from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EffectRecord:
	"""A successful, committed execution record for one Effect."""

	effect: str
	input: dict[str, Any]
	context: dict[str, Any] = field(default_factory=dict)
	facts: tuple[dict[str, Any], ...] = ()
	bundle_id: str = ""
	parent_bundle_id: str = ""
	action_id: str = ""
	effect_index: int = -1

	def to_dict(self) -> dict[str, Any]:
		facts = [deepcopy(dict(fact)) for fact in self.facts if isinstance(fact, dict)]
		primary = dict(facts[0]) if facts else {"type": "EffectExecuted"}
		primary.setdefault("type", "EffectExecuted")
		primary["record_type"] = "EffectRecord"
		primary["effect"] = str(self.effect or "")
		primary["input"] = deepcopy(dict(self.input or {}))
		record_context = dict(self.context or {})
		# The triggering event is already stored in the record stream.  Keeping a
		# recursive copy in every nested EffectRecord makes logs grow geometrically.
		record_context.pop("event", None)
		primary["_effect_context"] = deepcopy(record_context)
		primary["facts"] = facts
		primary["_effect_record"] = True
		if self.bundle_id:
			primary["bundle_id"] = str(self.bundle_id)
		if self.parent_bundle_id:
			primary["parent_bundle_id"] = str(self.parent_bundle_id)
		if self.action_id:
			primary["action_id"] = str(self.action_id)
		if self.effect_index >= 0:
			primary["effect_index"] = int(self.effect_index)
		return primary


def build_effect_records(
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
	"""Build a record for one successful Effect and its optional handler facts."""
	clean_facts = [deepcopy(dict(item)) for item in list(facts or []) if isinstance(item, dict)]
	if not clean_facts:
		clean_facts = [{}]
	records: list[dict[str, Any]] = []
	for fact in clean_facts:
		if bool(fact.get("_effect_record", False)):
			records.append(dict(fact))
			continue
		records.append(
			EffectRecord(
				effect=str(effect or ""),
				input=deepcopy(dict(input_data or {})),
				context=deepcopy(dict(context or {})),
				facts=(fact,) if fact else (),
				bundle_id=str(bundle_id or ""),
				parent_bundle_id=str(parent_bundle_id or ""),
				action_id=str(action_id or ""),
				effect_index=int(effect_index),
			).to_dict()
		)
	return records
