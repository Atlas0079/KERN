from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..sim.condition_evaluator import ConditionEvaluator
from ..task_policy import get_task_policy_from_task


def _read_memory_component_dict(ent: Any) -> dict[str, Any]:
	mem = ent.get_component("MemoryComponent") if hasattr(ent, "get_component") else None
	if mem is None:
		return {}
	def _interaction_memory_only(items: Any) -> list[dict[str, Any]]:
		out: list[dict[str, Any]] = []
		for item in list(items or []):
			if not isinstance(item, dict):
				continue
			source = item.get("source", {}) or {}
			if str(item.get("type", "") or "") == "event":
				continue
			if isinstance(source, dict) and str(source.get("kind", "") or "") == "event_log":
				continue
			out.append(dict(item))
		return out
	return {
		"short_term_queue": _interaction_memory_only(getattr(mem, "short_term_queue", [])),
		"short_term_max_entries": int(getattr(mem, "short_term_max_entries", 30) or 30),
		"mid_term_prep_queue": _interaction_memory_only(getattr(mem, "mid_term_prep_queue", [])),
		"mid_term_prep_max_entries": int(getattr(mem, "mid_term_prep_max_entries", 50) or 50),
		"mid_term_queue": _interaction_memory_only(getattr(mem, "mid_term_queue", [])),
		"mid_term_max_entries": int(getattr(mem, "mid_term_max_entries", 20) or 20),
		"last_mid_term_summary_tick": int(getattr(mem, "last_mid_term_summary_tick", -1) or -1),
		"mid_term_summary_cooldown_ticks": int(getattr(mem, "mid_term_summary_cooldown_ticks", 15) or 15),
	}


def _read_interaction_inbox(ent: Any) -> list[dict[str, Any]]:
	perception = ent.get_component("PerceptionComponent") if hasattr(ent, "get_component") else None
	return [
		deepcopy(item)
		for item in list(getattr(perception, "interaction_inbox", []) or [])
		if isinstance(item, dict)
	]


def _read_record_inbox(ent: Any) -> list[dict[str, Any]]:
	perception = ent.get_component("PerceptionComponent") if hasattr(ent, "get_component") else None
	return [
		deepcopy(item)
		for item in list(getattr(perception, "record_inbox", []) or [])
		if isinstance(item, dict)
	]


def _round1(value: Any) -> float | None:
	if value is None:
		return None
	try:
		return round(float(value), 1)
	except Exception:
		return None


def _int_or_default(value: Any, default: int) -> int:
	try:
		return int(value)
	except Exception:
		return int(default)


def _read_vitals(ent: Any) -> dict[str, float | None]:
	creature = ent.get_component("CreatureComponent") if hasattr(ent, "get_component") else None
	if creature is None:
		return {}
	out = {
		"hp": _round1(getattr(creature, "current_hp", None)),
		"max_hp": _round1(getattr(creature, "max_hp", None)),
		"energy": _round1(getattr(creature, "current_energy", None)),
		"max_energy": _round1(getattr(creature, "max_energy", None)),
		"nutrition": _round1(getattr(creature, "current_nutrition", None)),
		"max_nutrition": _round1(getattr(creature, "max_nutrition", None)),
	}
	if getattr(creature, "max_stress", None) is not None:
		out["stress"] = _round1(getattr(creature, "current_stress", None))
		out["max_stress"] = _round1(getattr(creature, "max_stress", None))
	return out


def _custom_component_data(ent: Any, component_name: str) -> dict[str, Any]:
	comp = ent.get_component(component_name) if hasattr(ent, "get_component") else None
	data = getattr(comp, "data", None)
	return dict(data) if isinstance(data, dict) else {}


def _description_by_source(source: Any, description: str, base_description: str, observed_description: str) -> str:
	source_id = str(source or "base").strip()
	if source_id == "observed":
		return observed_description or base_description or description
	if source_id == "description":
		return description or base_description or observed_description
	return base_description or description or observed_description


def _select_perception(ws: Any, ent: Any, actor_id: str, entity_id: str, description: str, base_description: str, observed_description: str) -> dict[str, str]:
	profile = _custom_component_data(ent, "PerceptionProfileComponent")
	levels = profile.get("levels", [])
	if not isinstance(levels, list):
		levels = []
	evaluator = ConditionEvaluator()
	context = {"self_id": str(actor_id or ""), "target_id": str(entity_id or "")}
	for level in levels:
		if not isinstance(level, dict):
			continue
		condition = level.get("condition", {}) or {}
		if not isinstance(condition, dict):
			continue
		if not evaluator.evaluate(ws, condition, context):
			continue
		return {
			"level": str(level.get("id", "") or "matched"),
			"description": _description_by_source(level.get("description", "base"), description, base_description, observed_description),
		}
	return {
		"level": str(profile.get("default_level", "") or "base"),
		"description": _description_by_source(profile.get("default_description", "base"), description, base_description, observed_description),
	}


