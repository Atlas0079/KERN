from __future__ import annotations

from typing import Any

from ..execution_errors import KernFailure
from .context_builder import DecisionContextBuilder
from .workflow_contract import validate_workflow_decision
from ..interaction.action_resolver import resolve_action_intent as _resolve_action_intent


def prepare_workflow_decision_input(ws: Any, actor_id: str, workflow: Any, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	frame = DecisionContextBuilder().build(
		ws,
		actor_id,
		reason,
		mode_context,
		previous_action=None,
		actions_committed=0,
		replans=0,
	)
	return {
		"status": "ready",
		"actor_id": str(actor_id),
		"workflow": workflow,
		"reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"ws_view": dict(getattr(frame, "_legacy_workflow_view", {}) or {}),
		"recipe_db": dict(frame.action_catalog),
	}


def decide_from_prepared_workflow(prepared: dict[str, Any]) -> dict[str, Any]:
	workflow = prepared.get("workflow")
	actor_id = str(prepared.get("actor_id", "") or "")
	reason = str(prepared.get("reason", "") or "")
	mode_context = dict(prepared.get("mode_context", {}) or {})
	ws_view = prepared.get("ws_view", {}) or {}
	recipe_db = dict(prepared.get("recipe_db", {}) or {})
	try:
		decision_raw = workflow.decide(ws_view, recipe_db, actor_id, reason, mode_context)
	except KernFailure:
		raise
	except Exception as e:
		raise KernFailure(
			"WORKFLOW_PROVIDER_EXCEPTION",
			str(e),
			origin="workflow",
			phase="decision",
			context={"actor_id": actor_id, "reason": reason},
		) from e
	return {"status": "ok", "actor_id": actor_id, "decision_raw": decision_raw}


def commit_workflow_decision(
	ws: Any,
	actor_id: str,
	reason: str,
	decision_raw: Any,
	*,
	decide_error: str = "",
) -> dict[str, Any]:
	if decide_error:
		raise KernFailure(
			"WORKFLOW_PROVIDER_EXCEPTION",
			str(decide_error),
			origin="workflow",
			phase="decision",
			context={"actor_id": str(actor_id or ""), "reason": str(reason or "")},
		)
	decision, err = validate_workflow_decision(decision_raw)
	if decision is None:
		raise KernFailure(
			"WORKFLOW_CONTRACT_INVALID_DECISION",
			str(err),
			origin="workflow",
			phase="decision_validation",
			context={"actor_id": str(actor_id or ""), "raw_decision": decision_raw},
		)
	return _decision_to_outcome(ws, actor_id, str(reason or ""), decision)


def resolve_action_intent(ws: Any, actor_id: str, reason: str, action: dict[str, Any]) -> dict[str, Any]:
	"""Compatibility entry point; new code imports from KERN.interaction."""
	return _resolve_action_intent(ws, actor_id, reason, action)


def _apply_decision_memory_notes(ws: Any, actor_id: str, decision: dict[str, Any]) -> bool:
	DecisionContextBuilder.apply_step_meta(ws, actor_id, dict((decision or {}).get("meta", {}) or {}))
	return True


def _decision_to_outcome(ws: Any, actor_id: str, reason: str, decision: dict[str, Any]) -> dict[str, Any]:
	dtype = str((decision or {}).get("type", "") or "")
	if not _apply_decision_memory_notes(ws, actor_id, decision):
		raise KernFailure(
			"MEMORY_PATCH_FAILED",
			"decision memory notes could not be applied",
			origin="workflow",
			phase="memory_patch",
			context={"actor_id": str(actor_id or "")},
		)
	if dtype in {"end_turn", "action_plan"}:
		return dict(decision)
	raise KernFailure("INVALID_DECISION_TYPE", f"unsupported workflow decision type: {dtype}", origin="workflow", phase="decision_validation")


def run_workflow_cycle(
	ws: Any,
	actor_id: str,
	workflow: Any,
	reason: str,
	mode_context: dict[str, Any],
) -> dict[str, Any]:
	prepared = prepare_workflow_decision_input(ws, actor_id, workflow, reason, mode_context)
	if str(prepared.get("status", "") or "") != "ready":
		return dict(prepared.get("outcome", {"type": "end_turn"}) or {"type": "end_turn"})
	decided = decide_from_prepared_workflow(prepared)
	return commit_workflow_decision(
		ws,
		actor_id,
		str(reason or ""),
		decided.get("decision_raw"),
		decide_error=str(decided.get("error", "") or "") if str(decided.get("status", "") or "") != "ok" else "",
	)
