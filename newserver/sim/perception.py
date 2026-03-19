from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.components import AgentSetting, ContainerComponent, DecisionArbiterComponent, MemoryComponent, TaskHostComponent, WorkerComponent


@dataclass
class TaskView:
	task_id: str = ""
	task_type: str = ""
	task_status: str = ""
	progress: float = 0.0
	required_progress: float = 0.0
	assigned_agent_ids: list[str] = field(default_factory=list)
	is_available: bool = True
	required_item_tag: str = ""
	done_condition_id: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"task_id": self.task_id,
			"task_type": self.task_type,
			"task_status": self.task_status,
			"progress": float(self.progress),
			"required_progress": float(self.required_progress),
			"assigned_agent_ids": list(self.assigned_agent_ids),
			"is_available": bool(self.is_available),
			"required_item_tag": self.required_item_tag,
			"done_condition_id": self.done_condition_id,
		}


@dataclass
class EntityView:
	entity_id: str = ""
	name: str = ""
	tags: list[str] = field(default_factory=list)
	contained_in: str = ""
	contained_in_slot: str = ""
	is_top_level: bool = False
	tasks: list[TaskView] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return {
			"id": self.entity_id,
			"name": self.name,
			"tags": list(self.tags),
			"contained_in": self.contained_in,
			"contained_in_slot": self.contained_in_slot,
			"is_top_level": bool(self.is_top_level),
			"tasks": [task.to_dict() for task in list(self.tasks or [])],
		}


@dataclass
class AgentStateView:
	agent_name: str = ""
	personality_summary: str = ""
	common_knowledge_summary: str = ""
	mid_term_summary: str = ""
	short_term_memory_text: str = ""
	short_term_memory_items: list[dict[str, Any]] = field(default_factory=list)
	active_interrupt_preset_id: str = ""
	available_interrupt_presets: list[str] = field(default_factory=list)
	interrupt_preset_summaries: list[dict[str, str]] = field(default_factory=list)
	current_task_id: str = ""
	current_task_type: str = ""
	current_task_status: str = ""
	current_task_progress: float = 0.0
	current_task_required_progress: float = 0.0

	def to_dict(self) -> dict[str, Any]:
		return {
			"agent_name": self.agent_name,
			"personality_summary": self.personality_summary,
			"common_knowledge_summary": self.common_knowledge_summary,
			"mid_term_summary": self.mid_term_summary,
			"short_term_memory_text": self.short_term_memory_text,
			"short_term_memory_items": list(self.short_term_memory_items),
			"active_interrupt_preset_id": self.active_interrupt_preset_id,
			"available_interrupt_presets": list(self.available_interrupt_presets),
			"interrupt_preset_summaries": list(self.interrupt_preset_summaries),
			"current_task_id": self.current_task_id,
			"current_task_type": self.current_task_type,
			"current_task_status": self.current_task_status,
			"current_task_progress": float(self.current_task_progress),
			"current_task_required_progress": float(self.current_task_required_progress),
		}


