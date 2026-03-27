from __future__ import annotations

from typing import Any

from ..models.components import StatusComponent, TaskHostComponent, WorkerComponent
from ..models.task import Task
from ._effect_binder import BindError, _base_bind, _require_float, _require_str, _resolve_param_token


def _get_or_create_statuses_list(entity: Any) -> list[str] | None:
	comp = entity.get_component("StatusComponent")
	if not isinstance(comp, StatusComponent):
		return None
	return comp.statuses


def _clone_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
	cloned = dict(recipe)
	process = cloned.get("process", {}) or {}
	cloned["process"] = dict(process) if isinstance(process, dict) else {}
	outputs = cloned.get("outputs", []) or []
	cloned["outputs"] = [dict(x) for x in outputs if isinstance(x, dict)]
	return cloned


def _as_process_dict(recipe: dict[str, Any]) -> dict[str, Any]:
	process = recipe.get("process", {}) or {}
	return dict(process) if isinstance(process, dict) else {}


def _require_duration_spec(effect_type: str, recipe: dict[str, Any]) -> dict[str, Any]:
	process = _as_process_dict(recipe)
	duration = process.get("duration", {}) or {}
	if not isinstance(duration, dict) or not duration:
		raise BindError(effect_type, ["process.duration"])
	return dict(duration)


def _parse_param_token(effect_type: str, token: Any, field: str) -> str:
	text = str(token or "").strip()
	if not text.startswith("param:"):
		raise BindError(effect_type, [field])
	key = str(text[len("param:") :]).strip()
	if not key:
		raise BindError(effect_type, [field])
	return key


def _clone_recipe_with_required_progress(recipe: dict[str, Any], required_progress: float) -> dict[str, Any]:
	recipe_out = _clone_recipe(recipe)
	process = _as_process_dict(recipe_out)
	process["required_progress"] = float(required_progress)
	recipe_out["process"] = process
	return recipe_out


def _resolve_fixed_duration(effect_type: str, recipe: dict[str, Any]) -> float:
	duration = _require_duration_spec(effect_type, recipe)
	raw_value = duration.get("value", None)
	try:
		value = float(raw_value)
	except Exception:
		raise BindError(effect_type, ["process.duration.value"])
	if value <= 0:
		raise BindError(effect_type, ["process.duration.value"])
	return value


def _resolve_param_duration(effect_type: str, recipe: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, dict[str, Any]]:
	duration = _require_duration_spec(effect_type, recipe)
	key = _parse_param_token(effect_type, duration.get("from_param", ""), "process.duration.from_param")
	params = ctx.get("parameters", {}) or {}
	params_out = dict(params) if isinstance(params, dict) else {}
	raw_value = params_out.get(key, duration.get("default", None))
	if raw_value is None or str(raw_value).strip() == "":
		raise BindError(effect_type, [f"parameters.{key}"])
	try:
		value = float(raw_value)
	except Exception:
		raise BindError(effect_type, [f"parameters.{key}"])
	min_value = duration.get("min", None)
	if min_value is not None and value < float(min_value):
		raise BindError(effect_type, [f"parameters.{key}"])
	if float(value).is_integer():
		params_out[key] = int(value)
	else:
		params_out[key] = value
	return value, params_out


def _resolve_path_distance_duration(_ws: Any, effect_type: str, recipe: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, dict[str, Any], dict[str, Any]]:
	self_id = str(ctx.get("self_id", "") or "")
	params = ctx.get("parameters", {}) or {}
	params_out = dict(params) if isinstance(params, dict) else {}
	duration = _require_duration_spec(effect_type, recipe)
	to_param = _parse_param_token(effect_type, duration.get("to_param", "param:to_location_id"), "process.duration.to_param")
	to_location_id = str(params_out.get(to_param, "") or "").strip()
	if not to_location_id:
		raise BindError(effect_type, [f"parameters.{to_param}"])
	source_location = _ws.get_location_of_entity(self_id) if self_id and hasattr(_ws, "get_location_of_entity") else None
	if source_location is None:
		raise BindError(effect_type, ["source_location_id"])
	selected_path = None
	for path in list(_ws.get_paths_from(source_location.location_id) or []):
		if str(getattr(path, "to_location_id", "") or "") == to_location_id and not bool(getattr(path, "is_blocked", False)):
			selected_path = path
			break
	if selected_path is None:
		raise BindError(effect_type, [f"reachable_path:{source_location.location_id}->{to_location_id}"])
	required_progress = float(getattr(selected_path, "distance", 1.0) or 1.0)
	min_value = duration.get("min", None)
	if min_value is not None:
		required_progress = max(float(min_value), required_progress)
	params_out["source_location_id"] = str(getattr(source_location, "location_id", "") or "")
	params_out[to_param] = to_location_id
	to_name = ""
	to_loc = _ws.get_location_by_id(to_location_id) if hasattr(_ws, "get_location_by_id") else None
	if to_loc is not None:
		to_name = str(getattr(to_loc, "location_name", "") or "")
	extra = dict(ctx.get("interaction_extra", {}) or {})
	extra.update(
		{
			"travel_phase": "depart",
			"to_location_id": to_location_id,
			"to_location_name": to_name,
			"source_location_id": str(params_out.get("source_location_id", "") or ""),
		}
	)
	return required_progress, params_out, extra


