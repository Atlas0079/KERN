from __future__ import annotations

from typing import Any

from ..dynamic_text import DynamicTextError, render_dynamic_payload_text_fields
from ..execution_errors import executor_error
from ._effect_binder import BindError, _base_bind, _require_param, _resolve_param_token


def _bind_emit_event(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	event_type = str(_resolve_param_token(_require_param(params, effect_type, "event_type"), ctx) or "").strip()
	if not event_type:
		raise BindError(effect_type, ["event_type"])
	payload = _resolve_param_token(_require_param(params, effect_type, "payload"), ctx)
	if payload is None:
		payload = {}
	if not isinstance(payload, dict):
		raise BindError(effect_type, ["payload_object"])
	return {"effect": effect_type, "event_type": event_type, "payload": dict(payload)}, ctx


def execute_emit_event(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	event_type = str(data.get("event_type", "") or "").strip()
	if not event_type:
		return executor_error("EmitEvent: event_type missing")
	payload = data.get("payload", {}) or {}
	if not isinstance(payload, dict):
		return executor_error("EmitEvent: payload must be object")
	try:
		payload_obj = render_dynamic_payload_text_fields(ws, context, payload)
	except DynamicTextError as exc:
		return executor_error(f"EmitEvent.payload: {exc}")
	if event_type == "MessageBroadcasted":
		source_ref = str(payload_obj.get("source_ref", "self") or "self")
		source_ent = executor._resolve_entity_from_ctx(ws, context, source_ref)
		if source_ent is None:
			return executor_error(f"EmitEvent: source {source_ref} not found")
		payload_obj["source_id"] = str(source_ent.entity_id)
		payload_obj.pop("source_ref", None)
	event: dict[str, Any] = {"type": event_type}
	for k, v in payload_obj.items():
		key = str(k)
		if key == "type":
			continue
		event[key] = v
	return [event]
