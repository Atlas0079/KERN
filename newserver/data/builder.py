from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.components import (
	AgentSetting,
	AgentControlComponent,
	ContainerComponent,
	ContainerSlot,
	CreatureComponent,
	DecisionArbiterComponent,
	LogicControlComponent,
	MemoryComponent,
	PlayerControlComponent,
	TagComponent,
	TaskHostComponent,
	UnknownComponent,
	WorkerComponent,
)
from ..models.entity import Entity
from ..models.location import Location
from ..models.task import Task
from ..models.path import Path
from ..models.world_state import WorldState


@dataclass
class BuildResult:
	world_state: WorldState


def _task_from_dict(raw: dict[str, Any]) -> Task:
	task = Task(task_id=str(raw.get("task_id", "") or ""), task_type=str(raw.get("task_type", "") or ""))
	task.action_type = str(raw.get("action_type", task.action_type) or task.action_type)
	task.target_entity_id = str(raw.get("target_entity_id", "") or "")
	task.progress = float(raw.get("progress", 0.0) or 0.0)
	task.required_progress = float(raw.get("required_progress", task.required_progress) or task.required_progress)
	task.multiple_entity = bool(raw.get("multiple_entity", False))
	assigned = raw.get("assigned_agent_ids", []) or []
	if isinstance(assigned, list):
		task.assigned_agent_ids = [str(x) for x in assigned]
	task.task_status = str(raw.get("task_status", task.task_status) or task.task_status)
	params = raw.get("parameters", {}) or {}
	if isinstance(params, dict):
		task.parameters = dict(params)
	task.progressor_id = str(raw.get("progressor_id", "") or "")
	pp = raw.get("progressor_params", {}) or {}
	if isinstance(pp, dict):
		task.progressor_params = dict(pp)
	te = raw.get("tick_effects", []) or []
	if isinstance(te, list):
		task.tick_effects = [dict(x) for x in te if isinstance(x, dict)]
	ce = raw.get("completion_effects", []) or []
	if isinstance(ce, list):
		task.completion_effects = [dict(x) for x in ce if isinstance(x, dict)]
	return task


def _attach_tasks_from_snapshot(ws: WorldState, host_entity: Entity, snapshot: dict[str, Any]) -> None:
	overrides = snapshot.get("component_overrides", {}) or {}
	if not isinstance(overrides, dict):
		return
	host_patch = overrides.get("TaskHostComponent", {}) or {}
	if not isinstance(host_patch, dict):
		return
	tasks_raw = host_patch.get("tasks", {}) or {}
	if not isinstance(tasks_raw, dict) or not tasks_raw:
		return
	host = host_entity.get_component("TaskHostComponent")
	if not isinstance(host, TaskHostComponent):
		host = TaskHostComponent()
		host_entity.add_component("TaskHostComponent", host)
	for task_id, traw in tasks_raw.items():
		tid = str(task_id or "")
		if not tid:
			continue
		payload = dict(traw) if isinstance(traw, dict) else {}
		payload.setdefault("task_id", tid)
		task = _task_from_dict(payload)
		if not task.task_id:
			continue
		if ws.get_task_by_id(task.task_id) is None:
			ws.register_task(task)
		if host.get_task(task.task_id) is None:
			host.add_task(task)


