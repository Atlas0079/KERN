from __future__ import annotations

from typing import Any

from ..execution_errors import executor_error
from ._effect_binder import BindError, _base_bind, _require_param, _resolve_param_token


def _bind_set_environment_field(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	key = str(_resolve_param_token(_require_param(params, effect_type, "key"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not key:
		raise BindError(effect_type, ["key"])
	value = _resolve_param_token(_require_param(params, effect_type, "value"), ctx)
	return {"effect": effect_type, "scope_id": scope_id, "key": key, "value": value}, ctx


def _bind_add_environment_condition(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	condition_id = str(_resolve_param_token(_require_param(params, effect_type, "condition_id"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not condition_id:
		raise BindError(effect_type, ["condition_id"])
	out: dict[str, Any] = {"effect": effect_type, "scope_id": scope_id, "condition_id": condition_id}
	if "duration_ticks" in params:
		try:
			out["duration_ticks"] = int(_resolve_param_token(params.get("duration_ticks"), ctx))
		except Exception:
			raise BindError(effect_type, ["duration_ticks"])
	return out, ctx


def _bind_remove_environment_condition(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(_require_param(params, effect_type, "scope_id"), ctx) or "").strip()
	condition_id = str(_resolve_param_token(_require_param(params, effect_type, "condition_id"), ctx) or "").strip()
	if not scope_id:
		raise BindError(effect_type, ["scope_id"])
	if not condition_id:
		raise BindError(effect_type, ["condition_id"])
	return {"effect": effect_type, "scope_id": scope_id, "condition_id": condition_id}, ctx


def _bind_environment_condition_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	scope_id = str(_resolve_param_token(params.get("scope_id", ""), ctx) or "").strip()
	return {"effect": effect_type, "scope_id": scope_id}, ctx


def _require_scope(ws: Any, scope_id: str, effect_name: str) -> tuple[Any, list[dict[str, Any]] | None]:
	if not hasattr(ws, "get_environment_scope_by_id"):
		return None, executor_error(f"{effect_name}: world has no environment scopes")
	scope = ws.get_environment_scope_by_id(scope_id)
	if scope is None:
		return None, executor_error(f"{effect_name}: unknown scope_id: {scope_id}")
	return scope, None


def execute_set_environment_field(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	key = str(data.get("key", "") or "").strip()
	if not scope_id:
		return executor_error("SetEnvironmentField: scope_id missing")
	if not key:
		return executor_error("SetEnvironmentField: key missing")
	scope, err = _require_scope(ws, scope_id, "SetEnvironmentField")
	if err is not None:
		return err
	fields = getattr(scope, "fields", None)
	if not isinstance(fields, dict):
		scope.fields = {}
	old_value = scope.fields.get(key)
	new_value = data.get("value")
	scope.fields[key] = new_value
	return [
		{
			"type": "EnvironmentFieldSet",
			"scope_id": scope_id,
			"key": key,
			"old_value": old_value,
			"value": new_value,
		}
	]


def execute_add_environment_condition(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	condition_id = str(data.get("condition_id", "") or "").strip()
	if not scope_id:
		return executor_error("AddEnvironmentCondition: scope_id missing")
	if not condition_id:
		return executor_error("AddEnvironmentCondition: condition_id missing")
	scope, err = _require_scope(ws, scope_id, "AddEnvironmentCondition")
	if err is not None:
		return err
	if not isinstance(getattr(scope, "conditions", None), list):
		scope.conditions = []
	if condition_id not in scope.conditions:
		scope.conditions.append(condition_id)
	expire_at_tick = None
	if "duration_ticks" in data:
		try:
			duration_ticks = int(data.get("duration_ticks", 0) or 0)
		except Exception:
			duration_ticks = 0
		if duration_ticks > 0:
			now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
			expire_at_tick = int(now_tick + duration_ticks)
			scope.condition_expire_at_tick[condition_id] = expire_at_tick
		else:
			scope.condition_expire_at_tick.pop(condition_id, None)
	return [{"type": "EnvironmentConditionAdded", "scope_id": scope_id, "condition_id": condition_id, "expire_at_tick": expire_at_tick}]


def execute_remove_environment_condition(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	scope_id = str(data.get("scope_id", "") or "").strip()
	condition_id = str(data.get("condition_id", "") or "").strip()
	if not scope_id:
		return executor_error("RemoveEnvironmentCondition: scope_id missing")
	if not condition_id:
		return executor_error("RemoveEnvironmentCondition: condition_id missing")
	scope, err = _require_scope(ws, scope_id, "RemoveEnvironmentCondition")
	if err is not None:
		return err
	if condition_id in list(getattr(scope, "conditions", []) or []):
		scope.conditions.remove(condition_id)
	scope.condition_expire_at_tick.pop(condition_id, None)
	return [{"type": "EnvironmentConditionRemoved", "scope_id": scope_id, "condition_id": condition_id}]


def execute_environment_condition_tick(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	wanted_scope_id = str(data.get("scope_id", "") or "").strip()
	scopes = []
	if wanted_scope_id:
		scope, err = _require_scope(ws, wanted_scope_id, "EnvironmentConditionTick")
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
		expire_map = dict(getattr(scope, "condition_expire_at_tick", {}) or {})
		for condition_id, expire_tick in list(expire_map.items()):
			cid = str(condition_id or "")
			if not cid:
				continue
			try:
				expire_i = int(expire_tick)
			except Exception:
				expire_i = -1
			if expire_i <= 0 or now_tick < expire_i:
				continue
			if cid in list(getattr(scope, "conditions", []) or []):
				scope.conditions.remove(cid)
			scope.condition_expire_at_tick.pop(cid, None)
			events.append({"type": "EnvironmentConditionExpired", "scope_id": scope_id, "condition_id": cid})
	return events
