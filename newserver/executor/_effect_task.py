from __future__ import annotations

from typing import Any

from ..models.components import TaskHostComponent, WorkerComponent
from ..models.task import Task


def _get_or_create_conditions_list(entity: Any) -> list[str] | None:
	comp = entity.get_component("ConditionComponent")
	if comp is None:
		return None
	if hasattr(comp, "data") and isinstance(getattr(comp, "data"), dict):
		comp.data.setdefault("conditions", [])
		if isinstance(comp.data["conditions"], list):
			return comp.data["conditions"]
	return None


def execute_add_condition(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	condition_id = data.get("condition_id")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "AddCondition: target missing"}]
	cond_list = _get_or_create_conditions_list(target)
	if cond_list is None:
		return [{"type": "ExecutorError", "message": "AddCondition: ConditionComponent missing (not migrated yet)"}]
	cid = str(condition_id)
	if cid not in cond_list:
		cond_list.append(cid)
	return [{"type": "ConditionAdded", "entity_id": target.entity_id, "condition_id": cid}]


def execute_remove_condition(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	condition_id = data.get("condition_id")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "RemoveCondition: target missing"}]
	cond_list = _get_or_create_conditions_list(target)
	if cond_list is None:
		return [{"type": "ExecutorError", "message": "RemoveCondition: ConditionComponent missing (not migrated yet)"}]
	cid = str(condition_id)
	if cid in cond_list:
		cond_list.remove(cid)
	return [{"type": "ConditionRemoved", "entity_id": target.entity_id, "condition_id": cid}]


