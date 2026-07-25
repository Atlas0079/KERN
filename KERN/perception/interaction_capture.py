from __future__ import annotations

from typing import Any

from ..models.components import PerceptionComponent


def _entity_location_id(ws: Any, entity_id: str) -> str:
	if not entity_id or not hasattr(ws, "get_location_of_entity"):
		return ""
	location = ws.get_location_of_entity(str(entity_id))
	return str(getattr(location, "location_id", "") or "") if location is not None else ""


def select_interaction_perceivers(ws: Any, record: dict[str, Any]) -> list[str]:
	"""Select memory-capable perceivers from the world state at interaction time."""
	if not isinstance(record, dict):
		return []
	actor_id = str(record.get("actor_id", "") or "")
	target_id = str(record.get("target_id", "") or "")
	interaction_location_id = str(record.get("location_id", "") or "")
	recipients: list[str] = []
	entities = getattr(ws, "entities", {}) or {}
	for entity_id in sorted(str(item) for item in entities.keys()):
		entity = ws.get_entity_by_id(entity_id) if hasattr(ws, "get_entity_by_id") else entities.get(entity_id)
		if entity is None or not hasattr(entity, "get_component"):
			continue
		perception = entity.get_component("PerceptionComponent")
		if not isinstance(perception, PerceptionComponent) or not bool(perception.enabled):
			continue
		is_participant = entity_id in {actor_id, target_id}
		is_same_location = bool(
			interaction_location_id
			and _entity_location_id(ws, entity_id) == interaction_location_id
		)
		if is_participant or is_same_location:
			recipients.append(entity_id)
	return recipients


def capture_interaction(ws: Any, record: dict[str, Any]) -> list[str]:
	"""Fan out an immutable interaction snapshot to perceivers in the same world transaction."""
	if not isinstance(record, dict):
		return []
	recipients = select_interaction_perceivers(ws, record)
	record["perceived_by_agent_ids"] = list(recipients)
	for entity_id in recipients:
		entity = ws.get_entity_by_id(entity_id) if hasattr(ws, "get_entity_by_id") else None
		if entity is None or not hasattr(entity, "get_component"):
			continue
		perception = entity.get_component("PerceptionComponent")
		if isinstance(perception, PerceptionComponent):
			perception.enqueue_interaction(record)
	return recipients
