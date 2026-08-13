from __future__ import annotations

from typing import Any

from ..models.components.memory import MemoryComponent


def _safe_str(value: Any) -> str:
	return str(value or "")


def _memory_from_raw(raw: dict[str, Any]) -> MemoryComponent:
	data = dict(raw)
	return MemoryComponent(
		short_term_queue=[dict(item) for item in list(data.get("short_term_queue", []) or [])],
		short_term_max_entries=int(data.get("short_term_max_entries", 30) or 30),
		mid_term_prep_queue=[dict(item) for item in list(data.get("mid_term_prep_queue", []) or [])],
		mid_term_prep_max_entries=int(data.get("mid_term_prep_max_entries", 50) or 50),
		mid_term_queue=[dict(item) for item in list(data.get("mid_term_queue", []) or [])],
		mid_term_max_entries=int(data.get("mid_term_max_entries", 20) or 20),
		last_mid_term_summary_tick=int(data.get("last_mid_term_summary_tick", -1) or -1),
		mid_term_summary_cooldown_ticks=int(data.get("mid_term_summary_cooldown_ticks", 15) or 15),
	)


def _top_topics(items: list[dict[str, Any]], max_count: int = 3) -> list[str]:
	counter: dict[str, int] = {}
	for item in items:
		topic = _safe_str(item.get("topic")).strip()
		if topic:
			counter[topic] = int(counter.get(topic, 0) or 0) + 1
	sorted_items = sorted(counter.items(), key=lambda pair: (-int(pair[1]), str(pair[0])))
	return [str(key) for key, _count in sorted_items[: max(0, int(max_count or 0))]]


def _build_entities_index(full_ws_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
	out: dict[str, dict[str, Any]] = {}
	for item in list(full_ws_view.get("entities", []) or []):
		entity_id = _safe_str(item.get("id"))
		if entity_id:
			out[entity_id] = dict(item)
	return out


def _record_to_memory_entry(actor_id: str, item: dict[str, Any]) -> dict[str, Any]:
	record_type = _safe_str(item.get("record_type")).strip() or "agent_record"
	importance = 0.7
	if record_type == "social_action":
		importance = 0.8
	elif record_type == "social_feed_view":
		importance = 0.65
	content = _safe_str(item.get("content")).strip()
	return {
		"tick": int(item.get("tick", 0) or 0),
		"time_str": _safe_str(item.get("time_str")),
		"type": "agent_record",
		"topic": record_type,
		"importance": float(importance),
		"location_id": _safe_str(item.get("location_id")),
		"actor_id": _safe_str(item.get("actor_id")) or _safe_str(actor_id),
		"target_id": _safe_str(item.get("target_id")),
		"content": content,
		"record_id": _safe_str(item.get("record_id")),
		"record_type": record_type,
		"source": {
			"kind": "agent_record",
			"record_id": _safe_str(item.get("record_id")),
			"source_effect": _safe_str(item.get("source_effect")),
		},
	}


def build_memory_patch(
	full_ws_view: dict[str, Any],
	actor_id: str,
	min_importance: float = 0.45,
) -> dict[str, Any] | None:
	view = dict(full_ws_view)
	entities = _build_entities_index(view)
	actor = entities.get(_safe_str(actor_id), {})
	if not actor:
		return None
	memory = _memory_from_raw(dict(actor.get("memory", {}) or {}))
	record_inbox = [
		dict(item)
		for item in list(view.get("record_inbox", []) or [])
	]

	notes: list[dict[str, Any]] = []
	consume_record_ids: list[str] = []
	seen_ids: set[str] = set()
	for item in record_inbox:
		record_id = _safe_str(item.get("record_id")).strip()
		if not record_id or record_id in seen_ids:
			continue
		seen_ids.add(record_id)
		consume_record_ids.append(record_id)
		entry = _record_to_memory_entry(_safe_str(actor_id), item)
		if not str(entry.get("content", "") or "").strip():
			continue
		if float(entry.get("importance", 0.0) or 0.0) >= float(min_importance):
			notes.append(entry)
			memory.add_short_term(entry)

	mid_term_summaries: list[dict[str, Any]] = []
	clear_mid_term_prep = False

	if not notes and not consume_record_ids and not mid_term_summaries:
		return None
	return {
		"notes": notes,
		"consume_interaction_ids": [],
		"consume_record_ids": consume_record_ids,
		"remove_short_term_record_ids": [],
		"mid_term_summaries": mid_term_summaries,
		"clear_mid_term_prep": bool(clear_mid_term_prep),
	}
