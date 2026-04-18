from __future__ import annotations

from typing import Any

from ..models.components import ValuableComponent
from ._effect_binder import (
	BindError,
	_base_bind,
	_require_float,
	_require_param,
	_require_str,
	_resolve_param_token,
)
from ._effect_entity import _execute_move_entity_core, execute_destroy_entity


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


def execute_exchange_resources(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	source_key = str(data.get("source", "self"))
	target_key = str(data.get("target", "target"))
	transfer_mode = str(data.get("transfer_mode", "destroy"))

	source_ent = executor._resolve_entity_from_ctx(ws, context, source_key)
	if source_ent is None:
		return [{"type": "ExecutorError", "message": f"ExchangeResources: source {source_key} not found"}]

	target_ent = None
	if transfer_mode == "transfer":
		target_ent = executor._resolve_entity_from_ctx(ws, context, target_key)
		if target_ent is None:
			return [{"type": "ExecutorError", "message": f"ExchangeResources: target {target_key} not found for transfer mode"}]

	consume_items = data.get("consume_items", [])
	consume_money = data.get("consume_money", 0.0)
	produce_items = data.get("produce_items", [])
	produce_money_raw = data.get("produce_money", 0.0)

	total_value = 0.0
	items_to_process = []
	for item_ref in consume_items:
		item = executor._resolve_entity_from_ctx(ws, context, item_ref)
		if item is None:
			return [{"type": "ExecutorError", "message": f"ExchangeResources: item to consume {item_ref} not found"}]
		items_to_process.append(item)
		val_comp = item.get_component("ValuableComponent")
		if isinstance(val_comp, ValuableComponent):
			total_value += float(val_comp.price)

	produce_money = total_value if produce_money_raw == "eval_price" else float(produce_money_raw)

	source_agent_comp = source_ent.get_component("AgentSetting")
	if source_agent_comp is None:
		return [{"type": "ExecutorError", "message": f"ExchangeResources: source {source_key} has no AgentSetting"}]

	source_money = float(getattr(source_agent_comp, "money", 0.0))
	if source_money < consume_money:
		return [{"type": "ExecutorError", "message": f"ExchangeResources: insufficient money. Has {source_money}, needs {consume_money}"}]

	target_agent_comp = None
	target_money = 0.0
	if transfer_mode == "transfer" and target_ent is not None:
		target_agent_comp = target_ent.get_component("AgentSetting")
		if target_agent_comp is not None:
			target_money = float(getattr(target_agent_comp, "money", 0.0))
			if target_money < produce_money:
				return [{"type": "ExecutorError", "message": f"ExchangeResources: target {target_key} has insufficient money to buy"}]

	events = []
	source_loc = ws.get_location_of_entity(source_ent.entity_id)
	source_location_id = str(getattr(source_loc, "location_id", "") or "")

	source_agent_comp.money = source_money - consume_money + produce_money
	if transfer_mode == "transfer" and target_agent_comp is not None:
		target_agent_comp.money = target_money + consume_money - produce_money

	if transfer_mode == "destroy":
		for item in items_to_process:
			events.extend(execute_destroy_entity(executor, ws, {"effect": "DestroyEntity", "target": "target"}, {"target_id": str(item.entity_id)}))
		for template_id in produce_items:
			events.extend(
				executor.execute(
					ws,
					{
						"effect": "CreateEntity",
						"template": str(template_id),
						"destination": {"type": "location", "target": source_location_id},
					},
					{"self_id": str(source_ent.entity_id)},
				)
			)
	elif transfer_mode == "transfer" and target_ent is not None:
		for item in items_to_process:
			events.extend(
				_execute_move_entity_core(
					executor,
					ws,
					{
						"entity_id": str(item.entity_id),
						"source_id": str(source_ent.entity_id),
						"destination_id": str(target_ent.entity_id),
					},
				)
			)
		for template_id in produce_items:
			events.extend(
				executor.execute(
					ws,
					{
						"effect": "CreateEntity",
						"template": str(template_id),
						"destination": {"type": "location", "target": source_location_id},
					},
					{"self_id": str(source_ent.entity_id)},
				)
			)

	events.append(
		{
			"type": "ResourcesExchanged",
			"source_id": str(source_ent.entity_id),
			"target_id": str(target_ent.entity_id) if target_ent else "",
			"mode": transfer_mode,
			"money_delta": produce_money - consume_money,
			"items_processed": [str(i.entity_id) for i in items_to_process],
			"items_produced_templates": produce_items,
		}
	)
	return events


def execute_abort_simulation(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	reason = str(data.get("reason", "") or "").strip()
	detail = str(data.get("detail", "") or "").strip()
	severity = str(data.get("severity", "error") or "error").strip().lower()
	stop = bool(data.get("stop", True))
	actor_id = str((context or {}).get("self_id", "") or "")
	services = getattr(ws, "services", {}) or {}
	services["abort_requested"] = bool(stop)
	services["abort_reason"] = reason
	services["abort_detail"] = detail
	services["abort_severity"] = severity
	services["abort_actor_id"] = actor_id
	if bool(stop):
		request_stop = services.get("request_stop")
		if callable(request_stop):
			request_stop(
				{
					"reason": reason,
					"detail": detail,
					"severity": severity,
					"actor_id": actor_id,
				}
			)
	return [
		{
			"type": "SimulationAbortRequested",
			"reason": reason,
			"detail": detail,
			"severity": severity,
			"stop": bool(stop),
			"actor_id": actor_id,
		}
	]
