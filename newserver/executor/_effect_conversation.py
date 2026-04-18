from __future__ import annotations

import random
import uuid
from typing import Any

from ..log_manager import get_logger
from ._effect_binder import _base_bind, _require_int, _require_param, _resolve_param_token


def _bind_start_conversation(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	max_utterances = _require_int(params, effect_type, "max_utterances_per_tick", ctx)
	opening_text = str(_resolve_param_token(_require_param(params, effect_type, "opening_text"), ctx) or "")
	return {"effect": effect_type, "max_utterances_per_tick": max_utterances, "opening_text": opening_text}, ctx


def execute_start_conversation(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	logger = get_logger()
	services = getattr(ws, "services", {}) or {}
	log_full = bool(services.get("dialogue_log_full", False))
	self_id = str((context or {}).get("self_id", "") or "")
	location = ws.get_location_of_entity(self_id) if self_id else None
	if location is None:
		return [{"type": "ConversationSkipped", "reason": "location_missing", "self_id": self_id}]
	location_id = str(location.location_id)
	limit_default = int(services.get("dialogue_budget_limit_per_location", 4) or 4)
	used_map = services.get("dialogue_budget_used_per_location")
	if not isinstance(used_map, dict):
		used_map = {}
		services["dialogue_budget_used_per_location"] = used_map
	used = int(used_map.get(location_id, 0) or 0)
	if used >= limit_default:
		return [{"type": "ConversationSkipped", "reason": "budget_exhausted", "location_id": location_id, "used": used, "limit": limit_default}]
	max_req = int(data.get("max_utterances_per_tick", 4) or 4)
	remaining_budget = max(0, limit_default - used)
	remaining_rounds = min(max_req, remaining_budget)
	if remaining_rounds <= 0:
		return [{"type": "ConversationSkipped", "reason": "budget_exhausted", "location_id": location_id, "used": used, "limit": limit_default}]
	participants: list[str] = []
	for eid in list(location.entities_in_location):
		ent = ws.get_entity_by_id(str(eid))
		if ent is None:
			continue
		ctrl = ent.get_component("AgentControlComponent")
		if ctrl is None:
			continue
		if not bool(getattr(ctrl, "enabled", True)):
			continue
		participants.append(str(ent.entity_id))
	if len(participants) < 2:
		return [{"type": "ConversationSkipped", "reason": "no_participants", "location_id": location_id}]
	opening_text = str(data.get("opening_text", "") or "").strip()
	others = [p for p in participants if p != self_id]
	random.shuffle(others)
	if self_id and self_id in participants:
		participants = [self_id] + others
	else:
		participants = others
	conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
	events: list[dict[str, Any]] = [
		{
			"type": "ConversationStarted",
			"conversation_id": conversation_id,
			"location_id": location_id,
			"participants": list(participants),
			"budget_limit": int(limit_default),
			"budget_used_before": int(used),
		}
	]

	def _build_perception_for_dialogue(speaker_id: str, spoken_so_far: int, transcript: list[dict[str, Any]]) -> dict[str, Any]:
		from ..agent_workflow.observer import build_agent_perception
		from ..agent_workflow.full_ws_view_builder import build_full_ws_view
		full_ws_view = build_full_ws_view(ws, speaker_id, "", {})
		perception = build_agent_perception(full_ws_view, speaker_id)
		engine = services.get("interaction_engine")
		if engine is not None and hasattr(engine, "recipe_db") and isinstance(getattr(engine, "recipe_db"), dict):
			perception["recipe_db"] = dict(getattr(engine, "recipe_db"))
		used_now = int(used + spoken_so_far)
		perception["can_start_conversation_here"] = bool(used_now < limit_default)
		perception["tick"] = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		perception["conversation_transcript"] = [dict(x) for x in list(transcript or [])]
		return dict(perception)

	def _resolve_provider_and_name(speaker_id: str) -> tuple[Any, str]:
		ent = ws.get_entity_by_id(speaker_id)
		ctrl = ent.get_component("AgentControlComponent") if ent is not None else None
		pid = str(getattr(ctrl, "provider_id", "") or "").strip() if ctrl is not None else ""
		default_action_provider = services.get("default_action_provider")
		action_providers = services.get("action_providers", {}) or {}
		provider = default_action_provider if not pid else action_providers.get(pid)
		speaker_name = str(getattr(ent, "entity_name", "") or speaker_id) if ent is not None else speaker_id
		if ent is not None and hasattr(ent, "get_component"):
			agent_setting = ent.get_component("AgentSetting")
			if agent_setting is not None:
				speaker_name = str(getattr(agent_setting, "agent_name", "") or speaker_name)
		return provider, speaker_name

	def _record_spoken_line(speaker_id: str, speaker_name: str, line: str, utterance_index: int, transcript: list[dict[str, Any]]) -> None:
		transcript.append(
			{
				"utterance_index": int(utterance_index),
				"speaker_id": speaker_id,
				"speaker_name": speaker_name,
				"text": line,
				"pass": False,
			}
		)
		logger.warn(
			"dialogue",
			"spoken",
			context={
				"conversation_id": conversation_id,
				"location_id": location_id,
				"speaker_id": speaker_id,
				"utterance_index": int(utterance_index),
				"text": line,
			},
		)
		ws.record_interaction_attempt(
			actor_id=speaker_id,
			verb="Say",
			target_id=speaker_id,
			status="success",
			reason="",
			recipe_id="conversation.say",
			extra={"is_dialogue": True, "conversation_id": conversation_id, "speech": line},
		)
		events.append(
			{
				"type": "ConversationSpoken",
				"conversation_id": conversation_id,
				"speaker_id": speaker_id,
				"location_id": location_id,
				"text": line,
				"utterance_index": int(utterance_index),
			}
		)

	spoken_count = 0
	transcript: list[dict[str, Any]] = []
	utterance_count = 0
	if self_id and opening_text:
		_initiator_provider, initiator_name = _resolve_provider_and_name(self_id)
		_record_spoken_line(self_id, initiator_name, opening_text, utterance_count, transcript)
		utterance_count += 1
		spoken_count += 1

	if utterance_count < remaining_rounds:
		for speaker_id in [p for p in participants if p != self_id]:
			if utterance_count >= remaining_rounds:
				break
			provider, speaker_name = _resolve_provider_and_name(speaker_id)
			if provider is None or not hasattr(provider, "decide_dialogue"):
				continue
			perception = _build_perception_for_dialogue(speaker_id, utterance_count, transcript)
			line = str(
				provider.decide_dialogue(
					perception=perception,
					conversation_context={
						"conversation_id": conversation_id,
						"location_id": location_id,
						"participants": list(participants),
						"utterance_index": int(utterance_count),
						"max_utterances_per_tick": int(remaining_rounds),
						"transcript": [dict(x) for x in list(transcript or [])],
						"dialogue_phase": "join_decision",
						"initiator_id": self_id,
					},
					self_id=speaker_id,
				)
				or ""
			).strip()
			if (not line) or (line.upper() == "PASS"):
				continue
			_record_spoken_line(speaker_id, speaker_name, line, utterance_count, transcript)
			utterance_count += 1
			spoken_count += 1

	used_map[location_id] = used + spoken_count
	events.append(
		{
			"type": "ConversationEnded",
			"conversation_id": conversation_id,
			"location_id": location_id,
			"utterance_count": int(utterance_count),
			"spoken_count": int(spoken_count),
			"budget_used_after": int(used_map[location_id]),
			"budget_limit": int(limit_default),
			"transcript": list(transcript),
			"joined_participants": [str(x.get("speaker_id", "") or "") for x in list(transcript) if isinstance(x, dict)],
		}
	)
	if spoken_count <= 0:
		logger.warn(
			"dialogue",
			"no_speech",
			context={
				"conversation_id": conversation_id,
				"location_id": location_id,
				"participants": list(participants),
				"utterance_count": int(utterance_count),
				"budget_limit": int(limit_default),
				"budget_used_before": int(used),
				"budget_used_after": int(used_map[location_id]),
				"transcript": list(transcript),
			},
		)
	elif log_full:
		logger.warn(
			"dialogue",
			"transcript",
			context={
				"conversation_id": conversation_id,
				"location_id": location_id,
				"participants": list(participants),
				"utterance_count": int(utterance_count),
				"spoken_count": int(spoken_count),
				"transcript": list(transcript),
			},
		)
	return events
