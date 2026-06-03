from __future__ import annotations

from typing import Any

from ..execution_errors import is_execution_error_event
from .full_ws_view_builder import build_full_ws_view
from .interrupt_runtime import check_if_interrupt_is_needed
from .workflow_contract import validate_workflow_decision


def workflow_contract_error_policy(ws: Any) -> str:
	raw = str(ws.runtime_state.workflow_contract_on_error or "fail_fast").strip().lower()
	if raw not in {"fail_fast", "degrade_to_noop"}:
		return "fail_fast"
	return raw


def _record_workflow_error_event(ws: Any, actor_id: str, stage: str, detail: dict[str, Any]) -> None:
	if hasattr(ws, "record_event"):
		ws.record_event(
			{"type": "WorkflowDecisionError", "stage": str(stage or ""), "detail": dict(detail or {})},
			{"actor_id": actor_id},
		)


def _build_workflow_ws_view(ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	full_view = build_full_ws_view(ws, actor_id, reason, mode_context)
	return {
		"full_ws_view": full_view,
		"interrupt_reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
	}


def _build_workflow_recipe_db(ws: Any) -> dict[str, Any]:
	services = getattr(ws, "services", {}) or {}
	interaction_engine = services.get("interaction_engine")
	if interaction_engine is None or not hasattr(interaction_engine, "recipe_db"):
		return {}
	recipe_db = getattr(interaction_engine, "recipe_db", {}) or {}
	return dict(recipe_db) if isinstance(recipe_db, dict) else {}


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


def _commands_to_operations(ws: Any, actor_id: str, reason: str, commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
	services = getattr(ws, "services", {}) or {}
	interaction_engine = services.get("interaction_engine")
	if interaction_engine is None or not hasattr(interaction_engine, "process_command"):
		return None, {"kind": "contract", "code": "MISSING_INTERACTION_ENGINE", "message": "interaction_engine unavailable"}
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
	ops: list[dict[str, Any]] = []
	for idx, command in enumerate(list(commands or [])):
		cmd = dict(command) if isinstance(command, dict) else {}
		verb = str(cmd.get("verb", "") or "").strip()
		if not verb:
			return None, {"kind": "contract", "code": "COMMAND_MISSING_VERB", "message": f"commands[{idx}].verb is required"}
		if verb == "ContinueCurrentTask":
			return [], None
		if verb == "YieldCurrentTask":
			task_id = _current_worker_task_id(ws, actor_id)
			if not task_id:
				return None, {"kind": "business", "code": "NO_CURRENT_TASK_TO_YIELD", "message": "YieldCurrentTask requested but no task is in progress"}
			ops.append(
				{
					"effect": {
						"effect": "InterruptTask",
						"task_id": task_id,
						"reason": str(reason or ""),
						"interrupt_source": "manual_yield",
						"is_voluntary": True,
					},
					"context": {"self_id": actor_id, "task_id": task_id},
				}
			)
			continue
		if verb == "AcceptTask":
			current_task = _current_worker_task(ws, actor_id)
			current_target_id = str(getattr(current_task, "target_entity_id", "") or "") if current_task is not None else ""
			command_target_id = str(cmd.get("target_id", "") or "")
			if current_target_id and command_target_id == current_target_id:
				continue
			if current_task is not None:
				return None, {
					"kind": "business",
					"code": "CURRENT_TASK_ACTIVE",
					"message": "AcceptTask requested while another task is already in progress; use ContinueCurrentTask or YieldCurrentTask first",
				}
		if verb in meta_verbs:
			cmd["target_id"] = str(actor_id)
		result = interaction_engine.process_command(ws, actor_id, cmd)
		status = str((result or {}).get("status", "") or "")
		if status != "success":
			return None, {
				"kind": "business",
				"code": str((result or {}).get("reason", "") or "COMMAND_REJECTED"),
				"message": str((result or {}).get("message", "") or "command rejected by interaction engine"),
			}
		ctx = dict((result or {}).get("context", {}) or {})
		bundle = (result or {}).get("bundle", {}) or {}
		if isinstance(bundle, dict):
			ops.append({"bundle": dict(bundle), "context": dict(ctx)})
	return ops, None


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
				"last_event_seq_seen": int(mem_patch.get("last_event_seq_seen", 0) or 0),
				"last_interaction_seq_seen": int(mem_patch.get("last_interaction_seq_seen", 0) or 0),
				"mid_term_summaries": [dict(x) for x in list(mem_patch.get("mid_term_summaries", []) or []) if isinstance(x, dict)],
				"clear_mid_term_prep": bool(mem_patch.get("clear_mid_term_prep", False)),
			}
		]
	}
	mem_events = execute(mem_effect, {"self_id": actor_id, "target_id": actor_id})
	for ev in list(mem_events or []):
		if is_execution_error_event(ev):
			return False
	return True


