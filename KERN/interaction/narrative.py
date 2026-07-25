from __future__ import annotations

from typing import Any

from ..dynamic_text import entity_display_name, render_dynamic_text


def render_interaction_narrative(
	ws: Any,
	template: Any,
	context: dict[str, Any] | None = None,
	values: dict[str, Any] | None = None,
) -> str:
	"""Adapt interaction aliases onto the shared dynamic-text renderer."""
	text = str(template or "")
	if not text.strip():
		return ""
	ctx = dict(context or {})
	dynamic_values = dict(ctx.get("dynamic_values", {}) or {}) if isinstance(ctx.get("dynamic_values", {}), dict) else {}
	dynamic_values.update(dict(values or {}))
	actor_id = str(ctx.get("actor_id", "") or ctx.get("self_id", "") or "")
	target_id = str(ctx.get("target_id", "") or ctx.get("event_entity_id", "") or "")
	if actor_id:
		dynamic_values["actor"] = entity_display_name(ws, actor_id)
	else:
		dynamic_values.setdefault("actor", "")
	if target_id:
		dynamic_values["target"] = entity_display_name(ws, target_id)
	else:
		dynamic_values.setdefault("target", "")
	if str(ctx.get("reason", "") or ""):
		dynamic_values["reason"] = str(ctx.get("reason", "") or "")
	else:
		dynamic_values.setdefault("reason", "")
	ctx["dynamic_values"] = dynamic_values
	return render_dynamic_text(ws, ctx, text)
