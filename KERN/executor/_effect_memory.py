from __future__ import annotations

from typing import Any

from ..dynamic_text import DynamicTextError, render_dynamic_text
from ..execution_errors import executor_error
from ..models.components import MemoryComponent, PerceptionComponent
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
	target, err = executor.require_entity(ws, context, target_key, "AddMemoryNote", "target")
	if err is not None:
		return err
	try:
		text = render_dynamic_text(ws, context, data.get("text", "")).strip()
	except DynamicTextError as exc:
		return executor_error(f"AddMemoryNote.text: {exc}")
	if not text:
		return executor_error("AddMemoryNote: text missing")
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
	consume_ids = _resolve_param_token(params.get("consume_interaction_ids", []), ctx)
	out["consume_interaction_ids"] = [
		str(item)
		for item in list(consume_ids or [])
		if str(item or "").strip()
	] if isinstance(consume_ids, list) else []
	consume_record_ids = _resolve_param_token(params.get("consume_record_ids", []), ctx)
	out["consume_record_ids"] = [
		str(item)
		for item in list(consume_record_ids or [])
		if str(item or "").strip()
	] if isinstance(consume_record_ids, list) else []
	remove_short_term_ids = _resolve_param_token(params.get("remove_short_term_record_ids", []), ctx)
	out["remove_short_term_record_ids"] = [
		str(item)
		for item in list(remove_short_term_ids or [])
		if str(item or "").strip()
	] if isinstance(remove_short_term_ids, list) else []
	summaries = _resolve_param_token(params.get("mid_term_summaries", []), ctx)
	out["mid_term_summaries"] = [dict(x) for x in list(summaries or []) if isinstance(x, dict)] if isinstance(summaries, list) else []
	out["clear_mid_term_prep"] = bool(_resolve_param_token(params.get("clear_mid_term_prep", False), ctx))
	return out, ctx


def execute_apply_memory_patch(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "self") or "self")
	target, err = executor.require_entity(ws, context, target_key, "ApplyMemoryPatch", "target")
	if err is not None:
		return err
	mem = target.get_component("MemoryComponent")
	if not isinstance(mem, MemoryComponent):
		mem = MemoryComponent()
		target.add_component("MemoryComponent", mem)
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	notes = [dict(x) for x in list(data.get("notes", []) or []) if isinstance(x, dict)]
	for note in notes:
		mem.add_short_term(note)
	short_term_removed = mem.remove_short_term_by_record_ids(
		[
			str(item)
			for item in list(data.get("remove_short_term_record_ids", []) or [])
			if str(item or "").strip()
		]
	)
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
	consume_ids = [
		str(item)
		for item in list(data.get("consume_interaction_ids", []) or [])
		if str(item or "").strip()
	]
	perception = target.get_component("PerceptionComponent")
	interactions_consumed = perception.consume_interactions(consume_ids) if isinstance(perception, PerceptionComponent) else 0
	record_ids = [
		str(item)
		for item in list(data.get("consume_record_ids", []) or [])
		if str(item or "").strip()
	]
	records_consumed = perception.consume_records(record_ids) if isinstance(perception, PerceptionComponent) else 0
	return [
		{
			"type": "MemoryPatched",
			"entity_id": str(getattr(target, "entity_id", "") or ""),
			"notes_added": int(len(notes)),
			"interactions_consumed": int(interactions_consumed),
			"records_consumed": int(records_consumed),
			"short_term_removed": int(short_term_removed),
		}
	]