def build_world_state(bundle_world: dict[str, Any], entity_templates: dict[str, Any], _recipe_db: dict[str, Any]) -> BuildResult:
	ws = WorldState()
	world_state_data = bundle_world.get("world_state", {})
	ws.game_time.total_ticks = int(world_state_data.get("current_tick", 0))

	# 1) Register locations first
	for loc_data in bundle_world.get("locations", []):
		loc_id = str(loc_data.get("location_id", "")).strip()
		if not loc_id:
			continue
		loc = Location(
			location_id=loc_id,
			location_name=str(loc_data.get("location_name", "Unnamed Location")),
			description=str(loc_data.get("description", "")),
		)
		ws.register_location(loc)

	# 1.5) Register paths
	paths_data = bundle_world.get("paths", []) or []
	for p_data in paths_data:
		from_id = str(p_data["from_location_id"]).strip()
		to_id = str(p_data["to_location_id"]).strip()
		pid = str(p_data["path_id"]).strip()
		
		path = Path(
			path_id=pid,
			from_location_id=from_id,
			to_location_id=to_id,
			distance=float(p_data.get("distance", 1.0)),
			travel_type=str(p_data.get("travel_type", "walk")),
			is_blocked=bool(p_data.get("is_blocked", False)),
		)
		
		ws.register_path(path)

	nested_snapshots_by_entity_id: dict[str, dict[str, Any]] = {}
	for loc_data in bundle_world.get("locations", []):
		loc_id = str(loc_data.get("location_id", "")).strip()
		loc = ws.get_location_by_id(loc_id)
		if loc is None:
			continue

		for snapshot in loc_data.get("entities", []):
			if not isinstance(snapshot, dict):
				continue
			parent_id = str(snapshot.get("parent_container", "") or "").strip()
			if parent_id:
				raise ValueError(f"location root entity must not define parent_container: {snapshot.get('instance_id', '')}")
			template_id = snapshot.get("template_id")
			instance_id = snapshot.get("instance_id")
			if not template_id or not instance_id:
				continue

			ent = create_entity_from_template(
				template_id=str(template_id),
				instance_id=str(instance_id),
				entity_templates=entity_templates,
			)
			ws.register_entity(ent)
			loc.add_entity_id(ent.entity_id)

			overrides = snapshot.get("component_overrides", {}) or {}
			apply_component_overrides(ent, overrides)
			_attach_tasks_from_snapshot(ws, ent, snapshot)

	for snapshot in list(bundle_world.get("entities", []) or []):
		if not isinstance(snapshot, dict):
			continue
		template_id = snapshot.get("template_id")
		instance_id = snapshot.get("instance_id")
		if not template_id or not instance_id:
			continue
		ent = create_entity_from_template(
			template_id=str(template_id),
			instance_id=str(instance_id),
			entity_templates=entity_templates,
		)
		ws.register_entity(ent)
		nested_snapshots_by_entity_id[str(ent.entity_id)] = snapshot
		overrides = snapshot.get("component_overrides", {}) or {}
		apply_component_overrides(ent, overrides)
		_attach_tasks_from_snapshot(ws, ent, snapshot)

	for entity_id, snapshot in nested_snapshots_by_entity_id.items():
		parent_id = str(snapshot.get("parent_container", "") or "").strip()
		if not parent_id:
			raise ValueError(f"nested entity '{entity_id}' missing parent_container")

		child = ws.get_entity_by_id(entity_id)
		if child is None:
			continue

		parent_entity = ws.get_entity_by_id(parent_id)
		if parent_entity is not None:
			cc = parent_entity.get_component("ContainerComponent")
			if not isinstance(cc, ContainerComponent):
				raise ValueError(f"parent_container '{parent_id}' has no ContainerComponent for child '{entity_id}'")
			if not cc.add_entity(child):
				raise ValueError(f"failed to add nested entity '{entity_id}' into parent_container '{parent_id}'")
			continue

		raise ValueError(f"parent_container '{parent_id}' not found for child '{entity_id}'")

	# 2.6) Restore initial tasks from archive
	for tdata in list(bundle_world.get("tasks", []) or []):
		if not isinstance(tdata, dict):
			continue

		task_id = str(tdata.get("task_id", "") or "").strip()
		if not task_id:
			raise ValueError("task missing task_id")
		task_type = str(tdata.get("task_type", "") or "").strip()
		if not task_type:
			raise ValueError(f"task[{task_id}] missing task_type")
		target_entity_id = str(tdata.get("target_entity_id", "") or "").strip()
		if not target_entity_id:
			raise ValueError(f"task[{task_id}] missing target_entity_id")
		current_agent_id = str(tdata.get("current_agent_id", "") or "").strip()
		if not current_agent_id:
			raise ValueError(f"task[{task_id}] missing current_agent_id")

		target = ws.get_entity_by_id(target_entity_id)
		if target is None:
			raise ValueError(f"task[{task_id}] target_entity_id not found: {target_entity_id}")

		host_entity = target
		agent = ws.get_entity_by_id(current_agent_id)
		if agent is not None:
			host_entity = agent
		else:
			raise ValueError(f"task[{task_id}] current_agent_id not found: {current_agent_id}")

		host = host_entity.get_component("TaskHostComponent")
		if not isinstance(host, TaskHostComponent):
			raise ValueError(f"task[{task_id}] host entity '{host_entity.entity_id}' missing TaskHostComponent")

		task_kwargs: dict[str, Any] = {}
		task_kwargs["task_id"] = task_id
		task_kwargs["task_type"] = task_type
		task_kwargs["action_type"] = str(tdata.get("action_type", "Task") or "Task")
		task_kwargs["target_entity_id"] = target_entity_id
		task_kwargs["progress"] = float(tdata.get("progress", 0.0))
		task_kwargs["required_progress"] = float(tdata.get("required_progress", 1.0))
		task_kwargs["multiple_entity"] = bool(tdata.get("multiple_entity", False))
		task_kwargs["task_status"] = str(tdata.get("task_status", "Inactive"))

		assigned = tdata.get("assigned_agent_ids", []) or []
		if isinstance(assigned, list):
			task_kwargs["assigned_agent_ids"] = [str(x) for x in assigned]

		params = tdata.get("parameters", {}) or {}
		if isinstance(params, dict):
			task_kwargs["parameters"] = dict(params)

		ce = tdata.get("completion_effects", []) or []
		if isinstance(ce, list):
			task_kwargs["completion_effects"] = [x for x in ce if isinstance(x, dict)]
		if not task_kwargs.get("completion_effects"):
			raise ValueError(f"task[{task_id}] missing completion_effects")

		task_kwargs["progressor_id"] = str(tdata.get("progressor_id", "") or "")
		if not task_kwargs["progressor_id"]:
			raise ValueError(f"task[{task_id}] missing progressor_id")
		pp = tdata.get("progressor_params", {}) or {}
		if isinstance(pp, dict):
			task_kwargs["progressor_params"] = dict(pp)
		else:
			raise ValueError(f"task[{task_id}] progressor_params must be object")
		te = tdata.get("tick_effects", []) or []
		if isinstance(te, list):
			task_kwargs["tick_effects"] = [x for x in te if isinstance(x, dict)]
		else:
			raise ValueError(f"task[{task_id}] tick_effects must be list")

		task = Task(**task_kwargs)
		host.add_task(task)
		ws.register_task(task)

		worker = agent.get_component("WorkerComponent")
		if isinstance(worker, WorkerComponent):
			worker.assign_task(task.task_id)
		else:
			raise ValueError(f"task[{task_id}] current_agent '{current_agent_id}' missing WorkerComponent")

	# 3) Minimal initialization (e.g. Creature current_*)
	for ent in ws.entities.values():
		ent.ensure_initialized()

	return BuildResult(world_state=ws)


