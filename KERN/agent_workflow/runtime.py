from __future__ import annotations

from typing import Any

from ..execution_errors import KernFailure
from .full_ws_view_builder import build_full_ws_view
from .memory_policy import build_memory_patch
from .view_profile import active_workflow_view_profile
from .workflow_contract import validate_workflow_decision
from ..interaction.results import ActionRejected
from ..interaction.narrative import render_interaction_narrative
from ..interaction.presentation import interaction_content


def _build_workflow_ws_view(ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	profile = active_workflow_view_profile(ws=ws, mode_context=mode_context, full_ws_view={})
	full_view = build_full_ws_view(ws, actor_id, reason, mode_context)
	full_view["workflow_view_profile"] = dict(profile)
	return {
		"full_ws_view": full_view,
		"interrupt_reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"workflow_view_profile": dict(profile),
	}


def _build_workflow_recipe_db(ws: Any) -> dict[str, Any]:
	services = getattr(ws, "services", {}) or {}
	interaction_engine = services.get("interaction_engine")
	if interaction_engine is None or not hasattr(interaction_engine, "recipe_db"):
		return {}
	recipe_db = getattr(interaction_engine, "recipe_db", {}) or {}
	return dict(recipe_db) if isinstance(recipe_db, dict) else {}


def prepare_workflow_decision_input(ws: Any, actor_id: str, workflow: Any, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	ws_view = _build_workflow_ws_view(ws, actor_id, reason, mode_context)
	recent_interactions = [
		dict(item)
		for item in list((ws_view.get("full_ws_view", {}) or {}).get("interaction_inbox", []) or [])
		if isinstance(item, dict)
	]
	recipe_db = _build_workflow_recipe_db(ws)
	try:
		mem_patch = build_memory_patch(
			full_ws_view=dict(ws_view.get("full_ws_view", {}) or {}),
			actor_id=str(actor_id),
		)
	except Exception as e:
		raise KernFailure(
			"WORKFLOW_MEMORY_PATCH_BUILD_FAILED",
			str(e),
			origin="workflow",
			phase="memory_patch",
			context={"actor_id": str(actor_id or "")},
		) from e
	if isinstance(mem_patch, dict) and mem_patch:
		if not _apply_memory_patch(ws, actor_id, mem_patch):
			raise KernFailure(
				"WORKFLOW_MEMORY_PATCH_APPLY_FAILED",
				"workflow memory patch executor failed",
				origin="workflow",
				phase="memory_patch",
				context={"actor_id": str(actor_id or "")},
			)
		ws_view = _build_workflow_ws_view(ws, actor_id, reason, mode_context)
	ws_view["full_ws_view"]["recent_interactions"] = recent_interactions
	return {
		"status": "ready",
		"actor_id": str(actor_id),
		"workflow": workflow,
		"reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"ws_view": ws_view,
		"recipe_db": recipe_db,
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


def _render_interaction_narrative(ws: Any, recipe: dict[str, Any], actor_name: str, target_name: str, verb: str, status: str, reason: str, values: dict[str, Any]) -> str:
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
			if not isinstance(recipe, dict):
				continue
			if not bool(recipe.get("is_meta", False)):
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
		raise KernFailure("INTERACTION_BUNDLE_INVALID", "interaction engine returned an invalid bundle", origin="interaction", phase="action_resolution")
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


def _apply_memory_patch(ws: Any, actor_id: str, mem_patch: dict[str, Any]) -> bool:
	services = getattr(ws, "services", {}) or {}
	execute = (services or {}).get("execute")
	if not callable(execute):
		return False
	mem_effect = {
		"effects": [
			{
				"effect": "ApplyMemoryPatch",
				"target": actor_id,
				"notes": [dict(x) for x in list(mem_patch.get("notes", []) or []) if isinstance(x, dict)],
				"consume_interaction_ids": [
					str(item)
					for item in list(mem_patch.get("consume_interaction_ids", []) or [])
					if str(item or "").strip()
				],
				"mid_term_summaries": [dict(x) for x in list(mem_patch.get("mid_term_summaries", []) or []) if isinstance(x, dict)],
				"clear_mid_term_prep": bool(mem_patch.get("clear_mid_term_prep", False)),
			}
		]
	}
	execute(mem_effect, {"self_id": actor_id, "target_id": actor_id})
	return True


def _apply_decision_memory_notes(ws: Any, actor_id: str, decision: dict[str, Any]) -> bool:
	meta = dict((decision or {}).get("meta", {}) or {})
	notes = [dict(x) for x in list(meta.get("memory_notes", []) or []) if isinstance(x, dict)]
	if not notes:
		return True
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	normalized: list[dict[str, Any]] = []
	for note in notes:
		content = str(note.get("content", note.get("text", "")) or "").strip()
		if not content:
			continue
		out = dict(note)
		out["content"] = content
		out.setdefault("tick", tick)
		out.setdefault("type", "note")
		out.setdefault("topic", "grounding")
		out.setdefault("importance", 0.8)
		out.setdefault("actor_id", actor_id)
		out.setdefault("tags", ["grounding", "ungroundable"])
		normalized.append(out)
	if not normalized:
		return True
	return _apply_memory_patch(
		ws,
		actor_id,
		{
			"notes": normalized,
			"consume_interaction_ids": [],
			"mid_term_summaries": [],
			"clear_mid_term_prep": False,
		},
	)


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
