from __future__ import annotations

from typing import Any

from ..entity_ref_resolver import resolve_entity_id
from ..effect_contract import EFFECT_SPECS, EFFECT_TYPES


class BindError(RuntimeError):
	def __init__(self, effect_type: str, missing: list[str]):
		self.effect_type = str(effect_type or "")
		self.missing = [str(x) for x in list(missing or []) if str(x)]
		super().__init__(f"{self.effect_type}: missing required context {self.missing}")


def _as_dict(x: Any) -> dict[str, Any]:
	return dict(x) if isinstance(x, dict) else {}


def _resolve_ref_id(ref: Any, ctx: dict[str, Any]) -> str:
	return resolve_entity_id(ref, ctx, allow_literal=False)


def _resolve_param_token(value: Any, ctx: dict[str, Any]) -> Any:
	if isinstance(value, str):
		key = str(value).strip()
		if key.startswith("param:"):
			params = ctx.get("parameters", {}) or {}
			if isinstance(params, dict):
				return params.get(key[len("param:") :], "")
			return ""
		return value
	if isinstance(value, list):
		return [_resolve_param_token(v, ctx) for v in value]
	if isinstance(value, dict):
		return {str(k): _resolve_param_token(v, ctx) for k, v in value.items()}
	return value


def _require_param(params: dict[str, Any], effect_type: str, key: str) -> Any:
	if key not in params:
		raise BindError(effect_type, [key])
	return params.get(key)


def _require_str(params: dict[str, Any], effect_type: str, key: str) -> str:
	raw = _require_param(params, effect_type, key)
	value = str(raw or "").strip()
	if not value:
		raise BindError(effect_type, [key])
	return value