def _materialize_task_recipe(_ws: Any, effect_type: str, recipe: dict[str, Any], ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	process = _as_process_dict(recipe)
	duration = process.get("duration", {}) or {}
	if not isinstance(duration, dict) or not duration:
		return _clone_recipe(recipe), dict(ctx)
	mode = str(duration.get("mode", "") or "").strip().lower()
	if mode == "fixed":
		required_progress = _resolve_fixed_duration(effect_type, recipe)
		return _clone_recipe_with_required_progress(recipe, required_progress), dict(ctx)
	if mode == "param":
		required_progress, params_out = _resolve_param_duration(effect_type, recipe, ctx)
		ctx_out = dict(ctx)
		ctx_out["parameters"] = params_out
		return _clone_recipe_with_required_progress(recipe, required_progress), ctx_out
	if mode == "path_distance":
		required_progress, params_out, extra = _resolve_path_distance_duration(_ws, effect_type, recipe, ctx)
		ctx_out = dict(ctx)
		ctx_out["parameters"] = params_out
		ctx_out["interaction_extra"] = extra
		return _clone_recipe_with_required_progress(recipe, required_progress), ctx_out
	raise BindError(effect_type, ["process.duration.mode"])


# Reminder: task binders and execute_* logic should evolve together in this file.
def _bind_add_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	status_id = _require_str(params, effect_type, "status_id")
	out: dict[str, Any] = {"effect": effect_type, "target": target, "status_id": status_id}
	if "duration_ticks" in params:
		raw_duration = _resolve_param_token(params.get("duration_ticks"), ctx)
		try:
			out["duration_ticks"] = int(raw_duration)
		except Exception:
			raise BindError(effect_type, ["duration_ticks"])
	return out, ctx


def _bind_remove_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	status_id = _require_str(params, effect_type, "status_id")
	return {"effect": effect_type, "target": target, "status_id": status_id}, ctx


def _bind_status_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	_ = params
	entity_id = str((ctx or {}).get("entity_id", "") or "")
	return {"effect": effect_type, "entity_id": entity_id}, ctx


def _bind_consume_inputs(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def _bind_create_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	if not str(ctx.get("target_id", "") or ""):
		raise BindError(effect_type, ["target_id"])
	recipe = params.get("recipe", {})
	if not isinstance(recipe, dict) or not recipe:
		raise BindError(effect_type, ["recipe"])
	assign_to = _require_str(params, effect_type, "assign_to")
	if assign_to not in {"self", "target"}:
		raise BindError(effect_type, ["assign_to"])
	recipe_out, ctx_out = _materialize_task_recipe(_ws, effect_type, dict(recipe), ctx)
	return {"effect": effect_type, "recipe": recipe_out, "assign_to": assign_to}, ctx_out


def _bind_accept_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	return {"effect": effect_type, "target": target}, ctx


def _bind_progress_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	task_id = _require_str(params, effect_type, "task_id")
	delta = _require_float(params, effect_type, "delta", ctx)
	return {"effect": effect_type, "task_id": task_id, "delta": delta}, ctx


def _bind_update_task_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	task_id = _require_str(params, effect_type, "task_id")
	status = _require_str(params, effect_type, "status")
	return {"effect": effect_type, "task_id": task_id, "status": status}, ctx


def _bind_finish_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def execute_add_status(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	status_id = data.get("status_id")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "AddStatus: target missing"}]
	status_list = _get_or_create_statuses_list(target)
	if status_list is None:
		return [{"type": "ExecutorError", "message": "AddStatus: StatusComponent missing"}]
	sid = str(status_id)
	if sid not in status_list:
		status_list.append(sid)
	comp = target.get_component("StatusComponent")
	expire_at_tick = None
	duration_raw = data.get("duration_ticks", None)
	if duration_raw is not None and isinstance(comp, StatusComponent):
		try:
			duration_ticks = int(duration_raw)
		except Exception:
			duration_ticks = 0
		if duration_ticks > 0:
			now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
			expire_at_tick = int(now_tick + duration_ticks)
			comp.expire_at_tick[sid] = expire_at_tick
		else:
			comp.expire_at_tick.pop(sid, None)
	return [{"type": "StatusAdded", "entity_id": target.entity_id, "status_id": sid, "expire_at_tick": expire_at_tick}]


def execute_remove_status(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	status_id = data.get("status_id")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "RemoveStatus: target missing"}]
	status_list = _get_or_create_statuses_list(target)
	if status_list is None:
		return [{"type": "ExecutorError", "message": "RemoveStatus: StatusComponent missing"}]
	sid = str(status_id)
	if sid in status_list:
		status_list.remove(sid)
	comp = target.get_component("StatusComponent")
	if isinstance(comp, StatusComponent):
		comp.expire_at_tick.pop(sid, None)
	return [{"type": "StatusRemoved", "entity_id": target.entity_id, "status_id": sid}]