def execute_consume_inputs(executor: Any, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	ids = (context or {}).get("entities_for_consumption_ids", []) or []
	events: list[dict[str, Any]] = []
	for eid in list(ids):
		events.extend(
			executor.execute(
				ws,
				{"effect": "DestroyEntity", "target": "target"},
				{"target_id": str(eid)},
			)
		)
	return events


def execute_create_task(executor: Any, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target = executor._resolve_entity_from_ctx(ws, context, "target")
	if target is None:
		return [{"type": "ExecutorError", "message": "CreateTask: target missing"}]
	
	recipe = (context or {}).get("recipe", {}) or {}
	if not isinstance(recipe, dict) or not recipe:
		return [{"type": "ExecutorError", "message": "CreateTask: recipe missing in context"}]
	
	# Determine Host: Default to target (Workstation/Item), unless context specifies otherwise
	host_entity = target
	host = host_entity.get_component("TaskHostComponent")
	if not isinstance(host, TaskHostComponent):
		host = TaskHostComponent()
		host_entity.add_component("TaskHostComponent", host)
	
	verb = str(recipe.get("verb", ""))
	task = Task(task_type=verb, target_entity_id=target.entity_id)
	task.action_type = "Task"
	params_ctx = (context or {}).get("parameters", {}) or {}
	if isinstance(params_ctx, dict):
		task.parameters.update(dict(params_ctx))
	extra_ctx = (context or {}).get("interaction_extra", {}) or {}
	if isinstance(extra_ctx, dict):
		task.parameters.update(dict(extra_ctx))
	recipe_id = str(recipe.get("id", "") or "")
	if recipe_id:
		task.parameters["recipe_id"] = recipe_id
	process = recipe.get("process", {}) or {}
	task.required_progress = float(process.get("required_progress", 1))
	task.completion_effects = [x for x in (recipe.get("outputs", []) or []) if isinstance(x, dict)]
	if not task.completion_effects:
		return [{"type": "ExecutorError", "message": "CreateTask: recipe has no outputs (completion_effects)"}]
	prog = recipe.get("progression", None)
	if prog is None:
		prog = process.get("progression", {}) or {}
	if isinstance(prog, dict):
		task.progressor_id = str(prog.get("progressor", prog.get("progressor_id", "")) or "")
		params = prog.get("params", {}) or {}
		if isinstance(params, dict):
			task.progressor_params = dict(params)
		task.tick_effects = [x for x in (prog.get("tick_effects", []) or []) if isinstance(x, dict)]
	
	host.add_task(task)
	ws.register_task(task)
	context["created_task_id"] = task.task_id
	events: list[dict[str, Any]] = [{"type": "TaskCreated", "task_id": task.task_id, "target_entity_id": target.entity_id}]
	
	# Determine Worker: Check context for "worker_id" or "assign_to"
	# If assign_to == "self", use self_id. If assign_to == "target", use target_id.
	# If None, leave unassigned.
	assign_to = str((context or {}).get("assign_to", "") or "")
	worker_id = ""
	if assign_to == "self":
		worker_id = str((context or {}).get("self_id", "") or "")
	elif assign_to == "target":
		worker_id = str((context or {}).get("target_id", "") or "")
	
	if worker_id:
		worker_ent = ws.get_entity_by_id(worker_id)
		if worker_ent:
			worker = worker_ent.get_component("WorkerComponent")
			if isinstance(worker, WorkerComponent):
				worker.assign_task(task.task_id)
				task.task_status = "InProgress"
				if worker_id not in task.assigned_agent_ids:
					task.assigned_agent_ids.append(worker_id)
				events.append({"type": "TaskAssigned", "task_id": task.task_id, "worker_id": worker_id})

	return events


def execute_accept_task(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	self_id = str((context or {}).get("self_id", "") or "")
	agent = ws.get_entity_by_id(self_id)
	if agent is None:
		return [{"type": "ExecutorError", "message": "AcceptTask: self missing"}]
	
	target_key = data.get("target", "target")
	host_entity = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if host_entity is None:
		return [{"type": "ExecutorError", "message": "AcceptTask: host missing"}]
	
	host = host_entity.get_component("TaskHostComponent")
	if not isinstance(host, TaskHostComponent):
		return [{"type": "ExecutorError", "message": "AcceptTask: target is not a TaskHost"}]
	
	tasks = host.get_available_tasks()
	if not tasks:
		return [{"type": "ExecutorError", "message": "AcceptTask: no available tasks on host"}]

	worker = agent.get_component("WorkerComponent")
	if not isinstance(worker, WorkerComponent):
		return [{"type": "ExecutorError", "message": "AcceptTask: agent has no WorkerComponent"}]
	
	def _agent_has_item_with_tag(tag: str) -> bool:
		cc = agent.get_component("ContainerComponent")
		if cc is None:
			return False
		if not hasattr(cc, "slots") or not isinstance(getattr(cc, "slots"), dict):
			return False
		for slot in cc.slots.values():
			for item_id in list(getattr(slot, "items", []) or []):
				ent = ws.get_entity_by_id(str(item_id))
				if ent is None:
					continue
				if tag in (ent.get_all_tags() or []):
					return True
		return False

	def _host_has_condition(condition_id: str) -> bool:
		comp = host_entity.get_component("ConditionComponent")
		if comp is None:
			return False
		if hasattr(comp, "data") and isinstance(getattr(comp, "data"), dict):
			conds = comp.data.get("conditions", []) or []
			return str(condition_id) in [str(x) for x in conds]
		if hasattr(comp, "conditions") and isinstance(getattr(comp, "conditions"), list):
			return str(condition_id) in [str(x) for x in getattr(comp, "conditions")]
		return False

	selected = None
	last_reason = ""
	for t in tasks:
		params = getattr(t, "parameters", {}) or {}
		if not isinstance(params, dict):
			params = {}
		required_tag = str(params.get("required_item_tag", "") or "").strip()
		if required_tag and not _agent_has_item_with_tag(required_tag):
			last_reason = f"missing required tool tag: {required_tag}"
			continue
		done_cond = str(params.get("done_condition_id", "") or "").strip()
		if done_cond and _host_has_condition(done_cond):
			last_reason = f"task already done: {done_cond}"
			continue
		selected = t
		break
	if selected is None:
		return [{"type": "ExecutorError", "message": f"AcceptTask: no suitable task on host ({last_reason or 'no match'})"}]

	# Assign
	worker.assign_task(selected.task_id)
	selected.task_status = "InProgress"
	if self_id not in selected.assigned_agent_ids:
		selected.assigned_agent_ids.append(self_id)
	
	return [{"type": "TaskAccepted", "task_id": selected.task_id, "worker_id": self_id, "host_id": host_entity.entity_id}]


def execute_progress_task(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	task_id = str(data.get("task_id") or (context or {}).get("task_id", "") or "")
	delta = float(data.get("delta", 0.0))
	task = ws.get_task_by_id(task_id) if hasattr(ws, "get_task_by_id") else None
	if task is None:
		return [{"type": "ExecutorError", "message": f"ProgressTask: task not found {task_id}"}]
	task.progress += delta
	return [
		{
			"type": "TaskProgressed",
			"task_id": task.task_id,
			"delta": delta,
			"new_progress": task.progress,
			"required": task.required_progress,
		}
	]


def execute_update_task_status(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	task_id = str(data.get("task_id") or (context or {}).get("task_id", "") or "")
	new_status = str(data.get("status", "")).strip()
	task = ws.get_task_by_id(task_id) if hasattr(ws, "get_task_by_id") else None
	if task is None:
		return [{"type": "ExecutorError", "message": f"UpdateTaskStatus: task not found {task_id}"}]
	old_status = getattr(task, "task_status", "Unknown")
	task.task_status = new_status
	return [
		{
			"type": "TaskStatusChanged",
			"task_id": task.task_id,
			"old_status": old_status,
			"new_status": new_status,
		}
	]


def execute_finish_task(executor: Any, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	task_id = str((context or {}).get("task_id", ""))
	task = ws.get_task_by_id(task_id)
	if task is None:
		return [{"type": "ExecutorError", "message": "FinishTask: task not found"}]
	if isinstance(context, dict):
		context.setdefault("target_id", str(getattr(task, "target_entity_id", "") or ""))
		params = getattr(task, "parameters", {}) or {}
		if isinstance(params, dict) and params:
			base_params = context.get("parameters", {}) or {}
			if not isinstance(base_params, dict):
				base_params = {}
			merged_params = dict(base_params)
			for k, v in params.items():
				if str(k) not in merged_params:
					merged_params[str(k)] = v
			context["parameters"] = merged_params
	effects = list(task.completion_effects or [])
	if not effects:
		return [{"type": "ExecutorError", "message": f"FinishTask: task has no completion_effects: {task_id}"}]
	events: list[dict[str, Any]] = []
	for eff in effects:
		events.extend(executor.execute(ws, eff, context))
	has_finish_error = any(
		isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError"}
		for ev in list(events or [])
	)
	if has_finish_error:
		task.task_status = "Failed"
		events.append({"type": "TaskFinishFailed", "task_id": task.task_id})
		return events
	host_entity = None
	self_id = str((context or {}).get("self_id", "") or "")
	if self_id:
		host_entity = ws.get_entity_by_id(self_id)
	if host_entity is None:
		host_entity = ws.get_entity_by_id(task.target_entity_id)
	if host_entity is not None:
		host = host_entity.get_component("TaskHostComponent")
		if isinstance(host, TaskHostComponent):
			host.remove_task(task.task_id)
	if (
		str(getattr(task, "task_type", "") or "") == "Travel"
		and self_id
		and hasattr(ws, "record_interaction_attempt")
	):
		to_location_id = ""
		to_location_name = ""
		loc = ws.get_location_of_entity(self_id) if hasattr(ws, "get_location_of_entity") else None
		if loc is not None:
			to_location_id = str(getattr(loc, "location_id", "") or "")
			to_location_name = str(getattr(loc, "location_name", "") or "")
		task_params = getattr(task, "parameters", {}) or {}
		recipe_id = ""
		source_location_id = ""
		if isinstance(task_params, dict):
			recipe_id = str(task_params.get("recipe_id", "") or "")
			source_location_id = str(task_params.get("source_location_id", "") or "")
		ws.record_interaction_attempt(
			actor_id=self_id,
			verb="Travel",
			target_id=self_id,
			status="success",
			reason="",
			recipe_id=recipe_id,
			extra={
				"travel_phase": "arrive",
				"to_location_id": to_location_id,
				"to_location_name": to_location_name,
				"source_location_id": source_location_id,
			},
		)
	ws.unregister_task(task.task_id)
	events.append({"type": "TaskFinished", "task_id": task.task_id})
	return events
