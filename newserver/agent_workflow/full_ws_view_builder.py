from __future__ import annotations

from typing import Any

from ..task_policy import get_task_policy_from_task


def _read_memory_component_dict(ent: Any) -> dict[str, Any]:
	mem = ent.get_component("MemoryComponent") if hasattr(ent, "get_component") else None
	if mem is None:
		return {}
	return {
		"short_term_queue": [dict(x) for x in list(getattr(mem, "short_term_queue", []) or []) if isinstance(x, dict)],
		"short_term_max_entries": int(getattr(mem, "short_term_max_entries", 30) or 30),
		"mid_term_prep_queue": [dict(x) for x in list(getattr(mem, "mid_term_prep_queue", []) or []) if isinstance(x, dict)],
		"mid_term_prep_max_entries": int(getattr(mem, "mid_term_prep_max_entries", 50) or 50),
		"mid_term_queue": [dict(x) for x in list(getattr(mem, "mid_term_queue", []) or []) if isinstance(x, dict)],
		"mid_term_max_entries": int(getattr(mem, "mid_term_max_entries", 20) or 20),
		"last_mid_term_summary_tick": int(getattr(mem, "last_mid_term_summary_tick", -1) or -1),
		"mid_term_summary_cooldown_ticks": int(getattr(mem, "mid_term_summary_cooldown_ticks", 15) or 15),
		"last_event_seq_seen": int(getattr(mem, "last_event_seq_seen", 0) or 0),
		"last_interaction_seq_seen": int(getattr(mem, "last_interaction_seq_seen", 0) or 0),
	}


def _actor_memory_cursors(ws: Any, actor_id: str) -> tuple[int, int]:
	agent = ws.get_entity_by_id(actor_id) if hasattr(ws, "get_entity_by_id") else None
	if agent is None:
		return (0, 0)
	mem = agent.get_component("MemoryComponent") if hasattr(agent, "get_component") else None
	if mem is None:
		return (0, 0)
	return (
		int(getattr(mem, "last_event_seq_seen", 0) or 0),
		int(getattr(mem, "last_interaction_seq_seen", 0) or 0),
	)


