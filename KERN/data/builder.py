from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..component_catalog import ComponentCatalog, build_core_component_catalog
from ..effect_bundle import effect_bundle_from_raw
from ..log_manager import get_logger
from ..models.components import (
	ContainerComponent,
	TaskHostComponent,
	WorkerComponent,
)
from ..models.entity import Entity
from ..models.environment import EnvironmentScope
from ..models.location import Location
from ..models.task import Task
from ..models.path import Path
from ..models.world_state import WorldState
from ..models.gametime import DEFAULT_TICK0_DATETIME


@dataclass
class BuildResult:
	world_state: WorldState




def _int_value(value: Any, field_name: str) -> int:
	try:
		return int(value)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{field_name} must be an integer: {value!r}") from exc


def _attach_tasks_from_snapshot(
	ws: WorldState,
	host_entity: Entity,
	snapshot: dict[str, Any],
	component_catalog: ComponentCatalog,
) -> None:
	overrides = snapshot.get("component_overrides", {})
	if not isinstance(overrides, dict):
		raise ValueError("entity component_overrides must be an object")
	host_patch = overrides.get("TaskHostComponent")
	if host_patch is None:
		return
	if not isinstance(host_patch, dict):
		raise ValueError("TaskHostComponent override must be an object")
	tasks_raw = host_patch.get("tasks", {})
	if not isinstance(tasks_raw, dict):
		raise ValueError("TaskHostComponent.tasks must be an object")
	if not tasks_raw:
		return
	host = host_entity.get_component("TaskHostComponent")
	if not isinstance(host, TaskHostComponent):
		host = component_catalog.build("TaskHostComponent", host_patch)
		host_entity.add_component("TaskHostComponent", host)
	for task in host.get_all_tasks():
		if ws.get_task_by_id(task.task_id) is None:
			ws.register_task(task)


