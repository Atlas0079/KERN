from __future__ import annotations

from typing import Any

from ..interaction.presentation import interaction_content, interaction_is_failure
from ..models.components.memory import MemoryComponent


def _safe_str(value: Any) -> str:
	return str(value or "")


def _memory_from_raw(raw: dict[str, Any]) -> MemoryComponent:
	data = dict(raw or {}) if isinstance(raw, dict) else {}
	return MemoryComponent(
		short_term_queue=[dict(item) for item in list(data.get("short_term_queue", []) or []) if isinstance(item, dict)],
		short_term_max_entries=int(data.get("short_term_max_entries", 30) or 30),
		mid_term_prep_queue=[dict(item) for item in list(data.get("mid_term_prep_queue", []) or []) if isinstance(item, dict)],
		mid_term_prep_max_entries=int(data.get("mid_term_prep_max_entries", 50) or 50),
		mid_term_queue=[dict(item) for item in list(data.get("mid_term_queue", []) or []) if isinstance(item, dict)],
		mid_term_max_entries=int(data.get("mid_term_max_entries", 20) or 20),
		last_mid_term_summary_tick=int(data.get("last_mid_term_summary_tick", -1) or -1),
		mid_term_summary_cooldown_ticks=int(data.get("mid_term_summary_cooldown_ticks", 15) or 15),
	)


def _top_topics(items: list[dict[str, Any]], max_count: int = 3) -> list[str]:
	counter: dict[str, int] = {}
	for item in list(items or []):
		if not isinstance(item, dict):
			continue
		topic = _safe_str(item.get("topic")).strip()
		if topic:
			counter[topic] = int(counter.get(topic, 0) or 0) + 1
	sorted_items = sorted(counter.items(), key=lambda pair: (-int(pair[1]), str(pair[0])))
	return [str(key) for key, _count in sorted_items[: max(0, int(max_count or 0))]]


def _build_entities_index(full_ws_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
	out: dict[str, dict[str, Any]] = {}
	for item in list(full_ws_view.get("entities", []) or []):
		if not isinstance(item, dict):
			continue
		entity_id = _safe_str(item.get("id"))
		if entity_id:
			out[entity_id] = dict(item)
	return out


def _interaction_to_memory_entry(actor_id: str, item: dict[str, Any]) -> dict[str, Any]:
	owner = _safe_str(item.get("actor_id"))
	target_id = _safe_str(item.get("target_id"))
	location_id = _safe_str(item.get("location_id"))
	verb = _safe_str(item.get("verb"))
	status = _safe_str(item.get("status"))
	is_dialogue = bool(item.get("is_dialogue", False)) or verb == "Say"
	is_self_related = bool(owner == actor_id or target_id == actor_id)
	is_failure = interaction_is_failure(status)
	if is_dialogue:
		importance = 0.8 if is_self_related else 0.65
		topic = "social_dialogue"
	else:
		importance = 0.8 if is_self_related and is_failure else 0.65 if is_self_related else 0.5
		topic = "action_failed" if is_failure else "action_success"
	content = interaction_content(item)
	return {
		"tick": int(item.get("tick", 0) or 0),
		"time_str": _safe_str(item.get("time_str")),
		"type": "interaction",
		"topic": topic,
		"importance": float(importance),
		"location_id": location_id,
		"actor_id": owner,
		"target_id": target_id,
		"content": content,
		"source": {
			"kind": "interaction_log",
			"seq": int(item.get("seq", 0) or 0),
			"interaction_id": _safe_str(item.get("interaction_id")),
		},
	}


def build_memory_patch(
	full_ws_view: dict[str, Any],
	actor_id: str,
	min_importance: float = 0.45,
) -> dict[str, Any] | None:
	view = dict(full_ws_view or {}) if isinstance(full_ws_view, dict) else {}
	entities = _build_entities_index(view)
	actor = entities.get(_safe_str(actor_id), {})
	if not actor:
		return None
	memory = _memory_from_raw(dict(actor.get("memory", {}) or {}))
	interaction_inbox = [
		dict(item)
		for item in list(view.get("interaction_inbox", []) or [])
		if isinstance(item, dict)
	]

	notes: list[dict[str, Any]] = []
	consume_interaction_ids: list[str] = []
	seen_ids: set[str] = set()
	for item in interaction_inbox:
		interaction_id = _safe_str(item.get("interaction_id")).strip()
		if not interaction_id or interaction_id in seen_ids:
			continue
		seen_ids.add(interaction_id)
		consume_interaction_ids.append(interaction_id)
		entry = _interaction_to_memory_entry(_safe_str(actor_id), item)
		if float(entry.get("importance", 0.0) or 0.0) >= float(min_importance):
			notes.append(entry)
			memory.add_short_term(entry)

	mid_term_summaries: list[dict[str, Any]] = []
	clear_mid_term_prep = False
	now_tick = int(view.get("tick", 0) or 0)
	if memory.should_summarize_mid_term(now_tick):
		prep_items = [dict(item) for item in list(memory.mid_term_prep_queue or []) if isinstance(item, dict)]
		if prep_items:
			topics = _top_topics(prep_items, 3)
			ticks = [int((item or {}).get("tick", 0) or 0) for item in prep_items]
			mid_term_summaries.append(
				{
					"summary": f"阶段记忆摘要：记录{len(prep_items)}条，关键主题：{', '.join(topics) if topics else 'general'}。",
					"tick_start": min(ticks) if ticks else now_tick,
					"tick_end": max(ticks) if ticks else now_tick,
					"tags": topics,
				}
			)
			clear_mid_term_prep = True

	if not notes and not consume_interaction_ids and not mid_term_summaries:
		return None
	return {
		"notes": notes,
		"consume_interaction_ids": consume_interaction_ids,
		"mid_term_summaries": mid_term_summaries,
		"clear_mid_term_prep": bool(clear_mid_term_prep),
	}
