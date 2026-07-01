from __future__ import annotations

from typing import Any

from ._effect_binder import BindError, _base_bind, _require_param, _resolve_param_token


def _bind_set_environment_variable(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	key = str(_resolve_param_token(_require_param(params, effect_type, "key"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not key:
		raise BindError(effect_type, ["key"])
	value = _resolve_param_token(_require_param(params, effect_type, "value"), ctx)
	return {"effect": effect_type, "scope_id": scope_id, "key": key, "value": value}, ctx


def _bind_add_environment_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	status_id = str(_resolve_param_token(_require_param(params, effect_type, "status_id"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not status_id:
		raise BindError(effect_type, ["status_id"])
	out: dict[str, Any] = {"effect": effect_type, "scope_id": scope_id, "status_id": status_id}
	if "duration_ticks" in params:
		try:
			out["duration_ticks"] = int(_resolve_param_token(params.get("duration_ticks"), ctx))
		except Exception:
			raise BindError(effect_type, ["duration_ticks"])
	return out, ctx


def _bind_remove_environment_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	status_id = str(_resolve_param_token(_require_param(params, effect_type, "status_id"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not status_id:
		raise BindError(effect_type, ["status_id"])
	return {"effect": effect_type, "scope_id": scope_id, "status_id": status_id}, ctx


def _bind_environment_status_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(params.get("scope_id", ""), ctx) or "").strip()
	return {"effect": effect_type, "scope_id": scope_id}, ctx


def _require_scope(ws: Any, scope_id: str, effect_name: str) -> tuple[Any, list[dict[str, Any]] | None]:
	if not hasattr(ws, "get_environment_scope_by_id"):
		return None, [{"type": "ExecutorError", "message": f"{effect_name}: world has no environment scopes"}]
	scope = ws.get_environment_scope_by_id(scope_id)
	if scope is None:
		return None, [{"type": "ExecutorError", "message": f"{effect_name}: unknown scope_id: {scope_id}"}]
	return scope, None


def execute_set_environment_variable(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	key = str(data.get("key", "") or "").strip()
	if not scope_id:
		return [{"type": "ExecutorError", "message": "SetEnvironmentVariable: scope_id missing"}]
	if not key:
		return [{"type": "ExecutorError", "message": "SetEnvironmentVariable: key missing"}]
	scope, err = _require_scope(ws, scope_id, "SetEnvironmentVariable")
	if err is not None:
		return err
	variables = getattr(scope, "variables", None)
	if not isinstance(variables, dict):
		scope.variables = {}
	old_value = scope.variables.get(key)
	new_value = data.get("value")
	scope.variables[key] = new_value
	return [
		{
			"type": "EnvironmentVariableSet",
			"scope_id": scope_id,
			"key": key,
			"old_value": old_value,
			"value": new_value,
		}
	]


def execute_add_environment_status(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	status_id = str(data.get("status_id", "") or "").strip()
	if not scope_id:
		return [{"type": "ExecutorError", "message": "AddEnvironmentStatus: scope_id missing"}]
	if not status_id:
		return [{"type": "ExecutorError", "message": "AddEnvironmentStatus: status_id missing"}]
	scope, err = _require_scope(ws, scope_id, "AddEnvironmentStatus")
	if err is not None:
		return err
	if not isinstance(getattr(scope, "statuses", None), list):
		scope.statuses = []
	if status_id not in scope.statuses:
		scope.statuses.append(status_id)
	expire_at_tick = None
	if "duration_ticks" in data:
		try:
			duration_ticks = int(data.get("duration_ticks", 0) or 0)
		except Exception:
			duration_ticks = 0
		if duration_ticks > 0:
			now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
			expire_at_tick = int(now_tick + duration_ticks)
			scope.expire_at_tick[status_id] = expire_at_tick
		else:
			scope.expire_at_tick.pop(status_id, None)
	return [{"type": "EnvironmentStatusAdded", "scope_id": scope_id, "status_id": status_id, "expire_at_tick": expire_at_tick}]


def execute_remove_environment_status(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	status_id = str(data.get("status_id", "") or "").strip()
	if not scope_id:
		return [{"type": "ExecutorError", "message": "RemoveEnvironmentStatus: scope_id missing"}]
	if not status_id:
		return [{"type": "ExecutorError", "message": "RemoveEnvironmentStatus: status_id missing"}]
	scope, err = _require_scope(ws, scope_id, "RemoveEnvironmentStatus")
	if err is not None:
		return err
	if status_id in list(getattr(scope, "statuses", []) or []):
		scope.statuses.remove(status_id)
	scope.expire_at_tick.pop(status_id, None)
	return [{"type": "EnvironmentStatusRemoved", "scope_id": scope_id, "status_id": status_id}]


def execute_environment_status_tick(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	wanted_scope_id = str(data.get("scope_id", "") or "").strip()
	scopes = []
	if wanted_scope_id:
		scope, err = _require_scope(ws, wanted_scope_id, "EnvironmentStatusTick")
		if err is not None:
			return err
		scopes = [scope]
	else:
		scopes = list(getattr(ws, "environment_scopes", {}).values())
	events: list[dict[str, Any]] = []
	for scope in scopes:
		if scope is None:
			continue
		scope_id = str(getattr(scope, "scope_id", "") or "")
		expire_map = dict(getattr(scope, "expire_at_tick", {}) or {})
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
			if sid in list(getattr(scope, "statuses", []) or []):
				scope.statuses.remove(sid)
			scope.expire_at_tick.pop(sid, None)
			events.append({"type": "EnvironmentStatusExpired", "scope_id": scope_id, "status_id": sid})
	return events