def build_world_state(
	bundle_world: dict[str, Any],
	entity_templates: dict[str, Any],
	_recipe_db: dict[str, Any],
	check_container_snapshot_consistency: bool = False,
	named_bundles: dict[str, Any] | None = None,
	component_catalog: ComponentCatalog | None = None,
) -> BuildResult:
	catalog = component_catalog or build_core_component_catalog()
	ws = WorldState()
	ws.named_bundles = named_bundles or {}
	world_state_data = bundle_world.get("world_state", {})
	if not isinstance(world_state_data, dict):
		raise ValueError("world_state must be an object")
	ws.game_time.total_ticks = _int_value(world_state_data.get("current_tick", 0), "world_state.current_tick")
	ws.game_time.set_tick0_datetime(str(world_state_data.get("tick0_datetime", DEFAULT_TICK0_DATETIME)))

	for scope_data in list(bundle_world.get("environment_scopes", []) or []):
		if not isinstance(scope_data, dict):
			raise ValueError("environment_scopes entries must be objects")
		scope_id = str(scope_data.get("scope_id", "")).strip()
		if not scope_id:
			raise ValueError("environment scope missing scope_id")
		location_ids = [
			str(item).strip()
			for item in list(scope_data.get("location_ids", []) or [])
			if str(item).strip()
		]
		fields = scope_data.get("fields", {})
		if not isinstance(fields, dict):
			raise ValueError(f"environment scope {scope_id}.fields must be an object")
		conditions = [str(item) for item in list(scope_data.get("conditions", []) or []) if str(item)]
		expire_raw = scope_data.get("condition_expire_at_tick", {}) or {}
		expire_map: dict[str, int] = {}
		if not isinstance(expire_raw, dict):
			raise ValueError(f"environment scope {scope_id}.condition_expire_at_tick must be an object")
		for key, value in expire_raw.items():
			expire_map[str(key)] = _int_value(value, f"environment scope {scope_id}.condition_expire_at_tick.{key}")
		ws.register_environment_scope(
			EnvironmentScope(
				scope_id=scope_id,
				scope_type=str(scope_data.get("scope_type", "region") or "region"),
				location_ids=location_ids,
			priority=_int_value(scope_data.get("priority", 0), f"environment scope {scope_id}.priority"),
				fields=dict(fields),
				conditions=conditions,
				condition_expire_at_tick=expire_map,
			)
		)

	# 1) Register locations first
	for loc_data in bundle_world.get("locations", []):
		if not isinstance(loc_data, dict):
			raise ValueError("locations entries must be objects")
		loc_id = str(loc_data.get("location_id", "")).strip()
		if not loc_id:
			raise ValueError("location missing location_id")
		loc = Location(
			location_id=loc_id,
			location_name=str(loc_data.get("location_name", "Unnamed Location")),
			description=str(loc_data.get("description", "")),
			light_level=_int_value(loc_data.get("light_level", 2), f"location {loc_id}.light_level"),
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
			raise ValueError(f"location {loc_id} was not registered")

		for snapshot in loc_data.get("entities", []):
			if not isinstance(snapshot, dict):
				raise ValueError(f"location {loc_id}.entities entries must be objects")
			parent_id = str(snapshot.get("parent_container", "") or "").strip()
			if parent_id:
				raise ValueError(f"location root entity must not define parent_container: {snapshot.get('instance_id', '')}")
			template_id = snapshot.get("template_id")
			instance_id = snapshot.get("instance_id")
			if not template_id or not instance_id:
				raise ValueError(f"location {loc_id} entity missing template_id or instance_id")

			ent = create_entity_from_template(
				template_id=str(template_id),
				instance_id=str(instance_id),
				entity_templates=entity_templates,
				component_catalog=catalog,
			)
			ws.register_entity(ent)
			loc.add_entity_id(ent.entity_id)

			overrides = snapshot.get("component_overrides", {}) or {}
			apply_component_overrides(ent, overrides, restore_container_items=False, component_catalog=catalog)
			_attach_tasks_from_snapshot(ws, ent, snapshot, catalog)

	for snapshot in list(bundle_world.get("entities", []) or []):
		if not isinstance(snapshot, dict):
			raise ValueError("entities entries must be objects")
		template_id = snapshot.get("template_id")
		instance_id = snapshot.get("instance_id")
		if not template_id or not instance_id:
			raise ValueError("nested entity missing template_id or instance_id")
		ent = create_entity_from_template(
			template_id=str(template_id),
			instance_id=str(instance_id),
			entity_templates=entity_templates,
			component_catalog=catalog,
		)
		ws.register_entity(ent)
		nested_snapshots_by_entity_id[str(ent.entity_id)] = snapshot
		overrides = snapshot.get("component_overrides", {}) or {}
		apply_component_overrides(ent, overrides, restore_container_items=False, component_catalog=catalog)
		_attach_tasks_from_snapshot(ws, ent, snapshot, catalog)

	for entity_id, snapshot in nested_snapshots_by_entity_id.items():
		parent_id = str(snapshot.get("parent_container", "") or "").strip()
		if not parent_id:
			raise ValueError(f"nested entity '{entity_id}' missing parent_container")

		child = ws.get_entity_by_id(entity_id)
		if child is None:
			raise ValueError(f"nested entity '{entity_id}' was not registered")

		parent_entity = ws.get_entity_by_id(parent_id)
		if parent_entity is not None:
			cc = parent_entity.get_component("ContainerComponent")
			if not isinstance(cc, ContainerComponent):
				raise ValueError(f"parent_container '{parent_id}' has no ContainerComponent for child '{entity_id}'")
			parent_snapshot = nested_snapshots_by_entity_id.get(parent_id)
			if parent_snapshot is None:
				for loc_data in bundle_world.get("locations", []):
					if not isinstance(loc_data, dict):
						continue
					for root_snapshot in loc_data.get("entities", []):
						if not isinstance(root_snapshot, dict):
							continue
						if str(root_snapshot.get("instance_id", "") or "").strip() == parent_id:
							parent_snapshot = root_snapshot
							break
					if parent_snapshot is not None:
						break
			recorded_in_parent = False
			if isinstance(parent_snapshot, dict):
				parent_overrides = parent_snapshot.get("component_overrides", {}) or {}
				if isinstance(parent_overrides, dict):
					container_patch = parent_overrides.get("ContainerComponent", {}) or {}
					if isinstance(container_patch, dict):
						slots_patch = container_patch.get("slots", {}) or {}
						if isinstance(slots_patch, dict):
							for slot_patch in slots_patch.values():
								if not isinstance(slot_patch, dict):
									continue
								items = slot_patch.get("items", []) or []
								if isinstance(items, list) and entity_id in [str(x) for x in items]:
									recorded_in_parent = True
									break
			if check_container_snapshot_consistency and not recorded_in_parent:
				get_logger().warn(
					"checkpoint",
					"parent_container_missing_child_record",
					context={"parent_id": parent_id, "child_id": entity_id},
				)
			if not cc.add_entity(child):
				raise ValueError(f"failed to add nested entity '{entity_id}' into parent_container '{parent_id}'")
			continue

		raise ValueError(f"parent_container '{parent_id}' not found for child '{entity_id}'")

	# 2.6) Restore initial tasks from archive
	for tdata in list(bundle_world.get("tasks", []) or []):
		if not isinstance(tdata, dict):
			raise ValueError("tasks entries must be objects")

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

		task_kwargs["start_bundle"] = effect_bundle_from_raw(tdata.get("start_bundle", {}) or {"effects": []})
		task_kwargs["completion_bundle"] = effect_bundle_from_raw(tdata.get("completion_bundle", {}) or {})
		if task_kwargs["completion_bundle"].is_empty():
			raise ValueError(f"task[{task_id}] missing completion_bundle")

		task_kwargs["progressor_id"] = str(tdata.get("progressor_id", "") or "")
		if not task_kwargs["progressor_id"]:
			raise ValueError(f"task[{task_id}] missing progressor_id")
		pp = tdata.get("progressor_params", {}) or {}
		if isinstance(pp, dict):
			if "progress_contributors" in pp:
				raise ValueError(f"task[{task_id}] progressor_params.progress_contributors is removed; use add_terms/mul_terms")
			task_kwargs["progressor_params"] = dict(pp)
		else:
			raise ValueError(f"task[{task_id}] progressor_params must be object")
		task_kwargs["tick_bundle"] = effect_bundle_from_raw(tdata.get("tick_bundle", {}) or {"effects": []})
		task_kwargs["cleanup_bundle"] = effect_bundle_from_raw(tdata.get("cleanup_bundle", {}) or {"effects": []})

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


def create_entity_from_template(
	template_id: str,
	instance_id: str,
	entity_templates: dict[str, Any],
	component_catalog: ComponentCatalog | None = None,
) -> Entity:
	catalog = component_catalog or build_core_component_catalog()
	template = entity_templates.get(template_id, {})
	if not isinstance(template, dict) or not template:
		raise ValueError(f"template not found: {template_id}")

	ent = Entity(
		entity_id=instance_id,
		template_id=template_id,
		entity_name=str(template["name"]),
	)

	components_data = template.get("components", {})
	if not isinstance(components_data, dict):
		raise ValueError(f"template components must be an object: {template_id}")

	for comp_name, comp_data in components_data.items():
		ent.add_component(comp_name, catalog.build(comp_name, comp_data))

	return ent


def _build_component(
	component_name: str,
	comp_data: Any,
	component_catalog: ComponentCatalog | None = None,
):
	catalog = component_catalog or build_core_component_catalog()
	return catalog.build(component_name, comp_data)


def apply_component_overrides(
	entity: Entity,
	overrides: dict[str, Any],
	restore_container_items: bool = True,
	component_catalog: ComponentCatalog | None = None,
) -> None:
	catalog = component_catalog or build_core_component_catalog()
	for component_name, patch in dict(overrides or {}).items():
		if not isinstance(patch, dict):
			raise ValueError(f"component override must be an object: {component_name}")
		component = entity.get_component(component_name)
		if component is None:
			raise ValueError(f"component override targets missing component: {component_name}")
		try:
			updated = catalog.apply_snapshot(
				component_name,
				component,
				patch,
				restore_container_items=restore_container_items,
			)
		except Exception as exc:
			raise RuntimeError(
				f"component override failed: entity_id={str(getattr(entity, 'entity_id', '') or '')} "
				f"component={str(component_name)}"
			) from exc
		if updated is not component:
			entity.components[component_name] = updated
