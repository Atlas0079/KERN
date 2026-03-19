from __future__ import annotations

from typing import Any

from ..entity_ref_resolver import resolve_entity_id
from ..effect_contract import EFFECT_TYPES


class BindError(RuntimeError):
	def __init__(self, effect_type: str, missing: list[str]):
		self.effect_type = str(effect_type or "")
		self.missing = [str(x) for x in list(missing or []) if str(x)]
		super().__init__(f"{self.effect_type}: missing required context {self.missing}")


def _as_dict(x: Any) -> dict[str, Any]:
	return dict(x) if isinstance(x, dict) else {}


def _resolve_ref_id(ref: Any, ctx: dict[str, Any]) -> str:
	return resolve_entity_id(ref, ctx, allow_literal=False)


def _base_bind(effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
	src = _as_dict(effect_data)
	ctx = _as_dict(context)
	effect_type = str(src.get("effect", "") or "")
	params = {k: v for k, v in src.items() if k != "effect"}
	return effect_type, params, ctx


def _bind_agent_control_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	entity_id = str(params.get("entity_id", "") or "")
	if entity_id and not str(ctx.get("entity_id", "") or ""):
		ctx["entity_id"] = entity_id
	if "max_actions_in_tick" in params and "max_actions_in_tick" not in ctx:
		ctx["max_actions_in_tick"] = params.get("max_actions_in_tick")
	return {"effect": effect_type, "entity_id": str(ctx.get("entity_id", "") or ""), "max_actions_in_tick": ctx.get("max_actions_in_tick", 50)}, ctx


def _bind_worker_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	entity_id = str(params.get("entity_id", "") or "")
	if entity_id and not str(ctx.get("entity_id", "") or ""):
		ctx["entity_id"] = entity_id
	if "ticks" in params and "ticks" not in ctx:
		ctx["ticks"] = params.get("ticks")
	return {"effect": effect_type, "entity_id": str(ctx.get("entity_id", "") or ""), "ticks": int(ctx.get("ticks", 1) or 1)}, ctx


def _bind_modify_property(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "")) or "")
	component = str(params.get("component", ctx.get("component", "")) or "")
	prop = str(params.get("property", ctx.get("property", "")) or "")
	has_change = "change" in params
	has_value = "value" in params
	missing: list[str] = []
	if not target:
		missing.append("target")
	if not component:
		missing.append("component")
	if not prop:
		missing.append("property")
	if not has_change and not has_value:
		missing.append("change_or_value")
	if has_change and has_value:
		missing.append("change_or_value_xor")
	if missing:
		raise BindError(effect_type, missing)
	ctx["target"] = target
	ctx["component"] = component
	ctx["property"] = prop
	out: dict[str, Any] = {"effect": effect_type, "target": target, "component": component, "property": prop}
	if has_change:
		change = float(params.get("change", 0.0) or 0.0)
		ctx["change"] = change
		out["change"] = change
	elif has_value:
		value = params.get("value", None)
		ctx["value"] = value
		out["value"] = value
	return out, ctx


def _bind_add_tag(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "target")) or "target")
	tag = str(params.get("tag", ctx.get("tag", "")) or "").strip()
	missing: list[str] = []
	if not tag:
		missing.append("tag")
	if missing:
		raise BindError(effect_type, missing)
	ctx["target"] = target
	ctx["tag"] = tag
	return {"effect": effect_type, "target": target, "tag": tag}, ctx


def _bind_remove_tag(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "target")) or "target")
	tag = str(params.get("tag", ctx.get("tag", "")) or "").strip()
	missing: list[str] = []
	if not tag:
		missing.append("tag")
	if missing:
		raise BindError(effect_type, missing)
	ctx["target"] = target
	ctx["tag"] = tag
	return {"effect": effect_type, "target": target, "tag": tag}, ctx


def _bind_apply_meta_action(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "self")) or "self")
	action_type = str(params.get("action_type", ctx.get("action_type", "")) or "")
	meta_params = params.get("params", ctx.get("params", {}))
	if not isinstance(meta_params, dict):
		meta_params = {}
	if not action_type:
		raise BindError(effect_type, ["action_type"])
	return {"effect": effect_type, "target": target, "action_type": action_type, "params": dict(meta_params)}, ctx


def _bind_attach_interrupt_preset_details(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def _bind_create_entity(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	out: dict[str, Any] = {"effect": effect_type}
	for k in ["template", "destination", "instance_id", "spawn_patch", "overrides"]:
		if k in params:
			out[k] = params[k]
		elif k in ctx:
			out[k] = ctx[k]
	return out, ctx


def _bind_destroy_entity(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "entity_to_destroy")) or "entity_to_destroy")
	return {"effect": effect_type, "target": target}, ctx


def _bind_move_entity(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	legacy_keys = [k for k in ["entity_id", "source_id", "destination_id", "target", "source", "destination"] if k in params]
	if legacy_keys:
		raise BindError(effect_type, [f"deprecated_keys:{','.join(sorted(legacy_keys))}"])
	entity_ref = params.get("entity_ref", ctx.get("entity_ref", ""))
	from_ref = params.get("from_ref", ctx.get("from_ref", ""))
	to_ref = params.get("to_ref", ctx.get("to_ref", ""))
	entity_id = _resolve_ref_id(entity_ref, ctx)
	source_id = _resolve_ref_id(from_ref, ctx)
	destination_id = _resolve_ref_id(to_ref, ctx)
	ctx["entity_id"] = entity_id
	ctx["source_id"] = source_id
	ctx["destination_id"] = destination_id
	missing: list[str] = []
	if not entity_id:
		missing.append("entity_id")
	if not source_id:
		missing.append("source_id")
	if not destination_id:
		missing.append("destination_id")
	if missing:
		raise BindError(effect_type, missing)
	return {"effect": effect_type}, ctx


def _bind_add_condition(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "")) or "")
	condition_id = str(params.get("condition_id", ctx.get("condition_id", "")) or "")
	missing: list[str] = []
	if not target:
		missing.append("target")
	if not condition_id:
		missing.append("condition_id")
	if missing:
		raise BindError(effect_type, missing)
	return {"effect": effect_type, "target": target, "condition_id": condition_id}, ctx


