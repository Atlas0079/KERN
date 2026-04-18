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


def _bind_apply_memory_patch(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	out: dict[str, Any] = {"effect": effect_type, "target": target}
	notes = _resolve_param_token(params.get("notes", []), ctx)
	out["notes"] = [dict(x) for x in list(notes or []) if isinstance(x, dict)] if isinstance(notes, list) else []
	if "last_event_seq_seen" in params:
		out["last_event_seq_seen"] = _resolve_param_token(params.get("last_event_seq_seen"), ctx)
	if "last_interaction_seq_seen" in params:
		out["last_interaction_seq_seen"] = _resolve_param_token(params.get("last_interaction_seq_seen"), ctx)
	summaries = _resolve_param_token(params.get("mid_term_summaries", []), ctx)
	out["mid_term_summaries"] = [dict(x) for x in list(summaries or []) if isinstance(x, dict)] if isinstance(summaries, list) else []
	out["clear_mid_term_prep"] = bool(_resolve_param_token(params.get("clear_mid_term_prep", False), ctx))
	return out, ctx


def execute_apply_memory_patch(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "self") or "self")
	target = executor._resolve_entity_from_ctx(ws, context, target_key)
	if target is None:
		return [{"type": "ExecutorError", "message": "ApplyMemoryPatch: target missing"}]
	mem = target.get_component("MemoryComponent")
	if not isinstance(mem, MemoryComponent):
		mem = MemoryComponent()
		target.add_component("MemoryComponent", mem)
	notes = [dict(x) for x in list(data.get("notes", []) or []) if isinstance(x, dict)]
	for note in notes:
		mem.add_short_term(note)
	for item in [dict(x) for x in list(data.get("mid_term_summaries", []) or []) if isinstance(x, dict)]:
		summary = str(item.get("summary", "") or "").strip()
		if not summary:
			continue
		t0 = int(item.get("tick_start", 0) or 0)
		t1 = int(item.get("tick_end", 0) or 0)
		tags_raw = item.get("tags", []) or []
		tags = [str(x) for x in list(tags_raw)] if isinstance(tags_raw, list) else []
		mem.add_mid_term_summary(summary, t0, t1, tags)
	if bool(data.get("clear_mid_term_prep", False)):
		mem.mid_term_prep_queue = []
	if "last_event_seq_seen" in data:
		try:
			mem.last_event_seq_seen = max(int(mem.last_event_seq_seen or 0), int(data.get("last_event_seq_seen", 0) or 0))
		except Exception:
			pass
	if "last_interaction_seq_seen" in data:
		try:
			mem.last_interaction_seq_seen = max(
				int(mem.last_interaction_seq_seen or 0),
				int(data.get("last_interaction_seq_seen", 0) or 0),
			)
		except Exception:
			pass
	return [
		{
			"type": "MemoryPatched",
			"entity_id": str(getattr(target, "entity_id", "") or ""),
			"notes_added": int(len(notes)),
			"last_event_seq_seen": int(getattr(mem, "last_event_seq_seen", 0) or 0),
			"last_interaction_seq_seen": int(getattr(mem, "last_interaction_seq_seen", 0) or 0),
		}
	]