def _decision_to_outcome(ws: Any, actor_id: str, reason: str, decision: dict[str, Any]) -> dict[str, Any]:
	dtype = str((decision or {}).get("type", "") or "")
	if dtype == "noop":
		return {"type": "noop"}
	if dtype == "error":
		err = dict((decision or {}).get("error", {}) or {})
		kind = str(err.get("kind", "") or "")
		code = str(err.get("code", "") or "")
		message = str(err.get("message", "") or "")
		_record_workflow_error_event(ws, actor_id, "provider_error", {"kind": kind, "code": code, "message": message})
		return {"type": "error", "error": {"kind": kind, "code": code, "message": message}}
	if dtype == "apply_commands":
		commands = list((decision or {}).get("commands", []) or [])
		ops, cmd_error = _commands_to_operations(ws, actor_id, reason, commands)
		if cmd_error is not None:
			_record_workflow_error_event(ws, actor_id, "command_compile_failed", dict(cmd_error))
			return {
				"type": "error",
				"error": {
					"kind": str(cmd_error.get("kind", "") or ""),
					"code": str(cmd_error.get("code", "") or ""),
					"message": str(cmd_error.get("message", "") or ""),
				},
			}
		if not ops:
			return {"type": "noop"}
		return {"type": "apply_operations", "operations": [dict(x) for x in list(ops or []) if isinstance(x, dict)]}
	_record_workflow_error_event(ws, actor_id, "contract_invalid_type", {"type": dtype})
	return {"type": "error", "error": {"kind": "contract", "code": "INVALID_DECISION_TYPE", "message": str(dtype)}}


def _apply_operations(ws: Any, actor_id: str, operations: list[dict[str, Any]]) -> tuple[bool, bool]:
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	if not callable(execute):
		_record_workflow_error_event(
			ws,
			actor_id,
			"execute_missing",
			{"reason": "ws.services.execute not callable"},
		)
		return True, False
	ops = [dict(x) for x in list(operations or []) if isinstance(x, dict)]
	for op in list(ops):
		bundle = op.get("bundle", {}) or {}
		ctx = op.get("context", {}) or {}
		if not isinstance(bundle, dict) or not isinstance(ctx, dict):
			_record_workflow_error_event(ws, actor_id, "operation_invalid", {"operation": dict(op) if isinstance(op, dict) else str(op)})
			return True, False
		evs = execute(dict(bundle), dict(ctx))
		for ev in list(evs or []):
			if is_execution_error_event(ev):
				_record_workflow_error_event(ws, actor_id, "executor_failed", {"bundle": dict(bundle), "error_event": dict(ev)})
				return True, False
	return False, bool(ops)