def build_full_ws_view(
	ws: Any,
	actor_id: str,
	reason: str,
	mode_context: dict[str, Any],
) -> dict[str, Any]:
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
		description_comp = ent.get_component("DescriptionComponent") if hasattr(ent, "get_component") else None
		description = ""
		base_description = ""
		observed_description = ""
		if description_comp is not None:
			description = str(getattr(description_comp, "description", "") or "")
			if hasattr(description_comp, "passive_text"):
				base_description = str(description_comp.passive_text() or "")
			else:
				base_description = str(getattr(description_comp, "base_description", "") or description)
			if hasattr(description_comp, "observed_text"):
				observed_description = str(description_comp.observed_text() or "")
			else:
				observed_description = str(getattr(description_comp, "observed_description", "") or description)
		perception = _select_perception(ws, ent, actor_id, eid, description, base_description, observed_description)
		memory_dict = _read_memory_component_dict(ent)
		wake_policy = ent.get_component("AgentWakePolicyComponent") if hasattr(ent, "get_component") else None
		active_interrupt_preset_id = str(getattr(wake_policy, "active_interrupt_preset_id", "") or "") if wake_policy is not None else ""
		interrupt_presets = dict(getattr(wake_policy, "interrupt_presets", {}) or {}) if wake_policy is not None else {}
		interrupt_preset_descriptions = dict(getattr(wake_policy, "interrupt_preset_descriptions", {}) or {}) if wake_policy is not None else {}
		world_state_entity = ent.get_component("WorldStateEntityComponent") if hasattr(ent, "get_component") else None
		world_state_entity_data: dict[str, Any] = {}
		if world_state_entity is not None:
			world_state_entity_data = {
				"debug_visible": bool(getattr(world_state_entity, "debug_visible", True)),
				"visible_to_agents": bool(getattr(world_state_entity, "visible_to_agents", False)),
				"note": str(getattr(world_state_entity, "note", "") or ""),
			}

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
				"description": description,
				"base_description": base_description,
				"observed_description": observed_description,
				"perception_description": str(perception.get("description", "") or ""),
				"perception_level": str(perception.get("level", "") or "base"),
				"memory": memory_dict,
				"active_interrupt_preset_id": active_interrupt_preset_id,
				"interrupt_presets": interrupt_presets,
				"interrupt_preset_descriptions": interrupt_preset_descriptions,
				"task_host_tasks": task_host_tasks,
				"container_slots": container_slots,
				"inventory": inventory,
				"worker_current_task": worker_current_task,
				"vitals": _read_vitals(ent),
				"world_state_entity": world_state_entity_data,
			}
		)

	locations_out: list[dict[str, Any]] = []
	for loc in list(getattr(ws, "locations", {}).values()):
		if loc is None:
			continue
		location_id = str(getattr(loc, "location_id", "") or "")
		environment = {}
		if hasattr(ws, "get_environment_for_location"):
			environment = ws.get_environment_for_location(location_id)
		if not isinstance(environment, dict):
			environment = {}
		light_level = _int_or_default(environment.get("light_level", getattr(loc, "light_level", 2)), 2)
		locations_out.append(
			{
				"id": location_id,
				"name": str(getattr(loc, "location_name", "") or ""),
				"description": str(getattr(loc, "description", "") or ""),
				"light_level": light_level,
				"environment": dict(environment),
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

	actor_entity = ws.get_entity_by_id(str(actor_id)) if hasattr(ws, "get_entity_by_id") else None
	interaction_inbox = _read_interaction_inbox(actor_entity) if actor_entity is not None else []
	record_inbox = _read_record_inbox(actor_entity) if actor_entity is not None else []

	state = ws.runtime_state
	return {
		"self_id": str(actor_id),
		"tick": int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0),
		"time_str": str(getattr(getattr(ws, "game_time", None), "time_to_string", lambda: "")() or ""),
		"reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"entities": entities_out,
		"locations": locations_out,
		"paths": paths_out,
		"interaction_inbox": interaction_inbox,
		"record_inbox": record_inbox,
		"recent_interactions": [],
		"dialogue_budget_limit_per_location": state.dialogue_budget_limit_per_location,
		"dialogue_budget_used_per_location": dict(state.dialogue_budget_used_per_location),
	}