@dataclass
class PerceptionSystem:
	"""
	Perception System:
	- Provide agent's location
	- Provide "visible" entities in location (including id/name/tags)

	V2 (Current Implementation): Support container visibility
	- Location stores "Spatial Index": entities_in_location
	- Container (ContainerComponent) stores "Containment Relationship"
	- Default: Contained entities are invisible
	- If container slot.config.transparent == true: Entities in that slot are visible, and transparent contents are recursively expanded.
	"""

	def perceive(self, ws: Any, self_id: str) -> dict[str, Any]:
		if self.is_observation_blocked(ws, self_id):
			return self._empty_perception_result(ws, self_id)
		loc = ws.get_location_of_entity(self_id)
		if loc is None:
			return self._empty_perception_result(ws, self_id)

		containment_index = self._build_containment_index(ws, loc.location_id)
		visible_ids = self._compute_visible_ids(ws, loc, containment_index)
		entities = self._build_entities_view(ws, loc, visible_ids, containment_index)
		reachable_locations = self._build_reachable_locations(ws, str(loc.location_id))
		can_start_conversation_here = self._can_start_conversation_here(ws, str(loc.location_id))
		agent_state = self._build_agent_state(ws, self_id)
		hidden_entity_count = self._count_hidden_entities(containment_index, visible_ids)
		agent_state_data = agent_state.to_dict()
		entities_data = [entity.to_dict() for entity in list(entities or [])]

		return {
			"self_id": self_id,
			"agent_name": str(agent_state_data.get("agent_name", "") or ""),
			"personality_summary": str(agent_state_data.get("personality_summary", "") or ""),
			"common_knowledge_summary": str(agent_state_data.get("common_knowledge_summary", "") or ""),
			"short_term_memory_text": str(agent_state_data.get("short_term_memory_text", "") or ""),
			"short_term_memory_items": list(agent_state_data.get("short_term_memory_items", []) or []),
			"mid_term_summary": str(agent_state_data.get("mid_term_summary", "") or ""),
			"location": {"id": loc.location_id, "name": loc.location_name},
			"map_topology": self._build_map_topology(ws),
			"reachable_locations": reachable_locations,
			"can_start_conversation_here": bool(can_start_conversation_here),
			"entities": entities_data,
			"current_task_id": str(agent_state_data.get("current_task_id", "") or ""),
			"current_task_type": str(agent_state_data.get("current_task_type", "") or ""),
			"current_task_status": str(agent_state_data.get("current_task_status", "") or ""),
			"current_task_progress": float(agent_state_data.get("current_task_progress", 0.0) or 0.0),
			"current_task_required_progress": float(agent_state_data.get("current_task_required_progress", 0.0) or 0.0),
			"active_interrupt_preset_id": str(agent_state_data.get("active_interrupt_preset_id", "") or ""),
			"available_interrupt_presets": list(agent_state_data.get("available_interrupt_presets", []) or []),
			"interrupt_preset_summaries": list(agent_state_data.get("interrupt_preset_summaries", []) or []),
			"inventory": self._get_inventory(ws, self_id),
			"hidden_entity_count": int(hidden_entity_count),
		}

	def _compute_visible_ids(self, ws: Any, loc: Any, containment_index: dict[str, dict[str, str]]) -> list[str]:
		contained_ids = set(containment_index.keys())
		top_level_ids: list[str] = []
		for eid in list(getattr(loc, "entities_in_location", []) or []):
			eid_s = str(eid)
			if not eid_s or eid_s in contained_ids:
				continue
			if self.is_observation_blocked(ws, eid_s):
				continue
			top_level_ids.append(eid_s)
		return self._expand_transparent_contents(ws, top_level_ids)

	def _build_entities_view(
		self,
		ws: Any,
		loc: Any,
		visible_ids: list[str],
		containment_index: dict[str, dict[str, str]],
	) -> list[EntityView]:
		location_entity_ids = set([str(x) for x in list(getattr(loc, "entities_in_location", []) or [])])
		entities: list[EntityView] = []
		for eid in list(visible_ids or []):
			ent = ws.get_entity_by_id(str(eid))
			if ent is None:
				continue
			if self.is_observation_blocked(ws, str(getattr(ent, "entity_id", "") or "")):
				continue
			containment = containment_index.get(str(eid), {})
			contained_in = str((containment or {}).get("container_id", "") or "")
			contained_in_slot = str((containment or {}).get("slot_id", "") or "")
			entities.append(
				EntityView(
					entity_id=str(ent.entity_id),
					name=self._get_entity_visible_name(ent),
					tags=list(ent.get_all_tags()),
					contained_in=contained_in,
					contained_in_slot=contained_in_slot,
					is_top_level=bool(str(eid) in location_entity_ids) and not bool(contained_in),
					tasks=self._extract_host_tasks(ent),
				)
			)
		return entities

	def _get_entity_visible_name(self, ent: Any) -> str:
		name = str(getattr(ent, "entity_name", "") or "")
		setting_comp = ent.get_component("AgentSetting") if hasattr(ent, "get_component") else None
		if isinstance(setting_comp, AgentSetting):
			return str(getattr(setting_comp, "agent_name", "") or name)
		return name

	def _extract_host_tasks(self, ent: Any) -> list[TaskView]:
		host = ent.get_component("TaskHostComponent") if hasattr(ent, "get_component") else None
		if not isinstance(host, TaskHostComponent):
			return []
		task_list: list[Any] = []
		if hasattr(host, "get_all_tasks"):
			task_list = list(host.get_all_tasks() or [])
		elif hasattr(host, "tasks") and isinstance(getattr(host, "tasks"), dict):
			task_list = list(getattr(host, "tasks").values())
		tasks_out: list[TaskView] = []
		for task in task_list:
			tasks_out.append(self._task_to_view(task))
		return tasks_out

	def _task_to_view(self, task: Any) -> TaskView:
		assigned = getattr(task, "assigned_agent_ids", []) or []
		assigned_ids = [str(x) for x in list(assigned) if str(x)]
		params = getattr(task, "parameters", {}) or {}
		required_item_tag = ""
		done_condition_id = ""
		if isinstance(params, dict):
			required_item_tag = str(params.get("required_item_tag", "") or "")
			done_condition_id = str(params.get("done_condition_id", "") or "")
		return TaskView(
			task_id=str(getattr(task, "task_id", "") or ""),
			task_type=str(getattr(task, "task_type", "") or ""),
			task_status=str(getattr(task, "task_status", "") or ""),
			progress=float(getattr(task, "progress", 0.0) or 0.0),
			required_progress=float(getattr(task, "required_progress", 0.0) or 0.0),
			assigned_agent_ids=assigned_ids,
			is_available=not bool(assigned_ids),
			required_item_tag=required_item_tag,
			done_condition_id=done_condition_id,
		)

	def _build_reachable_locations(self, ws: Any, location_id: str) -> list[dict[str, Any]]:
		reachable_locations: list[dict[str, Any]] = []
		for path in ws.get_paths_from(location_id):
			if bool(path.is_blocked):
				continue
			target_loc = ws.get_location_by_id(path.to_location_id)
			reachable_locations.append(
				{
					"path_id": str(path.path_id),
					"to_location_id": str(path.to_location_id),
					"to_location_name": str(target_loc.location_name) if target_loc is not None else str(path.to_location_id),
					"distance": float(path.distance),
				}
			)
		return reachable_locations

	def _can_start_conversation_here(self, ws: Any, location_id: str) -> bool:
		services = getattr(ws, "services", {}) or {}
		dialogue_limit = int(services.get("dialogue_budget_limit_per_location", 4) or 4)
		used_map = services.get("dialogue_budget_used_per_location", {}) or {}
		dialogue_used = int((used_map if isinstance(used_map, dict) else {}).get(str(location_id), 0) or 0)
		return dialogue_used < dialogue_limit

	def _empty_perception_result(self, ws: Any, self_id: str) -> dict[str, Any]:
		agent_state_data = self._build_agent_state(ws, self_id).to_dict()
		return {
			"self_id": str(self_id),
			"agent_name": str(agent_state_data.get("agent_name", "") or ""),
			"personality_summary": str(agent_state_data.get("personality_summary", "") or ""),
			"common_knowledge_summary": str(agent_state_data.get("common_knowledge_summary", "") or ""),
			"short_term_memory_text": str(agent_state_data.get("short_term_memory_text", "") or ""),
			"short_term_memory_items": list(agent_state_data.get("short_term_memory_items", []) or []),
			"mid_term_summary": str(agent_state_data.get("mid_term_summary", "") or ""),
			"location": None,
			"map_topology": [],
			"reachable_locations": [],
			"can_start_conversation_here": False,
			"entities": [],
			"current_task_id": str(agent_state_data.get("current_task_id", "") or ""),
			"current_task_type": str(agent_state_data.get("current_task_type", "") or ""),
			"current_task_status": str(agent_state_data.get("current_task_status", "") or ""),
			"current_task_progress": float(agent_state_data.get("current_task_progress", 0.0) or 0.0),
			"current_task_required_progress": float(agent_state_data.get("current_task_required_progress", 0.0) or 0.0),
			"active_interrupt_preset_id": str(agent_state_data.get("active_interrupt_preset_id", "") or ""),
			"available_interrupt_presets": list(agent_state_data.get("available_interrupt_presets", []) or []),
			"interrupt_preset_summaries": list(agent_state_data.get("interrupt_preset_summaries", []) or []),
			"inventory": self._get_inventory(ws, self_id),
			"hidden_entity_count": 0,
		}

	def _build_agent_state(self, ws: Any, self_id: str) -> AgentStateView:
		state = AgentStateView()
		agent = ws.get_entity_by_id(self_id)
		if agent is None:
			return state
		agent_comp = agent.get_component("AgentSetting")
		if isinstance(agent_comp, AgentSetting):
			state.agent_name = str(getattr(agent_comp, "agent_name", "") or "")
			state.personality_summary = str(getattr(agent_comp, "personality_summary", "") or "")
			state.common_knowledge_summary = str(getattr(agent_comp, "common_knowledge_summary", "") or "")
		arb = agent.get_component("DecisionArbiterComponent")
		if isinstance(arb, DecisionArbiterComponent):
			state.active_interrupt_preset_id = str(getattr(arb, "active_interrupt_preset_id", "") or "")
			presets = getattr(arb, "interrupt_presets", {}) or {}
			available_interrupt_presets = sorted([str(x) for x in presets.keys()])
			descs = getattr(arb, "interrupt_preset_descriptions", {}) or {}
			state.available_interrupt_presets = available_interrupt_presets
			state.interrupt_preset_summaries = [
				{"preset_id": pid, "description": str(descs.get(pid, "") or "")}
				for pid in available_interrupt_presets
			]
		mem = agent.get_component("MemoryComponent")
		if isinstance(mem, MemoryComponent):
			state.short_term_memory_text = mem.short_term_text(max_items=30)
			state.short_term_memory_items = [dict(x) for x in list(getattr(mem, "short_term_queue", []) or []) if isinstance(x, dict)]
			state.mid_term_summary = mem.to_summary_text()
		worker = agent.get_component("WorkerComponent")
		if worker is None:
			return state
		current_task_id = str(getattr(worker, "current_task_id", "") or "")
		state.current_task_id = current_task_id
		if not current_task_id:
			return state
		task = ws.get_task_by_id(current_task_id) if hasattr(ws, "get_task_by_id") else None
		if task is None:
			return state
		state.current_task_type = str(getattr(task, "task_type", "") or "")
		state.current_task_status = str(getattr(task, "task_status", "") or "")
		state.current_task_progress = float(getattr(task, "progress", 0.0) or 0.0)
		state.current_task_required_progress = float(getattr(task, "required_progress", 0.0) or 0.0)
		return state

	def _count_hidden_entities(self, containment_index: dict[str, dict[str, str]], visible_ids: list[str]) -> int:
		contained_ids = set(containment_index.keys())
		visible_id_set = set([str(x) for x in list(visible_ids or [])])
		return len([eid for eid in contained_ids if eid not in visible_id_set])

	def is_observation_blocked(self, ws: Any, entity_id: str) -> bool:
		return self._is_entity_in_transit(ws, entity_id)

	def _is_entity_in_transit(self, ws: Any, entity_id: str) -> bool:
		ent = ws.get_entity_by_id(str(entity_id)) if hasattr(ws, "get_entity_by_id") else None
		if ent is None:
			return False
		worker = ent.get_component("WorkerComponent")
		if not isinstance(worker, WorkerComponent):
			return False
		task_id = str(getattr(worker, "current_task_id", "") or "")
		if not task_id:
			return False
		task = ws.get_task_by_id(task_id) if hasattr(ws, "get_task_by_id") else None
		if task is None:
			return False
		if str(getattr(task, "task_type", "") or "") != "Travel":
			return False
		return str(getattr(task, "task_status", "") or "") == "InProgress"

	def _build_map_topology(self, ws: Any) -> list[dict[str, Any]]:
		topology: list[dict[str, Any]] = []
		locations = getattr(ws, "locations", {}) or {}
		for loc_id, loc in locations.items():
			neighbors: list[dict[str, Any]] = []
			seen: set[str] = set()
			for path in ws.get_paths_from(str(loc_id)):
				if bool(path.is_blocked):
					continue
				to_id = str(path.to_location_id)
				if to_id in seen:
					continue
				seen.add(to_id)
				to_loc = ws.get_location_by_id(to_id)
				neighbors.append(
					{
						"to_location_id": to_id,
						"to_location_name": str(to_loc.location_name) if to_loc is not None else to_id,
						"distance": float(path.distance),
					}
				)
			neighbors.sort(key=lambda x: str(x.get("to_location_id", "")))
			topology.append(
				{
					"location_id": str(loc_id),
					"location_name": str(getattr(loc, "location_name", "") or str(loc_id)),
					"neighbors": neighbors,
				}
			)
		topology.sort(key=lambda x: str(x.get("location_id", "")))
		return topology

	def _build_containment_index(self, ws: Any, location_id: str) -> dict[str, dict[str, str]]:
		index: dict[str, dict[str, str]] = {}
		for ent in list(getattr(ws, "entities", {}).values()):
			if ent is None:
				continue
			ent_loc = ws.get_location_of_entity(getattr(ent, "entity_id", ""))
			if ent_loc is None or str(getattr(ent_loc, "location_id", "")) != str(location_id):
				continue
			cc = ent.get_component("ContainerComponent")
			if not isinstance(cc, ContainerComponent):
				continue
			for slot_id, slot in cc.slots.items():
				for item_id in list(getattr(slot, "items", []) or []):
					iid = str(item_id)
					if not iid:
						continue
					index[iid] = {"container_id": str(getattr(ent, "entity_id", "") or ""), "slot_id": str(slot_id)}
		return index

	def _get_inventory(self, ws: Any, agent_id: str) -> list[dict[str, Any]]:
		"""
		Get list of items in agent's own container component.
		"""
		agent = ws.get_entity_by_id(agent_id)
		if agent is None:
			return []
		cc = agent.get_component("ContainerComponent")
		if not isinstance(cc, ContainerComponent):
			return []
		
		inventory: list[dict[str, Any]] = []
		for slot_name, slot in cc.slots.items():
			for item_id in slot.items:
				item = ws.get_entity_by_id(item_id)
				if item:
					conditions: list[str] = []
					cond_comp = item.get_component("ConditionComponent")
					if hasattr(cond_comp, "data") and isinstance(getattr(cond_comp, "data"), dict):
						raw = (getattr(cond_comp, "data") or {}).get("conditions", []) or []
						if isinstance(raw, list):
							conditions = [str(x) for x in raw]
					inventory.append({
						"id": item.entity_id,
						"name": item.entity_name,
						"tags": list(item.get_all_tags()),
						"slot": slot_name,
						"conditions": conditions,
					})
		return inventory

	def _expand_transparent_contents(self, ws: Any, seed_visible_ids: list[str]) -> list[str]:
		"""
		Recursively expand contents of all transparent slots starting from "Top-level visible entities".
		Rule: Only when a container entity itself is visible, can entities within its transparent slots be seen.
		"""
		visible: list[str] = []
		seen: set[str] = set()

		queue: list[str] = []
		for eid in seed_visible_ids:
			s = str(eid)
			if s and s not in seen:
				seen.add(s)
				queue.append(s)

		while queue:
			current_id = queue.pop(0)
			if self._is_entity_in_transit(ws, current_id):
				continue
			visible.append(current_id)

			ent = ws.get_entity_by_id(current_id)
			if ent is None:
				continue

			cc = ent.get_component("ContainerComponent")
			if not isinstance(cc, ContainerComponent):
				continue

			for slot in cc.slots.values():
				cfg = getattr(slot, "config", {}) or {}
				if not bool(cfg.get("transparent", False)):
					continue
				for item_id in list(getattr(slot, "items", []) or []):
					iid = str(item_id)
					if iid and iid not in seen and not self._is_entity_in_transit(ws, iid):
						seen.add(iid)
						queue.append(iid)

		return visible
