from __future__ import annotations

from typing import Any

from ..models.components.memory import MemoryComponent


DROP_EVENT_TYPES = {
	"TickAdvanced",
	"AdvanceTick",
	"ReactionTriggered",
	"ReactionApplied",
	"PropertyModified",
	"ConditionAdded",
	"ConditionRemoved",
	"CooldownSet",
	"MemoryNoteAdded",
	"MemoryPatched",
	"TaskProgressed",
	"ConversationStarted",
	"ConversationSpoken",
	"ConversationEnded",
}


def _safe_str(v: Any) -> str:
	return str(v or "")


def _memory_from_raw(raw: dict[str, Any]) -> MemoryComponent:
	d = dict(raw or {}) if isinstance(raw, dict) else {}
	return MemoryComponent(
		short_term_queue=[dict(x) for x in list(d.get("short_term_queue", []) or []) if isinstance(x, dict)],
		short_term_max_entries=int(d.get("short_term_max_entries", 30) or 30),
		mid_term_prep_queue=[dict(x) for x in list(d.get("mid_term_prep_queue", []) or []) if isinstance(x, dict)],
		mid_term_prep_max_entries=int(d.get("mid_term_prep_max_entries", 50) or 50),
		mid_term_queue=[dict(x) for x in list(d.get("mid_term_queue", []) or []) if isinstance(x, dict)],
		mid_term_max_entries=int(d.get("mid_term_max_entries", 20) or 20),
		last_mid_term_summary_tick=int(d.get("last_mid_term_summary_tick", -1) or -1),
		mid_term_summary_cooldown_ticks=int(d.get("mid_term_summary_cooldown_ticks", 15) or 15),
		last_event_seq_seen=int(d.get("last_event_seq_seen", 0) or 0),
		last_interaction_seq_seen=int(d.get("last_interaction_seq_seen", 0) or 0),
	)


def _top_topics(items: list[dict[str, Any]], max_count: int = 3) -> list[str]:
	counter: dict[str, int] = {}
	for item in list(items or []):
		if not isinstance(item, dict):
			continue
		topic = _safe_str(item.get("topic")).strip()
		if not topic:
			continue
		counter[topic] = int(counter.get(topic, 0) or 0) + 1
	sorted_items = sorted(counter.items(), key=lambda x: (-int(x[1]), str(x[0])))
	return [str(k) for k, _ in sorted_items[: max(0, int(max_count or 0))]]