def run_workflow_cycle(ws: Any, actor_id: str, workflow: Any, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	ws_view = _build_workflow_ws_view(ws, actor_id, reason, mode_context)
	recipe_db = _build_workflow_recipe_db(ws)
	if not hasattr(workflow, "build_memory_patch_data"):
		_record_workflow_error_event(
			ws,
			actor_id,
			"workflow_missing_memory_patch_data_hook",
			{"provider": str(type(workflow).__name__)},
		)
		return {
			"type": "error",
			"error": {
				"kind": "contract",
				"code": "WORKFLOW_MISSING_MEMORY_PATCH_HOOK",
				"message": str(type(workflow).__name__),
			},
		}
	try:
		mem_patch = workflow.build_memory_patch_data(ws_view, recipe_db, actor_id)
	except Exception as e:
		_record_workflow_error_event(ws, actor_id, "memory_patch_data_build_failed", {"error": str(e)})
		return {"type": "noop"}
	if isinstance(mem_patch, dict) and mem_patch:
		if not _apply_memory_patch(ws, actor_id, mem_patch):
			_record_workflow_error_event(ws, actor_id, "memory_patch_apply_failed", {"reason": "executor_failed"})
			return {"type": "noop"}
	try:
		decision_raw = workflow.decide(ws_view, recipe_db, actor_id, reason, mode_context)
	except Exception as e:
		_record_workflow_error_event(ws, actor_id, "decide_exception", {"error": str(e)})
		return {"type": "noop"}
	decision, err = validate_workflow_decision(decision_raw)
	if decision is None:
		_record_workflow_error_event(ws, actor_id, "contract_invalid", {"error": str(err), "raw": str(decision_raw)})
		return {"type": "error", "error": {"kind": "contract", "code": "WORKFLOW_CONTRACT_INVALID_DECISION", "message": str(err)}}
	return _decision_to_outcome(ws, actor_id, str(reason or ""), decision)


def run_agent_control_tick(ws: Any, actor_id: str, workflow: Any, max_actions_in_tick: int) -> None:
	agent = ws.get_entity_by_id(actor_id) if hasattr(ws, "get_entity_by_id") else None
	if agent is None:
		return
	arb = agent.get_component("DecisionArbiterComponent") if hasattr(agent, "get_component") else None
	if arb is None:
		return
	services = getattr(ws, "services", {}) or {}
	actions_executed = 0
	max_actions = max(1, int(max_actions_in_tick or 1))
	while actions_executed < max_actions:
		interrupt = check_if_interrupt_is_needed(ws=ws, agent_id=actor_id, arb=arb)
		if not bool(getattr(interrupt, "interrupt", False)):
			break
		reason = str(getattr(interrupt, "reason", "") or "")
		worker = agent.get_component("WorkerComponent") if hasattr(agent, "get_component") else None
		current_task_id = str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""
		mode_context = {
			"interrupt_decision_mode": bool(current_task_id),
			"interrupt_reason": reason,
		}
		outcome = run_workflow_cycle(ws, actor_id, workflow, reason, mode_context)
		otype = str((outcome or {}).get("type", "") or "")
		if otype == "error":
			err = dict((outcome or {}).get("error", {}) or {})
			kind = str(err.get("kind", "") or "")
			code = str(err.get("code", "") or "")
			message = str(err.get("message", "") or "")
			if kind == "contract" and workflow_contract_error_policy(ws) == "fail_fast":
				execute = (services or {}).get("execute")
				if callable(execute):
					execute(
						{
							"effects": [
								{
									"effect": "AbortSimulation",
									"reason": "workflow_contract_violation",
									"detail": f"{code}: {message}",
									"severity": "error",
									"stop": True,
								}
							]
						},
						{"self_id": actor_id},
					)
			break
		if otype == "noop":
			break
		if otype != "apply_operations":
			_record_workflow_error_event(ws, actor_id, "workflow_runtime_invalid_outcome_type", {"type": otype})
			if workflow_contract_error_policy(ws) == "fail_fast":
				execute = (services or {}).get("execute")
				if callable(execute):
					execute(
						{
							"effects": [
								{
									"effect": "AbortSimulation",
									"reason": "workflow_runtime_invalid_outcome_type",
									"detail": str(otype),
									"severity": "error",
									"stop": True,
								}
							]
						},
						{"self_id": actor_id},
					)
			break
		stop_loop, consumed = _apply_operations(ws, actor_id, list((outcome or {}).get("operations", []) or []))
		if consumed:
			actions_executed += 1
		if stop_loop:
			break
		worker_after = agent.get_component("WorkerComponent") if hasattr(agent, "get_component") else None
		if worker_after is not None and bool(getattr(worker_after, "current_task_id", "")):
			break
