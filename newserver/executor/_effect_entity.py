from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..models.components import ContainerComponent, WorkerComponent


def execute_create_entity(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	template_id = data.get("template")
	destination_data = data.get("destination")
	if not template_id or not isinstance(destination_data, dict):
		return [{"type": "ExecutorError", "message": "CreateEntity: missing template or destination"}]
	if not isinstance(executor.entity_templates, dict):
		return [{"type": "ExecutorError", "message": "CreateEntity: executor has no entity_templates"}]
	template = executor.entity_templates.get(str(template_id), {})
	if not isinstance(template, dict) or not template:
		return [{"type": "ExecutorError", "message": f"CreateEntity: template not found: {template_id}"}]
	from ..data.builder import create_entity_from_template
	new_id = str(data.get("instance_id") or f"{template_id}_{uuid4().hex[:8]}")
	new_entity = create_entity_from_template(str(template_id), new_id, executor.entity_templates)
	overrides = data.get("spawn_patch")
	if not isinstance(overrides, dict):
		overrides = data.get("overrides")
	if isinstance(overrides, dict):
		fmt_ctx = {"template_id": template_id}
		self_ent = executor._resolve_entity_from_ctx(ws, context, "self")
		target = executor._resolve_entity_from_ctx(ws, context, "target")
		if self_ent:
			fmt_ctx["self"] = self_ent
		if target:
			fmt_ctx["target"] = target
		def _fmt(val):
			if isinstance(val, str) and "{" in val and "}" in val:
				try:
					return val.format(**fmt_ctx)
				except Exception:
					return val
			return val
		if "name" in overrides:
			new_entity.entity_name = _fmt(overrides["name"])
		comp_ov = overrides.get("components", {})
		if isinstance(comp_ov, dict):
			for cname, cdata in comp_ov.items():
				comp = new_entity.get_component(cname)
				if comp and hasattr(comp, "data") and isinstance(comp.data, dict):
					for k, v in cdata.items():
						comp.data[k] = _fmt(v)
				elif comp:
					for k, v in cdata.items():
						if hasattr(comp, k):
							setattr(comp, k, _fmt(v))
	ws.register_entity(new_entity)
	dest_type = str(destination_data.get("type", ""))
	dest_target_key = destination_data.get("target")
	placed = False
	if dest_type == "container":
		parent = executor._resolve_entity_from_ctx(ws, context, str(dest_target_key))
		if parent is None and dest_target_key:
			parent = ws.get_entity_by_id(str(dest_target_key))
		if parent is not None:
			cc = parent.get_component("ContainerComponent")
			if isinstance(cc, ContainerComponent):
				if cc.add_entity(new_entity):
					placed = True
	elif dest_type == "location":
		loc = None
		if dest_target_key:
			loc = ws.get_location_by_id(str(dest_target_key))
		if loc is None:
			agent = executor._resolve_entity_from_ctx(ws, context, "self")
			if agent is not None:
				loc = ws.get_location_of_entity(agent.entity_id)
		if loc is not None:
			ws.ensure_entity_in_location(new_entity.entity_id, loc.location_id)
			placed = True
	if not placed:
		agent = executor._resolve_entity_from_ctx(ws, context, "self")
		loc = ws.get_location_of_entity(agent.entity_id) if agent is not None else None
		if loc is not None:
			ws.ensure_entity_in_location(new_entity.entity_id, loc.location_id)
			placed = True
	return [
		{
			"type": "EntityCreated",
			"entity_id": new_entity.entity_id,
			"template_id": new_entity.template_id,
			"placed": placed,
		}
	]


def execute_destroy_entity(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "entity_to_destroy"))
	ent = executor._resolve_entity_from_ctx(ws, context, target_key)
	if ent is None:
		return [{"type": "ExecutorError", "message": "DestroyEntity: target missing"}]
	events: list[dict[str, Any]] = []
	cc_self = ent.get_component("ContainerComponent")
	if isinstance(cc_self, ContainerComponent):
		for child_id in list(cc_self.get_all_item_ids()):
			events.extend(
				executor.execute(
					ws,
					{"effect": "DestroyEntity", "target": "target"},
					{"target_id": str(child_id)},
				)
			)
	wc = ent.get_component("WorkerComponent")
	if isinstance(wc, WorkerComponent):
		tid = getattr(wc, "current_task_id", "")
		if tid:
			task = ws.tasks.get(tid)
			if task:
				if str(getattr(task, "target_entity_id", "") or "") != str(ent.entity_id):
					if hasattr(task, "assigned_agent_ids") and isinstance(getattr(task, "assigned_agent_ids"), list):
						task.assigned_agent_ids = []
					task.task_status = "Inactive"
					events.append({"type": "TaskReleased", "task_id": tid, "reason": "agent_destroyed"})
				else:
					task.task_status = "Cancelled"
					events.append({"type": "TaskCancelled", "task_id": tid, "reason": "agent_destroyed"})
			wc.current_task_id = ""
	for loc in ws.locations.values():
		if ent.entity_id in loc.entities_in_location:
			loc.remove_entity_id(ent.entity_id)
	for holder in ws.entities.values():
		cc = holder.get_component("ContainerComponent")
		if isinstance(cc, ContainerComponent):
			for slot in cc.slots.values():
				if ent.entity_id in slot.items:
					slot.items.remove(ent.entity_id)
	ws.entities.pop(ent.entity_id, None)
	events.append({"type": "EntityDestroyed", "entity_id": ent.entity_id})
	return events


