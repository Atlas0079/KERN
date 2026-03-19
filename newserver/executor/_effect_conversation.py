from __future__ import annotations

import random
import uuid
from typing import Any

from ..log_manager import get_logger


def execute_start_conversation(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	logger = get_logger()
	services = getattr(ws, "services", {}) or {}
	log_full = bool(services.get("dialogue_log_full", False))
	if not log_full:
		log_full = str(__import__("os").environ.get("DIALOGUE_LOG_FULL", "0") or "").strip().lower() in {"1", "true", "yes", "on"}
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
	consecutive_passes = 0
	utterance_count = 0
	spoken_count = 0
	transcript: list[dict[str, Any]] = []
	while utterance_count < remaining_rounds:
		speaker_id = participants[utterance_count % len(participants)]
		perception_system = services.get("perception_system")
		perception = {}
		if perception_system is not None and hasattr(perception_system, "perceive"):
			perception = perception_system.perceive(ws, speaker_id)
		else:
			perception = {"self_id": speaker_id, "location": {"id": location_id, "name": str(getattr(location, "location_name", "") or "")}, "entities": []}
		if isinstance(perception, dict):
			engine = services.get("interaction_engine")
			if engine is not None and hasattr(engine, "recipe_db") and isinstance(getattr(engine, "recipe_db"), dict):
				perception["recipe_db"] = dict(getattr(engine, "recipe_db"))
			limit = int(services.get("dialogue_budget_limit_per_location", limit_default) or limit_default)
			used_now = int((services.get("dialogue_budget_used_per_location", {}) or {}).get(location_id, used + utterance_count) or (used + utterance_count))
			perception["can_start_conversation_here"] = bool(used_now < limit)
		ent = ws.get_entity_by_id(speaker_id)
		ctrl = ent.get_component("AgentControlComponent") if ent is not None else None
		pid = str(getattr(ctrl, "provider_id", "") or "").strip() if ctrl is not None else ""
		default_action_provider = services.get("default_action_provider")
		action_providers = services.get("action_providers", {}) or {}
		provider = default_action_provider if not pid else action_providers.get(pid)
		line = ""
		if utterance_count == 0 and speaker_id == self_id and opening_text:
			line = opening_text
		elif provider is not None and hasattr(provider, "decide_dialogue"):
			line = str(
				provider.decide_dialogue(
					perception=perception if isinstance(perception, dict) else {},
					conversation_context={
						"conversation_id": conversation_id,
						"location_id": location_id,
						"participants": list(participants),
						"utterance_index": int(utterance_count),
						"max_utterances_per_tick": int(remaining_rounds),
					},
					self_id=speaker_id,
				)
				or ""
			).strip()
		pass_turn = (not line) or (line.upper() == "PASS")
		if pass_turn:
			consecutive_passes += 1
			transcript.append(
				{
					"utterance_index": int(utterance_count),
					"speaker_id": speaker_id,
					"text": "",
					"pass": True,
				}
			)
			events.append({"type": "ConversationPass", "conversation_id": conversation_id, "speaker_id": speaker_id, "location_id": location_id, "utterance_index": int(utterance_count)})
		else:
			consecutive_passes = 0
			spoken_count += 1
			transcript.append(
				{
					"utterance_index": int(utterance_count),
					"speaker_id": speaker_id,
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
					"utterance_index": int(utterance_count),
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
					"utterance_index": int(utterance_count),
				}
			)
		utterance_count += 1
		if consecutive_passes >= len(participants):
			break
	used_map[location_id] = used + utterance_count
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
