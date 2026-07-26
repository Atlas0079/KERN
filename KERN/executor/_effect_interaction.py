from __future__ import annotations

from typing import Any

from ..execution_errors import executor_error
from ..perception import capture_interaction
from ._effect_binder import _base_bind, _require_str, _resolve_param_token


def _bind_record_interaction(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	verb = _require_str(params, effect_type, "verb")
	status = _require_str(params, effect_type, "status")
	actor_id = str(_resolve_param_token(params.get("actor_id", ctx.get("self_id", "")), ctx) or "").strip()
	target_id = str(_resolve_param_token(params.get("target_id", ctx.get("target_id", "")), ctx) or "").strip()
	reason = str(_resolve_param_token(params.get("reason", ""), ctx) or "")
	recipe_id = str(_resolve_param_token(params.get("recipe_id", ""), ctx) or "").strip()
	task_id = str(_resolve_param_token(params.get("task_id", ctx.get("task_id", "")), ctx) or "").strip()
	requested_origin = str(_resolve_param_token(params.get("interaction_origin", ""), ctx) or "").strip()
	context_origin = str(ctx.get("_interaction_origin", "") or "").strip()
	generated_origin = str(ctx.get("_generated_interaction_origin", "") or "").strip()
	origin = requested_origin or context_origin or generated_origin or "explicit"
	extra = _resolve_param_token(params.get("extra", {}) or {}, ctx)
	if not isinstance(extra, dict):
		extra = {}
	extra = dict(extra)
	extra.setdefault("interaction_origin", origin)
	event_context = dict(ctx)
	if actor_id:
		event_context["self_id"] = actor_id
		event_context["actor_id"] = actor_id
	return {
		"effect": effect_type,
		"actor_id": actor_id,
		"verb": verb,
		"target_id": target_id,
		"status": status,
		"reason": reason,
		"recipe_id": recipe_id,
		"task_id": task_id,
		"interaction_origin": origin,
		"extra": extra,
	}, event_context


def execute_record_interaction(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	if not hasattr(ws, "record_interaction_attempt"):
		return executor_error("RecordInteraction: world has no interaction log")
	extra = data.get("extra", {}) or {}
	if not isinstance(extra, dict):
		return executor_error("RecordInteraction: extra must be an object")
	extra = dict(extra)
	for key in ("_kern_bundle_id", "_kern_parent_bundle_id", "action_id", "_kern_effect_index"):
		if key in context and context.get(key) not in (None, ""):
			extra.setdefault(
				{"_kern_bundle_id": "bundle_id", "_kern_parent_bundle_id": "parent_bundle_id", "_kern_effect_index": "effect_index"}.get(key, key),
				context.get(key),
			)
	record = ws.record_interaction_attempt(
		actor_id=str(data.get("actor_id", "") or ""),
		verb=str(data.get("verb", "") or ""),
		target_id=str(data.get("target_id", "") or ""),
		status=str(data.get("status", "") or ""),
		reason=str(data.get("reason", "") or ""),
		recipe_id=str(data.get("recipe_id", "") or ""),
		task_id=str(data.get("task_id", "") or ""),
		extra=extra,
	)
	if not isinstance(record, dict):
		record = dict(getattr(ws, "interaction_log", [])[-1] or {}) if getattr(ws, "interaction_log", []) else {}
	perceived_by = capture_interaction(ws, record)
	return [
		{
			"type": "InteractionRecorded",
			"actor_id": str(data.get("actor_id", "") or ""),
			"target_id": str(data.get("target_id", "") or ""),
			"verb": str(data.get("verb", "") or ""),
			"status": str(data.get("status", "") or ""),
			"recipe_id": str(data.get("recipe_id", "") or ""),
			"task_id": str(data.get("task_id", "") or ""),
			"interaction_id": str(record.get("interaction_id", "") or ""),
			"interaction_origin": str(data.get("interaction_origin", "") or ""),
			"tick": int(record.get("tick", 0) or 0),
			"time_str": str(record.get("time_str", "") or ""),
			"perceived_by_agent_ids": list(perceived_by),
		}
	]