def create_entity_from_template(template_id: str, instance_id: str, entity_templates: dict[str, Any]) -> Entity:
	template = entity_templates.get(template_id, {})
	if not isinstance(template, dict) or not template:
		raise ValueError(f"template not found: {template_id}")

	ent = Entity(
		entity_id=instance_id,
		template_id=template_id,
		entity_name=str(template.get("name", "Unnamed Entity")),
	)

	components_data = template.get("components", {}) or {}
	if not isinstance(components_data, dict):
		components_data = {}

	for comp_name, comp_data in components_data.items():
		ent.add_component(comp_name, _build_component(comp_name, comp_data))

	return ent


def _build_component(component_name: str, comp_data: Any):
	"""
	Convert migrated components to dataclass; others remain UnknownComponent(dict).
	"""

	if component_name == "TagComponent":
		tags = list((comp_data or {}).get("tags", []))
		return TagComponent(tags=[str(x) for x in tags])

	if component_name == "CreatureComponent":
		d = comp_data or {}
		return CreatureComponent(
			max_hp=float(d.get("max_hp", 100.0)),
			max_energy=float(d.get("max_energy", 100.0)),
			max_nutrition=float(d.get("max_nutrition", 100.0)),
		)

	if component_name == "AgentSetting":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return AgentSetting(
			agent_name=str(d.get("agent_name", "")),
			personality_summary=str(d.get("personality_summary", "")),
			common_knowledge_summary=str(d.get("common_knowledge_summary", "")),
		)

	if component_name == "AgentControlComponent":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return AgentControlComponent(
			enabled=bool(d.get("enabled", True)),
			provider_id=str(d.get("provider_id", "") or ""),
		)

	if component_name == "PlayerControlComponent":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return PlayerControlComponent(
			enabled=bool(d.get("enabled", True)),
			provider_id=str(d.get("provider_id", "player") or "player"),
		)

	if component_name == "LogicControlComponent":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return LogicControlComponent(
			enabled=bool(d.get("enabled", True)),
			provider_id=str(d.get("provider_id", "logic") or "logic"),
		)

	if component_name == "MemoryComponent":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return MemoryComponent(
			short_term_queue=[dict(x) for x in list(d.get("short_term_queue", []) or []) if isinstance(x, dict)],
			short_term_max_entries=int(d.get("short_term_max_entries", 25) or 25),
			mid_term_prep_queue=[dict(x) for x in list(d.get("mid_term_prep_queue", []) or []) if isinstance(x, dict)],
			mid_term_prep_max_entries=int(d.get("mid_term_prep_max_entries", 50) or 50),
			mid_term_queue=[dict(x) for x in list(d.get("mid_term_queue", []) or []) if isinstance(x, dict)],
			mid_term_max_entries=int(d.get("mid_term_max_entries", 20) or 20),
			last_mid_term_summary_tick=int(d.get("last_mid_term_summary_tick", -1) or -1),
			mid_term_summary_cooldown_ticks=int(d.get("mid_term_summary_cooldown_ticks", 15) or 15),
			last_event_seq_seen=int(d.get("last_event_seq_seen", 0) or 0),
			last_interaction_seq_seen=int(d.get("last_interaction_seq_seen", 0) or 0),
		)

	if component_name == "ContainerComponent":
		d = comp_data or {}
		slots_data = d.get("slots", {}) or {}
		slots: dict[str, ContainerSlot] = {}
		for slot_id, slot_tpl in slots_data.items():
			cfg = dict(slot_tpl or {})
			cfg.setdefault("capacity_volume", 999.0)
			cfg.setdefault("capacity_count", 999)
			cfg.setdefault("accepted_tags", [])
			cfg.setdefault("transparent", False)
			slots[str(slot_id)] = ContainerSlot(config=cfg, items=[])
		return ContainerComponent(slots=slots)

	if component_name == "DecisionArbiterComponent":
		d = comp_data or {}
		if isinstance(d, dict):
			return DecisionArbiterComponent.from_template_data(d)
		return DecisionArbiterComponent.from_template_data({})

	if component_name == "TaskHostComponent":
		return TaskHostComponent()

	if component_name == "WorkerComponent":
		d = comp_data or {}
		if not isinstance(d, dict):
			d = {}
		return WorkerComponent(
			current_task_id=str(d.get("current_task_id", "") or ""),
		)

	# Unmigrated components (Edible/Perception/...)
	raw = comp_data if isinstance(comp_data, dict) else {"value": comp_data}
	return UnknownComponent(data=raw)