def build_full_ws_view(ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	entities_out: list[dict[str, Any]] = []
	for ent in list(getattr(ws, "entities", {}).values()):
		if ent is None:
			continue
		eid = str(getattr(ent, "entity_id", "") or "")
		loc = ws.get_location_of_entity(eid) if hasattr(ws, "get_location_of_entity") else None
		loc_id = str(getattr(loc, "location_id", "") or "")
		tags = list(ent.get_all_tags()) if hasattr(ent, "get_all_tags") else []
		status_comp = ent.get_component("StatusComponent") if hasattr(ent, "get_component") else None
		statuses = [str(x) for x in list(getattr(status_comp, "statuses", []) or [])]
		agent_setting = ent.get_component("AgentSetting") if hasattr(ent, "get_component") else None
		agent_name = str(getattr(agent_setting, "agent_name", "") or "")
		personality_summary = str(getattr(agent_setting, "personality_summary", "") or "")
		common_knowledge_summary = str(getattr(agent_setting, "common_knowledge_summary", "") or "")
		memory_dict = _read_memory_component_dict(ent)
		arb = ent.get_component("DecisionArbiterComponent") if hasattr(ent, "get_component") else None
		active_interrupt_preset_id = str(getattr(arb, "active_interrupt_preset_id", "") or "") if arb is not None else ""
		interrupt_presets = dict(getattr(arb, "interrupt_presets", {}) or {}) if arb is not None else {}
		interrupt_preset_descriptions = dict(getattr(arb, "interrupt_preset_descriptions", {}) or {}) if arb is not None else {}

		task_host = ent.get_component("TaskHostComponent") if hasattr(ent, "get_component") else None
		task_list: list[Any] = []
		if task_host is not None and hasattr(task_host, "get_all_tasks"):
			task_list = list(task_host.get_all_tasks() or [])
		task_host_tasks: list[dict[str, Any]] = []
		for task in task_list:
			if task is None:
				continue
			params = dict(getattr(task, "parameters", {}) or {})
			task_host_tasks.append(
				{
					"task_id": str(getattr(task, "task_id", "") or ""),
					"task_type": str(getattr(task, "task_type", "") or ""),
					"task_status": str(getattr(task, "task_status", "") or ""),
					"progress": float(getattr(task, "progress", 0.0) or 0.0),
					"required_progress": float(getattr(task, "required_progress", 0.0) or 0.0),
					"assigned_agent_ids": [str(x) for x in list(getattr(task, "assigned_agent_ids", []) or [])],
					"is_available": not bool(getattr(task, "assigned_agent_ids", []) or []),
					"required_item_tag": str(params.get("required_item_tag", "") or ""),
					"done_status_id": str(params.get("done_status_id", "") or ""),
				}
			)

		container_slots: dict[str, Any] = {}
		container = ent.get_component("ContainerComponent") if hasattr(ent, "get_component") else None
		inventory: list[dict[str, Any]] = []
		if container is not None and hasattr(container, "slots"):
			for slot_id, slot in (getattr(container, "slots", {}) or {}).items():
				items = [str(x) for x in list(getattr(slot, "items", []) or [])]
				cfg = dict(getattr(slot, "config", {}) or {})
				container_slots[str(slot_id)] = {"items": items, "config": cfg}
				if str(eid) != str(actor_id):
					continue
				for item_id in items:
					item_ent = ws.get_entity_by_id(item_id) if hasattr(ws, "get_entity_by_id") else None
					if item_ent is None:
						continue
					item_status_comp = item_ent.get_component("StatusComponent") if hasattr(item_ent, "get_component") else None
					item_statuses = [str(x) for x in list(getattr(item_status_comp, "statuses", []) or [])]
					inventory.append(
						{
							"id": str(getattr(item_ent, "entity_id", "") or ""),
							"name": str(getattr(item_ent, "entity_name", "") or ""),
							"tags": list(item_ent.get_all_tags()) if hasattr(item_ent, "get_all_tags") else [],
							"slot": str(slot_id),
							"statuses": item_statuses,
						}
					)

		worker = ent.get_component("WorkerComponent") if hasattr(ent, "get_component") else None
		worker_current_task: dict[str, Any] = {}
		task_id = str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""
		if task_id and hasattr(ws, "get_task_by_id"):
			task = ws.get_task_by_id(task_id)
			if task is not None:
				policy = get_task_policy_from_task(task)
				mode = str(policy.get("interrupt_mode", "") or "")
				worker_current_task = {
					"task_id": str(getattr(task, "task_id", "") or ""),
					"task_type": str(getattr(task, "task_type", "") or ""),
					"task_status": str(getattr(task, "task_status", "") or ""),
					"progress": float(getattr(task, "progress", 0.0) or 0.0),
					"required_progress": float(getattr(task, "required_progress", 0.0) or 0.0),
					"interrupt_mode": mode,
					"can_interrupt": mode not in {"", "forbidden"},
					"can_cancel": bool(policy.get("allow_voluntary_cancel", True)),
				}
		entities_out.append(
			{
				"id": eid,
				"name": str(getattr(ent, "entity_name", "") or ""),
				"template_id": str(getattr(ent, "template_id", "") or ""),
				"location_id": loc_id,
				"tags": [str(x) for x in list(tags or [])],
				"statuses": statuses,
				"agent_name": agent_name,
				"personality_summary": personality_summary,
				"common_knowledge_summary": common_knowledge_summary,
				"memory": memory_dict,
				"active_interrupt_preset_id": active_interrupt_preset_id,
				"interrupt_presets": interrupt_presets,
				"interrupt_preset_descriptions": interrupt_preset_descriptions,
				"task_host_tasks": task_host_tasks,
				"container_slots": container_slots,
				"inventory": inventory,
				"worker_current_task": worker_current_task,
			}
		)

	locations_out: list[dict[str, Any]] = []
	for loc in list(getattr(ws, "locations", {}).values()):
		if loc is None:
			continue
		locations_out.append(
			{
				"id": str(getattr(loc, "location_id", "") or ""),
				"name": str(getattr(loc, "location_name", "") or ""),
				"entities": [str(x) for x in list(getattr(loc, "entities_in_location", []) or []) if str(x)],
			}
		)

	paths_out: list[dict[str, Any]] = []
	for path in list(getattr(ws, "paths", {}).values()):
		if path is None:
			continue
		paths_out.append(
			{
				"path_id": str(getattr(path, "path_id", "") or ""),
				"from_location_id": str(getattr(path, "from_location_id", "") or ""),
				"to_location_id": str(getattr(path, "to_location_id", "") or ""),
				"distance": float(getattr(path, "distance", 0.0) or 0.0),
				"is_blocked": bool(getattr(path, "is_blocked", False)),
			}
		)

	last_event_seq_seen, last_interaction_seq_seen = _actor_memory_cursors(ws, actor_id)
	event_delta: list[dict[str, Any]] = []
	for rec in list(getattr(ws, "event_log", []) or []):
		if not isinstance(rec, dict):
			continue
		if int(rec.get("seq", 0) or 0) > int(last_event_seq_seen):
			event_delta.append(dict(rec))
	interaction_delta: list[dict[str, Any]] = []
	for rec in list(getattr(ws, "interaction_log", []) or []):
		if not isinstance(rec, dict):
			continue
		if int(rec.get("seq", 0) or 0) > int(last_interaction_seq_seen):
			interaction_delta.append(dict(rec))

	services = getattr(ws, "services", {}) or {}
	return {
		"self_id": str(actor_id),
		"tick": int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0),
		"time_str": str(getattr(getattr(ws, "game_time", None), "time_to_string", lambda: "")() or ""),
		"reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"entities": entities_out,
		"locations": locations_out,
		"paths": paths_out,
		"event_delta": event_delta,
		"interaction_delta": interaction_delta,
		"dialogue_budget_limit_per_location": int(services.get("dialogue_budget_limit_per_location", 4) or 4),
		"dialogue_budget_used_per_location": dict(services.get("dialogue_budget_used_per_location", {}) or {}),
	}
