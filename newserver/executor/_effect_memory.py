from __future__ import annotations

from typing import Any

from ..models.components import MemoryComponent
from ._effect_binder import BindError, _base_bind, _require_param, _require_str, _resolve_param_token


def _bind_add_memory_note(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	text = str(_resolve_param_token(_require_param(params, effect_type, "text"), ctx) or "").strip()
	if not text:
		raise BindError(effect_type, ["text"])
	out: dict[str, Any] = {"effect": effect_type, "target": target, "text": text}
	if "importance" in params:
		out["importance"] = _resolve_param_token(params.get("importance"), ctx)
	if "tags" in params:
		out["tags"] = _resolve_param_token(params.get("tags"), ctx)
	return out, ctx


def execute_add_memory_note(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "self") or "self")
	target = executor._resolve_entity_from_ctx(ws, context, target_key)
	if target is None:
		return [{"type": "ExecutorError", "message": "AddMemoryNote: target missing"}]
	text = str(data.get("text", "") or "").strip()
	if not text:
		return [{"type": "ExecutorError", "message": "AddMemoryNote: text missing"}]
	imp_raw = data.get("importance", 0.5)
	try:
		importance = float(imp_raw)
	except Exception:
		importance = 0.5
	if importance < 0:
		importance = 0.0
	if importance > 1:
		importance = 1.0
	tags_raw = data.get("tags", []) or []
	tags = [str(x) for x in list(tags_raw)] if isinstance(tags_raw, list) else []
	mem = target.get_component("MemoryComponent")
	if not isinstance(mem, MemoryComponent):
		mem = MemoryComponent()
		target.add_component("MemoryComponent", mem)
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	mem.add_entry(text=text, tick=tick, importance=importance, tags=tags)
	return [{"type": "MemoryNoteAdded", "entity_id": target.entity_id, "text": text, "importance": importance, "tick": tick}]
