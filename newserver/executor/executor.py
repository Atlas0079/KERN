from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._effect_agent import (
	execute_agent_control_tick,
	execute_apply_meta_action,
	execute_attach_details,
	execute_worker_tick,
)
from ._effect_binder import BindError, bind_effect_input
from ._effect_conversation import execute_start_conversation
from ._effect_entity import (
	execute_create_entity,
	execute_destroy_entity,
	execute_kill_entity,
	execute_move_entity,
)
from ._effect_property import execute_add_tag, execute_modify_property, execute_remove_tag
from ._effect_task import (
	execute_add_status,
	execute_consume_inputs,
	execute_create_task,
	execute_accept_task,
	execute_finish_task,
	execute_progress_task,
	execute_remove_status,
	execute_status_tick,
	execute_update_task_status,
)
from ._effect_event import execute_emit_event
from ._effect_memory import execute_add_memory_note
from ..entity_ref_resolver import resolve_entity
from ..effect_contract import EFFECT_SPECS, EFFECT_TYPES
from ..models.components import ContainerComponent, ValuableComponent

_EFFECT_HANDLER_METHODS: dict[str, str] = {
	str(effect_name): str((spec or {}).get("handler", "") or "")
	for effect_name, spec in EFFECT_SPECS.items()
}


def get_executor_effect_types() -> set[str]:
	return {str(k) for k in _EFFECT_HANDLER_METHODS.keys()}