def _bind_remove_condition(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "")) or "")
	condition_id = str(params.get("condition_id", ctx.get("condition_id", "")) or "")
	missing: list[str] = []
	if not target:
		missing.append("target")
	if not condition_id:
		missing.append("condition_id")
	if missing:
		raise BindError(effect_type, missing)
	return {"effect": effect_type, "target": target, "condition_id": condition_id}, ctx


def _bind_consume_inputs(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def _bind_create_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	if not str(ctx.get("target_id", "") or ""):
		raise BindError(effect_type, ["target_id"])
	recipe = ctx.get("recipe", {})
	if not isinstance(recipe, dict) or not recipe:
		raise BindError(effect_type, ["recipe"])
	return {"effect": effect_type}, ctx


def _bind_accept_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "target")) or "target")
	return {"effect": effect_type, "target": target}, ctx


def _bind_progress_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	task_id = str(params.get("task_id", ctx.get("task_id", "")) or "")
	delta = float(params.get("delta", ctx.get("delta", 0.0)) or 0.0)
	if not task_id:
		raise BindError(effect_type, ["task_id"])
	return {"effect": effect_type, "task_id": task_id, "delta": delta}, ctx


def _bind_update_task_status(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	task_id = str(params.get("task_id", ctx.get("task_id", "")) or "")
	status = str(params.get("status", ctx.get("status", "")) or "")
	missing: list[str] = []
	if not task_id:
		missing.append("task_id")
	if not status:
		missing.append("status")
	if missing:
		raise BindError(effect_type, missing)
	return {"effect": effect_type, "task_id": task_id, "status": status}, ctx


def _bind_finish_task(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def _bind_kill_entity(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "target")) or "target")
	corpse_template = str(params.get("corpse_template", ctx.get("corpse_template", "Corpse")) or "Corpse")
	reason = str(params.get("reason", ctx.get("reason", "killed")) or "killed")
	return {"effect": effect_type, "target": target, "corpse_template": corpse_template, "reason": reason}, ctx


def _bind_start_conversation(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	max_utterances = int(params.get("max_utterances_per_tick", ctx.get("max_utterances_per_tick", 4)) or 4)
	opening_text = ""
	ctx_params = ctx.get("parameters", {}) or {}
	if isinstance(ctx_params, dict):
		opening_text = str(ctx_params.get("text", "") or "")
	return {"effect": effect_type, "max_utterances_per_tick": max_utterances, "opening_text": opening_text}, ctx


def _bind_set_cooldown(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "self")) or "self")
	key = str(params.get("key", ctx.get("key", "")) or "")
	if not key:
		raise BindError(effect_type, ["key"])
	return {"effect": effect_type, "target": target, "key": key}, ctx


def _bind_add_memory_note(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = str(params.get("target", ctx.get("target", "self")) or "self")
	text = str(params.get("text", ctx.get("text", "")) or "").strip()
	if not text:
		raise BindError(effect_type, ["text"])
	out: dict[str, Any] = {"effect": effect_type, "target": target, "text": text}
	if "importance" in params:
		out["importance"] = params.get("importance")
	if "tags" in params:
		out["tags"] = params.get("tags")
	return out, ctx


def _bind_emit_event(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	event_type = str(params.get("event_type", ctx.get("event_type", "")) or "").strip()
	if not event_type:
		raise BindError(effect_type, ["event_type"])
	payload = params.get("payload", ctx.get("payload", {}))
	if payload is None:
		payload = {}
	if not isinstance(payload, dict):
		raise BindError(effect_type, ["payload_object"])
	return {"effect": effect_type, "event_type": event_type, "payload": dict(payload)}, ctx


_BINDERS: dict[str, Any] = {
	"AgentControlTick": _bind_agent_control_tick,
	"WorkerTick": _bind_worker_tick,
	"ModifyProperty": _bind_modify_property,
	"AddTag": _bind_add_tag,
	"RemoveTag": _bind_remove_tag,
	"ApplyMetaAction": _bind_apply_meta_action,
	"AttachInterruptPresetDetails": _bind_attach_interrupt_preset_details,
	"CreateEntity": _bind_create_entity,
	"DestroyEntity": _bind_destroy_entity,
	"MoveEntity": _bind_move_entity,
	"AddCondition": _bind_add_condition,
	"RemoveCondition": _bind_remove_condition,
	"ConsumeInputs": _bind_consume_inputs,
	"CreateTask": _bind_create_task,
	"AcceptTask": _bind_accept_task,
	"ProgressTask": _bind_progress_task,
	"UpdateTaskStatus": _bind_update_task_status,
	"FinishTask": _bind_finish_task,
	"KillEntity": _bind_kill_entity,
	"StartConversation": _bind_start_conversation,
	"SetCooldown": _bind_set_cooldown,
	"AddMemoryNote": _bind_add_memory_note,
	"EmitEvent": _bind_emit_event,
}


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
