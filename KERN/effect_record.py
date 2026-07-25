from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


EVENT_ENVELOPE_KEY = "__kern_event_envelope__"


def build_runtime_event(event_type: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
	return EffectEvent(
		type=str(event_type or ""),
		source_effect="",
		input={},
		context=dict(context or {}),
		payload=dict(payload or {}),
	).to_dict()


@dataclass(frozen=True)
class EffectEvent:
	"""Committed-event envelope produced by one successful Effect."""

	type: str
	source_effect: str
	input: dict[str, Any]
	context: dict[str, Any] = field(default_factory=dict)
	payload: dict[str, Any] = field(default_factory=dict)
	bundle_id: str = ""
	parent_bundle_id: str = ""
	action_id: str = ""
	effect_index: int = -1

	def to_dict(self) -> dict[str, Any]:
		return {
			"type": str(self.type or ""),
			"source_effect": str(self.source_effect or ""),
			"input": deepcopy(dict(self.input or {})),
			"context": deepcopy(dict(self.context or {})),
			"payload": deepcopy(dict(self.payload or {})),
			"bundle_id": str(self.bundle_id or ""),
			"parent_bundle_id": str(self.parent_bundle_id or ""),
			"action_id": str(self.action_id or ""),
			"effect_index": int(self.effect_index),
			EVENT_ENVELOPE_KEY: True,
		}


def build_effect_events(
	effect: str,
	input_data: dict[str, Any],
	context: dict[str, Any],
	facts: Any,
	*,
	bundle_id: str = "",
	parent_bundle_id: str = "",
	action_id: str = "",
	effect_index: int = -1,
) -> list[dict[str, Any]]:
	"""Build ordered custom Events followed by the Effect's default Event."""
	clean_context = deepcopy(dict(context or {}))
	clean_context.pop("event", None)
	records: list[dict[str, Any]] = []
	for fact in list(facts or []):
		if not isinstance(fact, dict):
			continue
		if bool(fact.get(EVENT_ENVELOPE_KEY, False)):
			records.append(dict(fact))
			continue
		fact_data = deepcopy(dict(fact))
		event_type = str(fact_data.pop("type", "") or "").strip()
		if not event_type:
			event_type = str(effect or "")
		records.append(
			EffectEvent(
				type=event_type,
				source_effect=str(effect or ""),
				input=deepcopy(dict(input_data or {})),
				context=clean_context,
				payload=fact_data,
				bundle_id=str(bundle_id or ""),
				parent_bundle_id=str(parent_bundle_id or ""),
				action_id=str(action_id or ""),
				effect_index=int(effect_index),
			).to_dict()
		)
	records.append(
		EffectEvent(
			type=str(effect or ""),
			source_effect=str(effect or ""),
			input=deepcopy(dict(input_data or {})),
			context=clean_context,
			payload={},
			bundle_id=str(bundle_id or ""),
			parent_bundle_id=str(parent_bundle_id or ""),
			action_id=str(action_id or ""),
			effect_index=int(effect_index),
		).to_dict()
	)
	return records
