from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._effect_agent import (
	execute_agent_control_tick,
	execute_apply_meta_action,
	execute_attach_interrupt_preset_details,
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
	execute_add_condition,
	execute_consume_inputs,
	execute_create_task,
	execute_accept_task,
	execute_finish_task,
	execute_progress_task,
	execute_remove_condition,
	execute_update_task_status,
)
from ._effect_cooldown import execute_set_cooldown
from ._effect_event import execute_emit_event
from ._effect_memory import execute_add_memory_note
from ..entity_ref_resolver import resolve_entity
from ..effect_contract import EFFECT_TYPES
from ..models.components import ContainerComponent

_EFFECT_HANDLER_METHODS: dict[str, str] = {
	"AgentControlTick": "_execute_agent_control_tick",
	"WorkerTick": "_execute_worker_tick",
	"ModifyProperty": "_execute_modify_property",
	"AddTag": "_execute_add_tag",
	"RemoveTag": "_execute_remove_tag",
	"ApplyMetaAction": "_execute_apply_meta_action",
	"AttachInterruptPresetDetails": "_execute_attach_interrupt_preset_details",
	"CreateEntity": "_execute_create_entity",
	"DestroyEntity": "_execute_destroy_entity",
	"MoveEntity": "_execute_move_entity",
	"AddCondition": "_execute_add_condition",
	"RemoveCondition": "_execute_remove_condition",
	"ConsumeInputs": "_execute_consume_inputs",
	"CreateTask": "_execute_create_task",
	"AcceptTask": "_execute_accept_task",
	"ProgressTask": "_execute_progress_task",
	"UpdateTaskStatus": "_execute_update_task_status",
	"FinishTask": "_execute_finish_task",
	"KillEntity": "_execute_kill_entity",
	"StartConversation": "_execute_start_conversation",
	"SetCooldown": "_execute_set_cooldown",
	"AddMemoryNote": "_execute_add_memory_note",
	"EmitEvent": "_execute_emit_event",
}


def get_executor_effect_types() -> set[str]:
	return {str(k) for k in _EFFECT_HANDLER_METHODS.keys()}


@dataclass
class WorldExecutor:
	"""
	Executor: Single entry point for world "write operations" (Align with Godot WorldExecutor.gd).

	Note:
	- This class only concerns "how to write", not "why to write" (Decision logic in Manager/LLM/Policy layer).
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

	def _execute_modify_property(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_modify_property(self, ws, data, context)

	def _execute_add_tag(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_tag(self, ws, data, context)

	def _execute_remove_tag(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_remove_tag(self, ws, data, context)

	def _execute_apply_meta_action(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_apply_meta_action(self, ws, data, context)

	def _execute_attach_interrupt_preset_details(self, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_attach_interrupt_preset_details(self, ws, _data, context)

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

	def _execute_set_cooldown(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_set_cooldown(self, ws, data, context)

	def _execute_add_memory_note(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_memory_note(self, ws, data, context)

	def _execute_emit_event(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_emit_event(self, ws, data, context)

	def _execute_add_condition(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_add_condition(self, ws, data, context)

	def _execute_remove_condition(self, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		return execute_remove_condition(self, ws, data, context)

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