def apply_component_overrides(entity: Entity, overrides: dict[str, Any]) -> None:
	"""
	MVP Override Strategy: If component is UnknownComponent, shallow merge dict directly;
	Migrated components (Tag/Creature/Agent/Container) do not do complex override first, avoid semantic inconsistency.

	Assume existence: Component level apply_snapshot()
	Intent: Consistent with Godot WorldBuilder convention, let component handle override itself;
	Necessity: Avoid builder coupling component internal fields, need to add this interface later.
	"""

	for comp_name, comp_patch in (overrides or {}).items():
		if not isinstance(comp_patch, dict):
			continue

		comp = entity.get_component(comp_name)
		if comp is None:
			continue

		# 1) UnknownComponent: Shallow merge data
		if isinstance(comp, UnknownComponent):
			comp.data.update(comp_patch)
			continue

		# 2) ContainerComponent: Support overriding slot config / items (For restoring container content from archive)
		if isinstance(comp, ContainerComponent):
			slots_patch = comp_patch.get("slots", None)
			if isinstance(slots_patch, dict):
				for slot_id, slot_p in slots_patch.items():
					if not isinstance(slot_p, dict):
						continue
					sid = str(slot_id)
					if sid not in comp.slots:
						comp.slots[sid] = ContainerSlot(config={}, items=[])
					if "config" in slot_p and isinstance(slot_p["config"], dict):
						comp.slots[sid].config.update(dict(slot_p["config"]))
					if "items" in slot_p and isinstance(slot_p["items"], list):
						comp.slots[sid].items = [str(x) for x in slot_p["items"]]
			continue

		# 3) WorkerComponent: Override current_task_id (For restoring action rights / what is being done)
		if isinstance(comp, WorkerComponent):
			if "current_task_id" in comp_patch:
				comp.current_task_id = str(comp_patch.get("current_task_id", "") or "")
			continue

		# 4) DecisionArbiterComponent: Rebuild ruleset/presets from structured data to avoid raw dict rules
		if isinstance(comp, DecisionArbiterComponent):
			base_data = {
				"active_interrupt_preset_id": str(getattr(comp, "active_interrupt_preset_id", "") or ""),
				"interrupt_presets": dict(getattr(comp, "interrupt_presets", {}) or {}),
				"interrupt_preset_descriptions": dict(getattr(comp, "interrupt_preset_descriptions", {}) or {}),
				"rules": [],
			}
			ruleset = list(getattr(comp, "ruleset", []) or [])
			for r in ruleset:
				if isinstance(r, dict) and "type" in r:
					base_data["rules"].append(dict(r))
				else:
					rule_type = str(getattr(r, "__class__", type("x", (), {})).__name__ or "")
					priority = int(getattr(r, "priority", 999) or 999)
					if rule_type == "LowNutritionRule":
						base_data["rules"].append({"type": "LowNutrition", "priority": priority, "threshold": float(getattr(r, "threshold", 50.0) or 50.0)})
					elif rule_type == "PerceptionChangeRule":
						base_data["rules"].append({"type": "PerceptionChange", "priority": priority, "trigger_on_agent_sighted": bool(getattr(r, "trigger_on_agent_sighted", True))})
					elif rule_type == "CorpseSightedRule":
						base_data["rules"].append({"type": "CorpseSighted", "priority": priority, "trigger_on_new_corpse": bool(getattr(r, "trigger_on_new_corpse", True))})
					elif rule_type == "IdleRule":
						base_data["rules"].append({"type": "Idle", "priority": priority})
			rules_patch = comp_patch.get("rules", comp_patch.get("ruleset", None))
			if isinstance(rules_patch, list):
				base_data["rules"] = [dict(x) for x in rules_patch if isinstance(x, dict)]
			if "active_interrupt_preset_id" in comp_patch:
				base_data["active_interrupt_preset_id"] = str(comp_patch.get("active_interrupt_preset_id", "") or "")
			if isinstance(comp_patch.get("interrupt_presets", None), dict):
				base_data["interrupt_presets"] = dict(comp_patch.get("interrupt_presets", {}) or {})
			if isinstance(comp_patch.get("interrupt_preset_descriptions", None), dict):
				base_data["interrupt_preset_descriptions"] = {
					str(k): str(v or "") for k, v in dict(comp_patch.get("interrupt_preset_descriptions", {}) or {}).items()
				}
			rebuilt = DecisionArbiterComponent.from_template_data(base_data)
			if isinstance(comp_patch.get("interrupt_runtime_state", None), dict):
				rebuilt.interrupt_runtime_state = dict(comp_patch.get("interrupt_runtime_state", {}) or {})
			if "_runtime_preset_id" in comp_patch:
				rebuilt._runtime_preset_id = str(comp_patch.get("_runtime_preset_id", "") or "")
			entity.components[comp_name] = rebuilt
			continue

		# 5) Other migrated components: Shallow assignment to same-name fields (No deep semantics)
		for k, v in comp_patch.items():
			if hasattr(comp, k):
				try:
					setattr(comp, k, v)
				except Exception as e:
					raise RuntimeError(
						f"component override failed: entity_id={str(getattr(entity, 'entity_id', '') or '')} "
						f"component={str(comp_name)} field={str(k)} value_type={str(type(v).__name__)}"
					) from e