def execute_status_tick(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	entity_id = str((data or {}).get("entity_id", "") or (context or {}).get("entity_id", "") or "")
	target = ws.get_entity_by_id(entity_id) if entity_id else None
	if target is None:
		return []
	comp = target.get_component("StatusComponent")
	if not isinstance(comp, StatusComponent):
		return []
	now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	expire_map = dict(getattr(comp, "expire_at_tick", {}) or {})
	if not expire_map:
		return []
	events: list[dict[str, Any]] = []
	for status_id, expire_tick in list(expire_map.items()):
		sid = str(status_id or "")
		if not sid:
			continue
		try:
			expire_i = int(expire_tick)
		except Exception:
			expire_i = -1
		if expire_i <= 0 or now_tick < expire_i:
			continue
		if sid in list(getattr(comp, "statuses", []) or []):
			comp.statuses.remove(sid)
		comp.expire_at_tick.pop(sid, None)
		events.append({"type": "StatusExpired", "entity_id": str(target.entity_id), "status_id": sid})
	return events


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


def execute_create_task(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target = executor._resolve_entity_from_ctx(ws, context, "target")
	if target is None:
		return [{"type": "ExecutorError", "message": "CreateTask: target missing"}]
	
	recipe = (data or {}).get("recipe", {}) or {}
	if not isinstance(recipe, dict) or not recipe:
		return [{"type": "ExecutorError", "message": "CreateTask: recipe missing in effect data"}]
	
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
			if "progress_contributors" in params:
				return [{"type": "ExecutorError", "message": "CreateTask: progressor_params.progress_contributors is removed; use add_terms/mul_terms"}]
			task.progressor_params = dict(params)
		task.tick_effects = [x for x in (prog.get("tick_effects", []) or []) if isinstance(x, dict)]
	
	host.add_task(task)
	ws.register_task(task)
	context["created_task_id"] = task.task_id
	events: list[dict[str, Any]] = [{"type": "TaskCreated", "task_id": task.task_id, "target_entity_id": target.entity_id}]
	
	# Determine Worker: Check context for "worker_id" or "assign_to"
	# If assign_to == "self", use self_id. If assign_to == "target", use target_id.
	# If None, leave unassigned.
	assign_to = str((data or {}).get("assign_to", "") or "")
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

	def _host_has_status(status_id: str) -> bool:
		comp = host_entity.get_component("StatusComponent")
		return bool(isinstance(comp, StatusComponent) and comp.has_status(str(status_id)))

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
		done_status = str(params.get("done_status_id", "") or "").strip()
		if done_status and _host_has_status(done_status):
			last_reason = f"task already done: {done_status}"
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