def _build_entities_index(full_ws_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
	out: dict[str, dict[str, Any]] = {}
	for item in list(full_ws_view.get("entities", []) or []):
		if not isinstance(item, dict):
			continue
		eid = _safe_str(item.get("id"))
		if eid:
			out[eid] = dict(item)
	return out


def _interaction_content(
	recipe_db: dict[str, Any],
	item: dict[str, Any],
	actor_name: str,
	target_name: str,
	verb: str,
	status: str,
	reason: str,
	recipe_id: str,
) -> str:
	recipe = dict(recipe_db.get(recipe_id, {}) or {}) if isinstance(recipe_db, dict) else {}
	template = _safe_str(recipe.get("narrative_fail" if status == "failed" else "narrative_success"))
	values = dict(item or {})
	values["actor"] = actor_name
	values["target"] = target_name
	values["reason"] = reason
	if template:
		out = template
		for k, v in values.items():
			out = out.replace("{" + str(k) + "}", str(v if v is not None else ""))
		return out
	if status == "failed":
		if target_name:
			return f"{actor_name}对{target_name}执行{verb}失败：{reason or 'unknown'}"
		return f"{actor_name}执行{verb}失败：{reason or 'unknown'}"
	if target_name:
		return f"{actor_name}对{target_name}执行了{verb}"
	return f"{actor_name}执行了{verb}"


def _event_to_memory_entry(actor_id: str, actor_loc_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
	ev = item.get("event", {}) or {}
	if not isinstance(ev, dict):
		return None
	ev_type = _safe_str(ev.get("type")).strip()
	if not ev_type or ev_type in DROP_EVENT_TYPES:
		return None
	owner = _safe_str(item.get("actor_id"))
	location_id = _safe_str(item.get("location_id"))
	event_entity_id = _safe_str(ev.get("entity_id"))
	is_self_related = bool(owner == actor_id or event_entity_id == actor_id)
	is_same_location = bool(location_id and location_id == actor_loc_id)
	if not is_self_related and not is_same_location:
		return None
	topic = "event"
	importance = 0.5
	if "Task" in ev_type:
		topic = "task"
		importance = 0.65 if is_self_related else 0.5
	elif ev_type in {"KillEntity", "EntityDestroyed"}:
		topic = "threat"
		importance = 0.85
	elif ev_type.startswith("Conversation"):
		topic = "social"
		importance = 0.55
	content = ev_type
	if ev_type.startswith("Task"):
		task_id = _safe_str(ev.get("task_id"))
		if task_id:
			content = f"{ev_type} {task_id}"
	elif ev_type.startswith("Conversation"):
		cid = _safe_str(ev.get("conversation_id"))
		if cid:
			content = f"{ev_type} {cid}"
	return {
		"tick": int(item.get("tick", 0) or 0),
		"time_str": "",
		"type": "event",
		"topic": topic,
		"importance": float(importance),
		"location_id": location_id,
		"actor_id": owner,
		"target_id": event_entity_id,
		"content": content,
		"source": {"kind": "event_log", "seq": int(item.get("seq", 0) or 0)},
	}


def _interaction_to_memory_entry(
	recipe_db: dict[str, Any],
	actor_id: str,
	actor_loc_id: str,
	item: dict[str, Any],
) -> dict[str, Any] | None:
	if bool(item.get("is_reaction", False)):
		return None
	owner = _safe_str(item.get("actor_id"))
	owner_name = _safe_str(item.get("actor_name")) or owner
	target_id = _safe_str(item.get("target_id"))
	target_name = _safe_str(item.get("target_name")) or target_id
	location_id = _safe_str(item.get("location_id"))
	verb = _safe_str(item.get("verb"))
	status = _safe_str(item.get("status"))
	reason = _safe_str(item.get("reason"))
	recipe_id = _safe_str(item.get("recipe_id"))
	speech = _safe_str(item.get("speech")).strip()
	is_dialogue = bool(item.get("is_dialogue", False)) or verb == "Say"
	is_self_related = bool(owner == actor_id or target_id == actor_id)
	is_same_location = bool(location_id and location_id == actor_loc_id)
	if not is_self_related and not is_same_location:
		return None
	if is_dialogue:
		importance = 0.8 if is_self_related else 0.65
		topic = "social_dialogue"
		content = f"{owner_name}：{speech}" if speech else f"{owner_name}：{verb} {status}"
	else:
		importance = 0.8 if is_self_related and status == "failed" else 0.65 if is_self_related else 0.5
		topic = "action_failed" if status == "failed" else "action_success"
		content = _interaction_content(recipe_db, item, owner_name, target_name, verb, status, reason, recipe_id)
	return {
		"tick": int(item.get("tick", 0) or 0),
		"time_str": "",
		"type": "interaction",
		"topic": topic,
		"importance": float(importance),
		"location_id": location_id,
		"actor_id": owner,
		"target_id": target_id,
		"content": content,
		"source": {"kind": "interaction_log", "seq": int(item.get("seq", 0) or 0)},
	}


def build_memory_patch(
	full_ws_view: dict[str, Any],
	recipe_db: dict[str, Any],
	actor_id: str,
	min_importance: float = 0.45,
) -> dict[str, Any] | None:
	view = dict(full_ws_view or {}) if isinstance(full_ws_view, dict) else {}
	entities = _build_entities_index(view)
	actor = entities.get(_safe_str(actor_id), {})
	if not actor:
		return None
	actor_loc_id = _safe_str(actor.get("location_id"))
	mem_raw = dict(actor.get("memory", {}) or {})
	mem = _memory_from_raw(mem_raw)

	last_event_seq_seen = int(getattr(mem, "last_event_seq_seen", 0) or 0)
	last_interaction_seq_seen = int(getattr(mem, "last_interaction_seq_seen", 0) or 0)
	event_delta = [dict(x) for x in list(view.get("event_delta", []) or []) if isinstance(x, dict)]
	interaction_delta = [dict(x) for x in list(view.get("interaction_delta", []) or []) if isinstance(x, dict)]

	notes: list[dict[str, Any]] = []
	new_last_event = last_event_seq_seen
	new_last_interaction = last_interaction_seq_seen

	for item in event_delta:
		seq = int(item.get("seq", 0) or 0)
		if seq <= last_event_seq_seen:
			continue
		entry = _event_to_memory_entry(_safe_str(actor_id), actor_loc_id, item)
		new_last_event = max(new_last_event, seq)
		if entry is None:
			continue
		if float(entry.get("importance", 0.0) or 0.0) >= float(min_importance):
			notes.append(entry)
			mem.add_short_term(entry)

	for item in interaction_delta:
		seq = int(item.get("seq", 0) or 0)
		if seq <= last_interaction_seq_seen:
			continue
		entry = _interaction_to_memory_entry(recipe_db, _safe_str(actor_id), actor_loc_id, item)
		new_last_interaction = max(new_last_interaction, seq)
		if entry is None:
			continue
		if float(entry.get("importance", 0.0) or 0.0) >= float(min_importance):
			notes.append(entry)
			mem.add_short_term(entry)

	mid_term_summaries: list[dict[str, Any]] = []
	clear_mid_term_prep = False
	now_tick = int(view.get("tick", 0) or 0)
	if mem.should_summarize_mid_term(now_tick):
		prep_items = [dict(x) for x in list(mem.mid_term_prep_queue or []) if isinstance(x, dict)]
		if prep_items:
			topics = _top_topics(prep_items, 3)
			summary = f"阶段记忆摘要：记录{len(prep_items)}条，关键主题：{', '.join(topics) if topics else 'general'}。"
			ticks = [int((x or {}).get('tick', 0) or 0) for x in prep_items]
			mid_term_summaries.append(
				{
					"summary": summary,
					"tick_start": min(ticks) if ticks else now_tick,
					"tick_end": max(ticks) if ticks else now_tick,
					"tags": topics,
				}
			)
			clear_mid_term_prep = True

	if not notes and not mid_term_summaries and new_last_event == last_event_seq_seen and new_last_interaction == last_interaction_seq_seen:
		return None
	return {
		"notes": notes,
		"last_event_seq_seen": int(new_last_event),
		"last_interaction_seq_seen": int(new_last_interaction),
		"mid_term_summaries": mid_term_summaries,
		"clear_mid_term_prep": bool(clear_mid_term_prep),
	}
