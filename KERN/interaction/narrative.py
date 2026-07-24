from __future__ import annotations

from typing import Any


def entity_display_name(ws: Any, entity_id: Any) -> str:
	identifier = str(entity_id or "").strip()
	if not identifier or not hasattr(ws, "get_entity_by_id"):
		return identifier
	entity = ws.get_entity_by_id(identifier)
	if entity is None:
		return identifier
	name = str(getattr(entity, "entity_name", "") or identifier)
	if hasattr(entity, "get_component"):
		setting = entity.get_component("AgentSetting")
		if setting is not None:
			name = str(getattr(setting, "agent_name", "") or name)
	return name


def render_interaction_narrative(
	ws: Any,
	template: Any,
	context: dict[str, Any] | None = None,
	values: dict[str, Any] | None = None,
) -> str:
	"""Render one explicit interaction narrative from a stable context snapshot."""
	text = str(template or "")
	if not text.strip():
		return ""
	ctx = dict(context or {})
	params = ctx.get("parameters", {}) or {}
	render_values = dict(params) if isinstance(params, dict) else {}
	render_values.update(dict(values or {}))
	actor_id = str(ctx.get("actor_id", "") or ctx.get("self_id", "") or "")
	target_id = str(ctx.get("target_id", "") or ctx.get("event_entity_id", "") or "")
	render_values["actor"] = entity_display_name(ws, actor_id)
	render_values["target"] = entity_display_name(ws, target_id)
	render_values["reason"] = str(ctx.get("reason", "") or render_values.get("reason", "") or "")
	for key, value in render_values.items():
		text = text.replace("{" + str(key) + "}", str(value if value is not None else ""))
	return text
