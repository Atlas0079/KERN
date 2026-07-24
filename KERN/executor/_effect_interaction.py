from __future__ import annotations

from typing import Any

from ..execution_errors import executor_error
from ._effect_binder import _base_bind, _require_str, _resolve_param_token


def _bind_record_interaction(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	verb = _require_str(params, effect_type, "verb")
	status = _require_str(params, effect_type, "status")
	actor_id = str(_resolve_param_token(params.get("actor_id", ctx.get("self_id", "")), ctx) or "").strip()
	target_id = str(_resolve_param_token(params.get("target_id", ctx.get("target_id", "")), ctx) or "").strip()
	reason = str(_resolve_param_token(params.get("reason", ""), ctx) or "")
	recipe_id = str(_resolve_param_token(params.get("recipe_id", ""), ctx) or "").strip()
	extra = _resolve_param_token(params.get("extra", {}) or {}, ctx)
	if not isinstance(extra, dict):
		extra = {}
	return {
		"effect": effect_type,
		"actor_id": actor_id,
		"verb": verb,
		"target_id": target_id,
		"status": status,
		"reason": reason,
		"recipe_id": recipe_id,
		"extra": dict(extra),
	}, ctx


def _bind_update_interaction_details(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	details_text = str(_resolve_param_token(params.get("details_text", ""), ctx) or "")
	if not details_text:
		from ._effect_binder import BindError

		raise BindError(effect_type, ["details_text"])
	actor_id = str(_resolve_param_token(params.get("actor_id", ctx.get("self_id", "")), ctx) or "").strip()
	return {"effect": effect_type, "details_text": details_text, "actor_id": actor_id}, ctx


def execute_record_interaction(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	if not hasattr(ws, "record_interaction_attempt"):
		return executor_error("RecordInteraction: world has no interaction log")
	extra = data.get("extra", {}) or {}
	if not isinstance(extra, dict):
		return executor_error("RecordInteraction: extra must be an object")
	ws.record_interaction_attempt(
		actor_id=str(data.get("actor_id", "") or ""),
		verb=str(data.get("verb", "") or ""),
		target_id=str(data.get("target_id", "") or ""),
		status=str(data.get("status", "") or ""),
		reason=str(data.get("reason", "") or ""),
		recipe_id=str(data.get("recipe_id", "") or ""),
		extra=dict(extra),
	)
	return [
		{
			"type": "InteractionRecorded",
			"actor_id": str(data.get("actor_id", "") or ""),
			"target_id": str(data.get("target_id", "") or ""),
			"verb": str(data.get("verb", "") or ""),
			"status": str(data.get("status", "") or ""),
			"recipe_id": str(data.get("recipe_id", "") or ""),
		}
	]


def execute_update_interaction_details(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	log = getattr(ws, "interaction_log", None)
	if not isinstance(log, list) or not log:
		return executor_error("UpdateInteractionDetails: interaction log is empty")
	last = log[-1]
	if not isinstance(last, dict):
		return executor_error("UpdateInteractionDetails: last interaction is invalid")
	actor_id = str(data.get("actor_id", "") or "")
	if actor_id and str(last.get("actor_id", "") or "") != actor_id:
		return executor_error("UpdateInteractionDetails: last interaction belongs to another actor")
	last["details_text"] = str(data.get("details_text", "") or "")
	last["private_to_actor"] = True
	return [
		{
			"type": "InteractionDetailsUpdated",
			"seq": int(last.get("seq", 0) or 0),
			"actor_id": actor_id,
		}
	]
