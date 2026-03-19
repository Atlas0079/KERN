from __future__ import annotations

from typing import Any


def resolve_entity_id(ref: Any, context: dict[str, Any] | None, allow_literal: bool = False) -> str:
	key = str(ref or "").strip()
	if not key:
		return ""
	ctx = context if isinstance(context, dict) else {}
	if key == "self":
		return str(ctx.get("self_id", "") or "")
	if key == "target":
		return str(ctx.get("target_id", "") or "")
	if key == "event_entity":
		if str(ctx.get("event_entity_id", "") or ""):
			return str(ctx.get("event_entity_id", "") or "")
		event = ctx.get("event", {}) or {}
		if isinstance(event, dict):
			return str(event.get("entity_id", "") or "")
		return ""
	if key.startswith("event."):
		event = ctx.get("event", {}) or {}
		if not isinstance(event, dict):
			return ""
		return str(event.get(key[len("event.") :], "") or "")
	if key.startswith("param:"):
		p = ctx.get("parameters", {}) or {}
		if not isinstance(p, dict):
			return ""
		return str(p.get(key[len("param:") :], "") or "")
	return key if allow_literal else ""


def resolve_entity(ws: Any, ref: Any, context: dict[str, Any] | None, allow_literal: bool = False) -> Any:
	entity_id = resolve_entity_id(ref, context, allow_literal=allow_literal)
	if not entity_id or not hasattr(ws, "get_entity_by_id"):
		return None
	return ws.get_entity_by_id(entity_id)