@dataclass
class WorldExecutor:
	"""
	Executor: Single entry point for world "write operations" (Align with Godot WorldExecutor.gd).

	Note:
	- This class only concerns "how to write", not "why to write" (Decision logic in Manager/LLM/Policy layer).
	- Effect Input Contract:
	  - data(effect_data): declarative operation payload, describes what to do.
	  - context: runtime invocation environment, describes where/who this call runs in.
	  - Handlers should primarily consume normalized data produced by binder; context is for runtime identity and refs.
	"""

	# Template required when creating entity at runtime; if not provided, CreateEntity will report error event
	entity_templates: dict[str, Any] | None = None

	def execute(self, ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			normalized_data, merged_ctx = bind_effect_input(ws, effect_data, context)
		except BindError as e:
			return [
				{
					"type": "BindError",
					"effect": str(getattr(e, "effect_type", "") or ""),
					"missing": list(getattr(e, "missing", []) or []),
					"message": str(e),
				}
			]
		effect_type = normalized_data.get("effect")
		if not effect_type:
			return [{"type": "ExecutorError", "message": "missing effect type"}]
		effect_name = str(effect_type)
		if effect_name not in EFFECT_TYPES:
			return [{"type": "ExecutorError", "message": f"unknown effect type: {effect_type}"}]
		handler_name = _EFFECT_HANDLER_METHODS.get(effect_name, "")
		handler = getattr(self, handler_name, None)
		if not callable(handler):
			return [{"type": "ExecutorError", "message": f"effect handler missing: {effect_name}"}]
		return handler(ws, normalized_data, merged_ctx)

	def _resolve_entity_from_ctx(self, ws: Any, ctx: dict[str, Any], key_or_idkey: str):
		ctx_dict = dict(ctx) if isinstance(ctx, dict) else {}
		key = str(key_or_idkey or "")
		if not key:
			return None
		direct_id = str(ctx_dict.get(key, "") or "")
		if direct_id:
			ent = ws.get_entity_by_id(direct_id)
			if ent is not None:
				return ent
		id_key = key if key.endswith("_id") else f"{key}_id"
		id_val = str(ctx_dict.get(id_key, "") or "")
		if id_val:
			ent = ws.get_entity_by_id(id_val)
			if ent is not None:
				return ent
		return resolve_entity(ws, key, ctx_dict, allow_literal=True)

	def _resolve_container_or_location_from_ctx(self, ws: Any, ctx: dict[str, Any], key_or_idkey: str):
		id_key = key_or_idkey if str(key_or_idkey).endswith("_id") else f"{key_or_idkey}_id"
		id_val = str((ctx or {}).get(id_key, ""))
		ent = ws.get_entity_by_id(id_val)
		if ent is not None and isinstance(ent.get_component("ContainerComponent"), ContainerComponent):
			return ent
		loc = ws.get_location_by_id(id_val)
		if loc is not None:
			return loc
		return None

	def _execute_agent_control_tick(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_agent_control_tick(self, ws, data, context)

	def _execute_worker_tick(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_worker_tick(self, ws, data, context)

	def _execute_status_tick(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_status_tick(self, ws, data, context)

	def _execute_modify_property(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_modify_property(self, ws, data, context)

	def _execute_add_tag(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_tag(self, ws, data, context)

	def _execute_remove_tag(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_remove_tag(self, ws, data, context)

	def _execute_apply_meta_action(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_apply_meta_action(self, ws, data, context)

	def _execute_attach_details(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_attach_details(self, ws, data, context)

	def _execute_create_entity(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_create_entity(self, ws, data, context)

	def _execute_destroy_entity(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_destroy_entity(self, ws, data, context)

	def _execute_move_entity(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_move_entity(self, ws, data, context)

	def _execute_kill_entity(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_kill_entity(self, ws, data, context)

	def _execute_start_conversation(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_start_conversation(self, ws, data, context)

	def _execute_add_memory_note(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_memory_note(self, ws, data, context)

	def _execute_emit_event(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_emit_event(self, ws, data, context)

	def _execute_exchange_resources(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		source_key = str(data.get("source", "self"))
		target_key = str(data.get("target", "target"))
		transfer_mode = str(data.get("transfer_mode", "destroy"))
		
		source_ent = self._resolve_entity_from_ctx(ws, context, source_key)
		if source_ent is None:
			return [{"type": "ExecutorError", "message": f"ExchangeResources: source {source_key} not found"}]
		
		target_ent = None
		if transfer_mode == "transfer":
			target_ent = self._resolve_entity_from_ctx(ws, context, target_key)
			if target_ent is None:
				return [{"type": "ExecutorError", "message": f"ExchangeResources: target {target_key} not found for transfer mode"}]
		
		consume_items = data.get("consume_items", [])
		consume_money = data.get("consume_money", 0.0)
		produce_items = data.get("produce_items", [])
		produce_money_raw = data.get("produce_money", 0.0)

		# 1. Evaluate total price of consumed items (if eval_price is requested)
		total_value = 0.0
		items_to_process = []
		for item_ref in consume_items:
			item = self._resolve_entity_from_ctx(ws, context, item_ref)
			if item is None:
				return [{"type": "ExecutorError", "message": f"ExchangeResources: item to consume {item_ref} not found"}]
			items_to_process.append(item)
			val_comp = item.get_component("ValuableComponent")
			if isinstance(val_comp, ValuableComponent):
				total_value += float(val_comp.price)

		produce_money = total_value if produce_money_raw == "eval_price" else float(produce_money_raw)

		# 2. Check and deduct money
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
		
		# 3. Apply changes
		events = []
		source_loc = ws.get_location_of_entity(source_ent.entity_id)
		source_location_id = str(getattr(source_loc, "location_id", "") or "")
		
		# Money transfer
		source_agent_comp.money = source_money - consume_money + produce_money
		if transfer_mode == "transfer" and target_agent_comp is not None:
			target_agent_comp.money = target_money + consume_money - produce_money

		# Items transfer
		if transfer_mode == "destroy":
			for item in items_to_process:
				events.extend(execute_destroy_entity(self, ws, {"effect": "DestroyEntity", "target": "target"}, {"target_id": str(item.entity_id)}))
			for template_id in produce_items:
				events.extend(
					self.execute(
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
			from ._effect_entity import _execute_move_entity_core
			for item in items_to_process:
				events.extend(_execute_move_entity_core(self, ws, {
					"entity_id": str(item.entity_id),
					"source_id": str(source_ent.entity_id),
					"destination_id": str(target_ent.entity_id)
				}))
			# Note: In transfer mode, 'produce_items' usually refers to entity_ids from target, not template_ids.
			# For simplicity here, if produce_items are template_ids, we still CreateEntity.
			# If you want true 2-way item transfer, you'd pass target's item IDs in produce_items and MoveEntity them back.
			for template_id in produce_items:
				events.extend(
					self.execute(
						ws,
						{
							"effect": "CreateEntity",
							"template": str(template_id),
							"destination": {"type": "location", "target": source_location_id},
						},
						{"self_id": str(source_ent.entity_id)},
					)
				)

		events.append({
			"type": "ResourcesExchanged",
			"source_id": str(source_ent.entity_id),
			"target_id": str(target_ent.entity_id) if target_ent else "",
			"mode": transfer_mode,
			"money_delta": produce_money - consume_money,
			"items_processed": [str(i.entity_id) for i in items_to_process],
			"items_produced_templates": produce_items
		})
		return events

	def _execute_abort_simulation(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
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

	def _execute_add_status(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_status(self, ws, data, context)

	def _execute_remove_status(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_remove_status(self, ws, data, context)

	def _execute_consume_inputs(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_consume_inputs(self, ws, data, context)

	def _execute_create_task(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_create_task(self, ws, data, context)

	def _execute_accept_task(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_accept_task(self, ws, data, context)

	def _execute_progress_task(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_progress_task(self, ws, data, context)

	def _execute_update_task_status(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_update_task_status(self, ws, data, context)

	def _execute_finish_task(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_finish_task(self, ws, data, context)
