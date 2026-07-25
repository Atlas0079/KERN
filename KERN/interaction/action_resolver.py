from __future__ import annotations

from typing import Any

from ..execution_errors import KernFailure
from .narrative import render_interaction_narrative
from .presentation import interaction_content
from .results import ActionRejected


def _current_worker_task_id(ws: Any, actor_id: str) -> str:
	agent = ws.get_entity_by_id(actor_id) if hasattr(ws, "get_entity_by_id") else None
	if agent is None:
		return ""
	worker = agent.get_component("WorkerComponent") if hasattr(agent, "get_component") else None
	return str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""


def _current_worker_task(ws: Any, actor_id: str) -> Any | None:
	task_id = _current_worker_task_id(ws, actor_id)
	if not task_id or not hasattr(ws, "get_task_by_id"):
		return None
	return ws.get_task_by_id(task_id)


def _render_interaction_narrative(
	ws: Any,
	recipe: dict[str, Any],
	actor_name: str,
	target_name: str,
	verb: str,
	status: str,
	reason: str,
	values: dict[str, Any],
) -> str:
	template_key = "narrative_fail" if str(status or "") == "failed" else "narrative_success"
	template = str((recipe or {}).get(template_key, "") or "")
	if template:
		return render_interaction_narrative(
			ws,
			template,
			{"reason": str(reason or ""), "dynamic_values": {"actor": str(actor_name or ""), "target": str(target_name or ""), "reason": str(reason or "")}},
			values=dict(values or {}),
		)
	return interaction_content(
		{
			"actor_name": actor_name,
			"target_name": target_name,
			"verb": verb,
			"status": status,
			"reason": reason,
		}
	)


def _entity_display_name(entity: Any, fallback: str) -> str:
	if entity is None:
		return str(fallback or "")
	name = str(getattr(entity, "entity_name", "") or fallback or "")
	if hasattr(entity, "get_component"):
		setting = entity.get_component("AgentSetting")
		if setting is not None:
			name = str(getattr(setting, "agent_name", "") or name)
	return name


def resolve_action_intent(ws: Any, actor_id: str, reason: str, action: dict[str, Any]) -> dict[str, Any]:
	services = getattr(ws, "services", {}) or {}
	interaction_engine = services.get("interaction_engine")
	if interaction_engine is None or not hasattr(interaction_engine, "resolve_action"):
		raise KernFailure(
			"MISSING_INTERACTION_ENGINE",
			"interaction_engine unavailable",
			origin="interaction",
			phase="action_resolution",
			context={"actor_id": str(actor_id or "")},
		)
	meta_verbs: set[str] = set()
	recipe_db = getattr(interaction_engine, "recipe_db", {}) or {}
	if isinstance(recipe_db, dict):
		for recipe in recipe_db.values():
			if not isinstance(recipe, dict) or not bool(recipe.get("is_meta", False)):
				continue
			verb_name = str(recipe.get("verb", "") or "").strip()
			if verb_name:
				meta_verbs.add(verb_name)
	cmd = dict(action or {})
	verb = str(cmd.get("verb", "") or "").strip()
	if not verb:
		raise KernFailure(
			"ACTION_MISSING_VERB",
			"action.verb is required",
			origin="workflow",
			phase="action_resolution",
			context={"actor_id": str(actor_id or ""), "action": cmd},
		)
	if verb == "YieldCurrentTask":
		task_id = _current_worker_task_id(ws, actor_id)
		if not task_id:
			return _rejected_action(ws, actor_id, cmd, "NO_CURRENT_TASK_TO_YIELD", "YieldCurrentTask requested but no task is in progress")
		return {
			"status": "ready",
			"bundle": {
				"effects": [
					{
						"effect": "InterruptTask",
						"task_id": task_id,
						"reason": str(reason or ""),
						"interrupt_source": "manual_yield",
						"is_voluntary": True,
					}
				]
			},
			"context": {"self_id": actor_id, "actor_id": actor_id, "task_id": task_id, "verb": verb},
		}
	if verb == "AcceptTask" and _current_worker_task(ws, actor_id) is not None:
		return _rejected_action(
			ws,
			actor_id,
			cmd,
			"CURRENT_TASK_ACTIVE",
			"AcceptTask requested while another task is already in progress; yield it first",
		)
	if verb in meta_verbs:
		cmd["target_id"] = str(actor_id)
	result = interaction_engine.resolve_action(ws, actor_id, cmd)
	status = str((result or {}).get("status", "") or "")
	if status != "success":
		if status not in {"rejected", "failed"}:
			raise KernFailure(
				"INTERACTION_RESULT_INVALID",
				"interaction engine returned an invalid status",
				origin="interaction",
				phase="action_resolution",
				context={"actor_id": actor_id, "action": cmd, "result": result},
			)
		return _rejected_action(
			ws,
			actor_id,
			cmd,
			str((result or {}).get("reason", "") or "ACTION_REJECTED"),
			str((result or {}).get("message", "") or "action rejected by interaction engine"),
			mismatch_reasons=[dict(item) for item in list((result or {}).get("mismatch_reasons", []) or []) if isinstance(item, dict)],
		)
	ctx = dict((result or {}).get("context", {}) or {})
	bundle = (result or {}).get("bundle", {}) or {}
	if not isinstance(bundle, dict):
		raise KernFailure(
			"INTERACTION_BUNDLE_INVALID",
			"interaction engine returned an invalid bundle",
			origin="interaction",
			phase="action_resolution",
		)
	recipe = dict((result or {}).get("recipe", {}) or {}) if isinstance((result or {}).get("recipe", {}), dict) else {}
	ctx.update(
		{
			"recipe_id": str(recipe.get("id", "") or ""),
			"verb": verb,
			"actor_id": str(actor_id),
			"target_id": str(ctx.get("target_id", "") or cmd.get("target_id", "") or ""),
			"parameters": dict(ctx.get("parameters", {}) or {}),
		}
	)
	return {"status": "ready", "bundle": dict(bundle), "context": ctx}


def _rejected_action(
	ws: Any,
	actor_id: str,
	action: dict[str, Any],
	code: str,
	message: str,
	*,
	mismatch_reasons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	target_id = str(action.get("target_id", "") or "")
	actor = ws.get_entity_by_id(str(actor_id)) if hasattr(ws, "get_entity_by_id") else None
	target = ws.get_entity_by_id(target_id) if target_id and hasattr(ws, "get_entity_by_id") else None
	verb = str(action.get("verb", "") or "")
	narrative = _render_interaction_narrative(
		ws,
		{},
		_entity_display_name(actor, str(actor_id)),
		_entity_display_name(target, target_id),
		verb,
		"failed",
		str(code or message),
		dict(action),
	)
	rejection = ActionRejected(
		code=str(code or "ACTION_REJECTED"),
		message=str(message or "action rejected"),
		action_intent=dict(action),
		details={"mismatch_reasons": list(mismatch_reasons or [])},
		narrative=narrative,
	)
	return {"status": "rejected", "rejection": rejection.to_dict()}


__all__ = ["resolve_action_intent"]
