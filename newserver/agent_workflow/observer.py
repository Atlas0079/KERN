from __future__ import annotations

from typing import Any


def _safe_str(v: Any) -> str:
	return str(v or "")


def _build_entity_index(full_ws_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
	out: dict[str, dict[str, Any]] = {}
	for item in list(full_ws_view.get("entities", []) or []):
		if not isinstance(item, dict):
			continue
		eid = _safe_str(item.get("id"))
		if eid:
			out[eid] = dict(item)
	return out


def _build_location_index(full_ws_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
	out: dict[str, dict[str, Any]] = {}
	for item in list(full_ws_view.get("locations", []) or []):
		if not isinstance(item, dict):
			continue
		lid = _safe_str(item.get("id"))
		if lid:
			out[lid] = dict(item)
	return out


def _short_term_text(items: list[dict[str, Any]], max_items: int = 30) -> str:
	raw = [dict(x) for x in list(items or []) if isinstance(x, dict)]
	if not raw:
		return ""
	lines: list[str] = []
	for e in raw[-int(max_items or 30) :]:
		content = _safe_str(e.get("content")).strip()
		if not content:
			continue
		tick = int(e.get("tick", 0) or 0)
		imp = float(e.get("importance", 0.5) or 0.5)
		topic = _safe_str(e.get("topic")).strip()
		topic_text = f"[{topic}] " if topic else ""
		lines.append(f"- [tick {tick}][imp {imp:.2f}] {topic_text}{content}")
	return "\n".join(lines)


def _mid_term_summary_text(items: list[dict[str, Any]], max_items: int = 4) -> str:
	raw = [dict(x) for x in list(items or []) if isinstance(x, dict)]
	if not raw:
		return ""
	lines: list[str] = []
	for e in raw[-int(max_items or 4) :]:
		summary = _safe_str(e.get("summary")).strip()
		if not summary:
			continue
		t0 = int(e.get("tick_start", 0) or 0)
		t1 = int(e.get("tick_end", 0) or 0)
		lines.append(f"- [tick {t0}-{t1}] {summary}")
	return "\n".join(lines)


def _build_map_topology(full_ws_view: dict[str, Any]) -> list[dict[str, Any]]:
	locations = _build_location_index(full_ws_view)
	paths = [dict(x) for x in list(full_ws_view.get("paths", []) or []) if isinstance(x, dict)]
	out: list[dict[str, Any]] = []
	for lid, loc in sorted(locations.items(), key=lambda kv: kv[0]):
		neighbors: list[dict[str, Any]] = []
		seen: set[str] = set()
		for p in paths:
			if bool(p.get("is_blocked", False)):
				continue
			if _safe_str(p.get("from_location_id")) != lid:
				continue
			to_id = _safe_str(p.get("to_location_id"))
			if not to_id or to_id in seen:
				continue
			seen.add(to_id)
			target = locations.get(to_id, {})
			neighbors.append(
				{
					"to_location_id": to_id,
					"to_location_name": _safe_str(target.get("name")) or to_id,
					"distance": float(p.get("distance", 0.0) or 0.0),
				}
			)
		neighbors.sort(key=lambda x: _safe_str(x.get("to_location_id")))
		out.append(
			{
				"location_id": lid,
				"location_name": _safe_str(loc.get("name")) or lid,
				"neighbors": neighbors,
			}
		)
	return out


def build_agent_perception(full_ws_view: dict[str, Any], self_id: str) -> dict[str, Any]:
	view = dict(full_ws_view or {}) if isinstance(full_ws_view, dict) else {}
	self_id_s = _safe_str(self_id)
	entities = _build_entity_index(view)
	locations = _build_location_index(view)
	self_ent = entities.get(self_id_s, {})
	self_loc_id = _safe_str(self_ent.get("location_id"))
	self_loc = locations.get(self_loc_id, {})
	paths = [dict(x) for x in list(view.get("paths", []) or []) if isinstance(x, dict)]

	# Build container containment index in current location.
	containment: dict[str, dict[str, str]] = {}
	for ent in entities.values():
		if _safe_str(ent.get("location_id")) != self_loc_id:
			continue
		slots = ent.get("container_slots", {}) or {}
		if not isinstance(slots, dict):
			continue
		for slot_id, slot_data in slots.items():
			slot = slot_data if isinstance(slot_data, dict) else {}
			for item_id in list(slot.get("items", []) or []):
				iid = _safe_str(item_id)
				if iid:
					containment[iid] = {"container_id": _safe_str(ent.get("id")), "slot_id": _safe_str(slot_id)}

	def _is_transit(eid: str) -> bool:
		ent = entities.get(eid, {})
		task = ent.get("worker_current_task", {}) or {}
		if not isinstance(task, dict) or not task:
			return False
		return _safe_str(task.get("task_type")) == "Travel" and _safe_str(task.get("task_status")) == "InProgress"

	location_entity_ids = [_safe_str(x) for x in list(self_loc.get("entities", []) or []) if _safe_str(x)]
	top_level_ids: list[str] = []
	for eid in location_entity_ids:
		if eid in containment:
			continue
		if _is_transit(eid):
			continue
		top_level_ids.append(eid)

	visible_ids: list[str] = []
	seen: set[str] = set()
	queue: list[str] = list(top_level_ids)
	while queue:
		current = _safe_str(queue.pop(0))
		if not current or current in seen:
			continue
		seen.add(current)
		if _is_transit(current):
			continue
		visible_ids.append(current)
		ent = entities.get(current, {})
		slots = ent.get("container_slots", {}) or {}
		if not isinstance(slots, dict):
			continue
		for _slot_id, slot_data in slots.items():
			slot = slot_data if isinstance(slot_data, dict) else {}
			cfg = slot.get("config", {}) or {}
			if not bool((cfg if isinstance(cfg, dict) else {}).get("transparent", False)):
				continue
			for child in list(slot.get("items", []) or []):
				cid = _safe_str(child)
				if cid and cid not in seen:
					queue.append(cid)

	visible_entities: list[dict[str, Any]] = []
	for eid in visible_ids:
		ent = entities.get(eid, {})
		if not ent:
			continue
		contain_info = containment.get(eid, {})
		visible_entities.append(
			{
				"id": _safe_str(ent.get("id")),
				"name": _safe_str(ent.get("agent_name")) or _safe_str(ent.get("name")),
				"tags": [str(x) for x in list(ent.get("tags", []) or [])],
				"statuses": [str(x) for x in list(ent.get("statuses", []) or [])],
				"contained_in": _safe_str(contain_info.get("container_id")),
				"contained_in_slot": _safe_str(contain_info.get("slot_id")),
				"is_top_level": bool(eid in location_entity_ids) and not bool(contain_info),
				"tasks": [dict(x) for x in list(ent.get("task_host_tasks", []) or []) if isinstance(x, dict)],
			}
		)

	reachable_locations: list[dict[str, Any]] = []
	for p in paths:
		if bool(p.get("is_blocked", False)):
			continue
		if _safe_str(p.get("from_location_id")) != self_loc_id:
			continue
		to_id = _safe_str(p.get("to_location_id"))
		target_loc = locations.get(to_id, {})
		reachable_locations.append(
			{
				"path_id": _safe_str(p.get("path_id")),
				"to_location_id": to_id,
				"to_location_name": _safe_str(target_loc.get("name")) or to_id,
				"distance": float(p.get("distance", 0.0) or 0.0),
			}
		)

	dialogue_limit = int(view.get("dialogue_budget_limit_per_location", 4) or 4)
	used_map = view.get("dialogue_budget_used_per_location", {}) or {}
	used_here = int((used_map if isinstance(used_map, dict) else {}).get(self_loc_id, 0) or 0)
	can_start_conversation_here = used_here < dialogue_limit

	mem = self_ent.get("memory", {}) or {}
	mem_short = [dict(x) for x in list(mem.get("short_term_queue", []) or []) if isinstance(x, dict)]
	mem_mid = [dict(x) for x in list(mem.get("mid_term_queue", []) or []) if isinstance(x, dict)]
	interrupt_preset_descriptions = self_ent.get("interrupt_preset_descriptions", {}) or {}
	available_interrupt_presets = sorted(
		[str(x) for x in list((self_ent.get("interrupt_presets", {}) or {}).keys()) if str(x)]
	)

	worker_task = self_ent.get("worker_current_task", {}) or {}
	return {
		"self_id": self_id_s,
		"agent_name": _safe_str(self_ent.get("agent_name")) or _safe_str(self_ent.get("name")),
		"personality_summary": _safe_str(self_ent.get("personality_summary")),
		"common_knowledge_summary": _safe_str(self_ent.get("common_knowledge_summary")),
		"short_term_memory_text": _short_term_text(mem_short, max_items=30),
		"short_term_memory_items": mem_short,
		"mid_term_summary": _mid_term_summary_text(mem_mid, max_items=4),
		"location": {"id": self_loc_id, "name": _safe_str(self_loc.get("name"))},
		"map_topology": _build_map_topology(view),
		"reachable_locations": reachable_locations,
		"can_start_conversation_here": bool(can_start_conversation_here),
		"entities": visible_entities,
		"current_task_id": _safe_str(worker_task.get("task_id")),
		"current_task_type": _safe_str(worker_task.get("task_type")),
		"current_task_status": _safe_str(worker_task.get("task_status")),
		"current_task_progress": float(worker_task.get("progress", 0.0) or 0.0),
		"current_task_required_progress": float(worker_task.get("required_progress", 0.0) or 0.0),
		"current_task_interrupt_mode": _safe_str(worker_task.get("interrupt_mode")),
		"current_task_can_interrupt": bool(worker_task.get("can_interrupt", False)),
		"current_task_can_cancel": bool(worker_task.get("can_cancel", False)),
		"active_interrupt_preset_id": _safe_str(self_ent.get("active_interrupt_preset_id")),
		"available_interrupt_presets": available_interrupt_presets,
		"interrupt_preset_summaries": [
			{"preset_id": pid, "description": _safe_str(interrupt_preset_descriptions.get(pid))}
			for pid in available_interrupt_presets
		],
		"inventory": [dict(x) for x in list(self_ent.get("inventory", []) or []) if isinstance(x, dict)],
		"hidden_entity_count": max(0, len(containment.keys()) - len([x for x in visible_ids if x in containment])),
		"tick": int(view.get("tick", 0) or 0),
	}
