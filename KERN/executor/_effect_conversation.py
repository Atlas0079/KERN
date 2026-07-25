from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..dynamic_text import DynamicTextError, render_dynamic_text
from ..execution_errors import executor_error
from ..interaction.conversation import ConversationEngine, ConversationRequest
from ._effect_binder import _base_bind, _require_int, _require_param, _resolve_param_token
from ._effect_child_bundle import run_child_bundle


def _bind_start_conversation(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	max_utterances = _require_int(params, effect_type, "max_utterances_per_tick", ctx)
	opening_text = str(_resolve_param_token(_require_param(params, effect_type, "opening_text"), ctx) or "")
	return {"effect": effect_type, "max_utterances_per_tick": max_utterances, "opening_text": opening_text}, ctx


def execute_start_conversation(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	initiator_id = str((context or {}).get("self_id", "") or "")
	location = ws.get_location_of_entity(initiator_id) if initiator_id else None
	if location is None:
		return [{"type": "ConversationCompleted", "conversation_id": "", "skipped_reason": "location_missing", "utterance_count": 0}]
	location_id = str(location.location_id)
	state = ws.runtime_state
	limit = int(state.dialogue_budget_limit_per_location)
	used = int(state.dialogue_budget_used_per_location.get(location_id, 0) or 0)
	remaining = max(0, limit - used)
	requested = max(0, int(data.get("max_utterances_per_tick", 0) or 0))
	max_utterances = min(requested, remaining)
	try:
		opening_text = render_dynamic_text(ws, context, data.get("opening_text", "")).strip()
	except DynamicTextError as exc:
		return executor_error(f"StartConversation.opening_text: {exc}")

	conversation_id = f"conv_{uuid4().hex[:12]}"
	result = ConversationEngine().conduct(
		ws,
		ConversationRequest(conversation_id, initiator_id, location_id, opening_text, max_utterances),
	)
	child_events: list[dict[str, Any]] = []
	if result.utterances:
		bundle = {
			"effects": [
				{
					"effect": "RecordInteraction",
					"actor_id": utterance.speaker_id,
					"verb": "Say",
					"target_id": "",
					"status": "success",
					"reason": "",
					"interaction_origin": "conversation",
					"extra": {
						"is_dialogue": True,
						"speech": utterance.text,
						"conversation_id": result.conversation_id,
						"utterance_index": int(utterance.utterance_index),
						"participants": list(result.participants),
					},
				}
				for utterance in result.utterances
			]
		}
		child_events = run_child_bundle(executor, ws, bundle, dict(context or {})).events
		state.dialogue_budget_used_per_location[location_id] = used + len(result.utterances)

	interaction_ids = [
		str((event.get("payload", {}) or {}).get("interaction_id", "") or "")
		for event in child_events
		if isinstance(event, dict) and str(event.get("type", "") or "") == "InteractionRecorded"
	]
	return [
		*child_events,
		{
			"type": "ConversationCompleted",
			"conversation_id": result.conversation_id,
			"location_id": result.location_id,
			"participants": list(result.participants),
			"interaction_ids": [item for item in interaction_ids if item],
			"utterance_count": len(result.utterances),
			"skipped_reason": result.skipped_reason,
			"budget_used_after": int(state.dialogue_budget_used_per_location.get(location_id, used) or 0),
			"budget_limit": limit,
		},
	]