def _execute_move_entity_core(executor: Any, ws: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
	ctx = dict(context or {})
	entity_to_move = executor._resolve_entity_from_ctx(ws, ctx, "entity_id")
	source_node = executor._resolve_container_or_location_from_ctx(ws, ctx, "source_id")
	dest_node = executor._resolve_container_or_location_from_ctx(ws, ctx, "destination_id")
	if entity_to_move is None or source_node is None or dest_node is None:
		return [{"type": "ExecutorError", "message": "MoveEntity: missing entity/source/destination"}]
	source_loc = source_node if hasattr(source_node, "location_id") else ws.get_location_of_entity(getattr(source_node, "entity_id", ""))
	dest_loc = dest_node if hasattr(dest_node, "location_id") else ws.get_location_of_entity(getattr(dest_node, "entity_id", ""))
	cross_location = False
	if source_loc is not None and dest_loc is not None:
		cross_location = str(source_loc.location_id) != str(dest_loc.location_id)
	if hasattr(source_node, "location_id"):
		if cross_location:
			source_node.remove_entity_id(entity_to_move.entity_id)
	else:
		cc = source_node.get_component("ContainerComponent")
		if isinstance(cc, ContainerComponent):
			if not cc.remove_entity_by_id(entity_to_move.entity_id):
				return [{"type": "ExecutorError", "message": "MoveEntity: failed to remove from source container"}]
	add_ok = False
	if hasattr(dest_node, "location_id"):
		add_ok = bool(dest_node.add_entity_id(entity_to_move.entity_id))
	else:
		cc = dest_node.get_component("ContainerComponent")
		if isinstance(cc, ContainerComponent):
			add_ok = bool(cc.add_entity(entity_to_move))
	if not add_ok:
		return [{"type": "ExecutorError", "message": "MoveEntity: failed to add to destination"}]

	return [
		{
			"type": "EntityMoved",
			"entity_id": entity_to_move.entity_id,
			"source_id": getattr(source_node, "location_id", getattr(source_node, "entity_id", "")),
			"destination_id": getattr(dest_node, "location_id", getattr(dest_node, "entity_id", ""))
		}
	]


def execute_move_entity(executor: Any, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return _execute_move_entity_core(executor, ws, context)


def execute_kill_entity(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target = executor._resolve_entity_from_ctx(ws, context, str(data.get("target", "target")))
	if target is None:
		return [{"type": "ExecutorError", "message": "KillEntity: target missing"}]
	owner_name = str(getattr(target, "entity_name", "") or "")
	agent_setting = target.get_component("AgentSetting")
	if agent_setting is not None:
		agent_name = str(getattr(agent_setting, "agent_name", "") or "")
		if agent_name:
			owner_name = agent_name
	if not owner_name:
		owner_name = str(getattr(target, "entity_id", "") or "Unknown")
	corpse_template = str(data.get("corpse_template", "Corpse"))
	events: list[dict[str, Any]] = []
	loc = ws.get_location_of_entity(target.entity_id)
	create_req = {
		"effect": "CreateEntity",
		"template": corpse_template,
		"destination": {"type": "location", "target": str(loc.location_id) if loc else ""},
		"spawn_patch": {
			"name": f"{owner_name}的尸体",
		}
	}
	create_res = executor.execute(ws, create_req, context)
	events.extend(create_res)
	corpse_id = ""
	for ev in create_res:
		if ev.get("type") == "EntityCreated":
			corpse_id = str(ev.get("entity_id", ""))
			break
	if corpse_id:
		cc = target.get_component("ContainerComponent")
		if isinstance(cc, ContainerComponent):
			items_to_move = list(cc.get_all_item_ids())
			for item_id in items_to_move:
				trans_req = {
					"effect": "MoveEntity",
					"entity_ref": "param:entity_id",
					"from_ref": "param:source_id",
					"to_ref": "param:destination_id",
				}
				sub_ctx = {"parameters": {"entity_id": str(item_id), "source_id": str(target.entity_id), "destination_id": str(corpse_id)}}
				events.extend(executor.execute(ws, trans_req, sub_ctx))
	destroy_req = {"effect": "DestroyEntity", "target": "target"}
	destroy_ctx = {"target_id": str(target.entity_id)}
	destroy_events = executor.execute(ws, destroy_req, destroy_ctx)
	events.extend(destroy_events)
	destroy_failed = any(
		isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError"}
		for ev in list(destroy_events or [])
	)
	if not destroy_failed and ws.get_entity_by_id(str(target.entity_id)) is None:
		events.append({
			"type": "EntityDied",
			"entity_id": target.entity_id,
			"corpse_id": corpse_id,
			"reason": str(data.get("reason", "killed"))
		})
	return events