def _require_int(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> int:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	try:
		return int(raw)
	except Exception:
		raise BindError(effect_type, [key])


def _require_float(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> float:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	try:
		return float(raw)
	except Exception:
		raise BindError(effect_type, [key])


def _require_dict(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> dict[str, Any]:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	if not isinstance(raw, dict):
		raise BindError(effect_type, [key])
	return dict(raw)


def _base_bind(effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
	src = _as_dict(effect_data)
	ctx = _as_dict(context)
	effect_type = str(src.get("effect", "") or "")
	params = {k: v for k, v in src.items() if k != "effect"}
	return effect_type, params, ctx


def _bind_exchange_resources(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	source = _require_str(params, effect_type, "source")
	target = _require_str(params, effect_type, "target")
	transfer_mode = _require_str(params, effect_type, "transfer_mode").strip().lower()
	if transfer_mode not in {"destroy", "transfer"}:
		raise BindError(effect_type, ["transfer_mode"])
	consume_items = _require_param(params, effect_type, "consume_items")
	if not isinstance(consume_items, list):
		raise BindError(effect_type, ["consume_items"])
	consume_items = [str(_resolve_param_token(x, ctx)) for x in consume_items if _resolve_param_token(x, ctx)]
	consume_money = _require_float(params, effect_type, "consume_money", ctx)
	produce_items = _require_param(params, effect_type, "produce_items")
	if not isinstance(produce_items, list):
		raise BindError(effect_type, ["produce_items"])
	produce_items = [str(_resolve_param_token(x, ctx)) for x in produce_items if _resolve_param_token(x, ctx)]
	produce_money = _resolve_param_token(_require_param(params, effect_type, "produce_money"), ctx)
	if produce_money != "eval_price":
		try:
			produce_money = float(produce_money)
		except Exception:
			raise BindError(effect_type, ["produce_money"])
	return {
		"effect": effect_type,
		"source": source,
		"target": target,
		"transfer_mode": transfer_mode,
		"consume_items": consume_items,
		"consume_money": consume_money,
		"produce_items": produce_items,
		"produce_money": produce_money,
	}, ctx


def _bind_abort_simulation(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	reason = str(_resolve_param_token(_require_param(params, effect_type, "reason"), ctx) or "").strip()
	detail = str(_resolve_param_token(_require_param(params, effect_type, "detail"), ctx) or "").strip()
	severity = str(_resolve_param_token(_require_param(params, effect_type, "severity"), ctx) or "").strip().lower()
	if severity not in {"info", "warning", "error", "fatal"}:
		raise BindError(effect_type, ["severity"])
	stop_raw = _resolve_param_token(_require_param(params, effect_type, "stop"), ctx)
	stop = bool(stop_raw)
	if isinstance(stop_raw, str):
		stop = str(stop_raw).strip().lower() not in {"0", "false", "no", ""}
	return {
		"effect": effect_type,
		"reason": reason,
		"detail": detail,
		"severity": severity,
		"stop": stop,
	}, ctx


def _build_binders() -> dict[str, Any]:
	# Reminder: keep each effect's binder close to its execute logic in the same domain file.
	# This file should stay focused on shared helpers and binder registration only.
	from ._effect_agent import _bind_agent_control_tick, _bind_apply_meta_action, _bind_attach_details, _bind_worker_tick
	from ._effect_conversation import _bind_start_conversation
	from ._effect_entity import _bind_create_entity, _bind_destroy_entity, _bind_kill_entity, _bind_move_entity
	from ._effect_event import _bind_emit_event
	from ._effect_memory import _bind_add_memory_note
	from ._effect_property import _bind_add_tag, _bind_modify_property, _bind_remove_tag
	from ._effect_task import (
		_bind_accept_task,
		_bind_add_status,
		_bind_consume_inputs,
		_bind_create_task,
		_bind_finish_task,
		_bind_progress_task,
		_bind_remove_status,
		_bind_status_tick,
		_bind_update_task_status,
	)

	available = {
		"_bind_agent_control_tick": _bind_agent_control_tick,
		"_bind_worker_tick": _bind_worker_tick,
		"_bind_status_tick": _bind_status_tick,
		"_bind_modify_property": _bind_modify_property,
		"_bind_add_tag": _bind_add_tag,
		"_bind_remove_tag": _bind_remove_tag,
		"_bind_apply_meta_action": _bind_apply_meta_action,
		"_bind_attach_details": _bind_attach_details,
		"_bind_create_entity": _bind_create_entity,
		"_bind_destroy_entity": _bind_destroy_entity,
		"_bind_move_entity": _bind_move_entity,
		"_bind_add_status": _bind_add_status,
		"_bind_remove_status": _bind_remove_status,
		"_bind_consume_inputs": _bind_consume_inputs,
		"_bind_create_task": _bind_create_task,
		"_bind_accept_task": _bind_accept_task,
		"_bind_progress_task": _bind_progress_task,
		"_bind_update_task_status": _bind_update_task_status,
		"_bind_finish_task": _bind_finish_task,
		"_bind_kill_entity": _bind_kill_entity,
		"_bind_start_conversation": _bind_start_conversation,
		"_bind_add_memory_note": _bind_add_memory_note,
		"_bind_emit_event": _bind_emit_event,
		"_bind_exchange_resources": _bind_exchange_resources,
		"_bind_abort_simulation": _bind_abort_simulation,
	}
	out: dict[str, Any] = {}
	for effect_name, spec in EFFECT_SPECS.items():
		binder_name = str((spec or {}).get("binder", "") or "")
		binder = available.get(binder_name, None)
		if not callable(binder):
			raise RuntimeError(f"effect binder not found: {effect_name} -> {binder_name}")
		out[str(effect_name)] = binder
	return out


_BINDERS: dict[str, Any] = _build_binders()


def get_binder_effect_types() -> set[str]:
	return {str(k) for k in _BINDERS.keys()}


def bind_effect_input(ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	base_data = _as_dict(effect_data)
	if "context" in base_data:
		eff = str(base_data.get("effect", "") or "")
		raise BindError(eff, ["effect.context is removed; move fields to top-level effect keys"])
	effect_type = str(base_data.get("effect", "") or "")
	if not effect_type:
		return {}, _as_dict(context)
	binder = _BINDERS.get(effect_type)
	if binder is None:
		if effect_type in EFFECT_TYPES:
			raise BindError(effect_type, ["binder_missing"])
		_, _, ctx = _base_bind(base_data, context)
		return base_data, ctx
	return binder(ws, base_data, context)
