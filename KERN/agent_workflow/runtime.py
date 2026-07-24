from __future__ import annotations

from typing import Any

from ..execution_errors import KernFailure
from .full_ws_view_builder import build_full_ws_view
from .interrupt_runtime import check_if_interrupt_is_needed
from .view_profile import active_workflow_view_profile
from .workflow_contract import validate_workflow_decision
from ..interaction.results import ActionRejected


def _build_workflow_ws_view(ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	full_view = build_full_ws_view(ws, actor_id, reason, mode_context)
	profile = active_workflow_view_profile(ws=ws, mode_context=mode_context, full_ws_view=full_view)
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
	recipe_db = _build_workflow_recipe_db(ws)
	if not hasattr(workflow, "build_memory_patch_data"):
		raise KernFailure(
			"WORKFLOW_MISSING_MEMORY_PATCH_HOOK",
			f"workflow provider {type(workflow).__name__} lacks build_memory_patch_data",
			origin="workflow",
			phase="workflow_input",
			context={"actor_id": str(actor_id or "")},
		)
	try:
		mem_patch = workflow.build_memory_patch_data(ws_view, recipe_db, actor_id)
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
	max_commands: int | None = None,
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
	if max_commands is not None and str(decision.get("type", "") or "") == "apply_commands":
		limit = max(0, int(max_commands or 0))
		decision["commands"] = [dict(x) for x in list(decision.get("commands", []) or [])[:limit] if isinstance(x, dict)]
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


def _render_interaction_narrative(recipe: dict[str, Any], actor_name: str, target_name: str, verb: str, status: str, reason: str, values: dict[str, Any]) -> str:
	template_key = "narrative_fail" if str(status or "") == "failed" else "narrative_success"
	template = str((recipe or {}).get(template_key, "") or "")
	render_values = dict(values or {})
	render_values["actor"] = str(actor_name or "")
	render_values["target"] = str(target_name or "")
	render_values["reason"] = str(reason or "")
	if template:
		out = template
		for key, value in render_values.items():
			out = out.replace("{" + str(key) + "}", str(value if value is not None else ""))
		return out
	if str(status or "") == "failed":
		if target_name:
			return f"{actor_name}对{target_name}执行{verb}失败：{reason or 'unknown'}"
		return f"{actor_name}执行{verb}失败：{reason or 'unknown'}"
	if target_name:
		return f"{actor_name}对{target_name}执行了{verb}"
	return f"{actor_name}执行了{verb}"


def _entity_display_name(entity: Any, fallback: str) -> str:
	if entity is None:
		return str(fallback or "")
	name = str(getattr(entity, "entity_name", "") or fallback or "")
	if hasattr(entity, "get_component"):
		setting = entity.get_component("AgentSetting")
		if setting is not None:
			name = str(getattr(setting, "agent_name", "") or name)
	return name


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
				return None, {"kind": "rejection", "code": "NO_CURRENT_TASK_TO_YIELD", "message": "YieldCurrentTask requested but no task is in progress"}
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
					"kind": "rejection",
					"code": "CURRENT_TASK_ACTIVE",
					"message": "AcceptTask requested while another task is already in progress; use ContinueCurrentTask or YieldCurrentTask first",
				}
		if verb in meta_verbs:
			cmd["target_id"] = str(actor_id)
		result = interaction_engine.process_command(ws, actor_id, cmd)
		status = str((result or {}).get("status", "") or "")
		if status != "success":
			reason_code = str((result or {}).get("reason", "") or "COMMAND_REJECTED")
			message = str((result or {}).get("message", "") or "command rejected by interaction engine")
			target_id = str(cmd.get("target_id", "") or "")
			actor = ws.get_entity_by_id(str(actor_id)) if hasattr(ws, "get_entity_by_id") else None
			target = ws.get_entity_by_id(target_id) if target_id and hasattr(ws, "get_entity_by_id") else None
			actor_name = _entity_display_name(actor, str(actor_id))
			target_name = _entity_display_name(target, target_id)
			narrative = _render_interaction_narrative({}, actor_name, target_name, verb, "failed", reason_code or message, dict(cmd))
			return None, {
				"kind": "rejection" if status in {"rejected", "failed"} else "contract",
				"code": reason_code,
				"message": message,
				"command_index": int(idx),
				"command": dict(cmd),
				"narrative": narrative,
				"mismatch_reasons": [dict(item) for item in list((result or {}).get("mismatch_reasons", []) or []) if isinstance(item, dict)],
			}
		ctx = dict((result or {}).get("context", {}) or {})
		bundle = (result or {}).get("bundle", {}) or {}
		recipe = dict((result or {}).get("recipe", {}) or {}) if isinstance((result or {}).get("recipe", {}), dict) else {}
		recipe_id = str(recipe.get("id", "") or "")
		target_id = str(ctx.get("target_id", "") or cmd.get("target_id", "") or "")
		params = dict(ctx.get("parameters", {}) or {}) if isinstance(ctx.get("parameters", {}), dict) else {}
		if isinstance(bundle, dict):
			operation_context = dict(ctx)
			operation_context["recipe_id"] = recipe_id
			operation_context["verb"] = verb
			operation_context["actor_id"] = str(actor_id)
			operation_context["target_id"] = target_id
			operation_context["parameters"] = params
			compiled_bundle = dict(bundle)
			ops.append({"bundle": compiled_bundle, "context": operation_context})
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
			"last_event_seq_seen": 0,
			"last_interaction_seq_seen": 0,
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
	if dtype == "noop":
		return {"type": "noop"}
	if dtype == "apply_commands":
		commands = list((decision or {}).get("commands", []) or [])
		ops, cmd_error = _commands_to_operations(ws, actor_id, reason, commands)
		if cmd_error is not None:
			if str(cmd_error.get("kind", "") or "") == "rejection":
				rejection = ActionRejected(
					code=str(cmd_error.get("code", "ACTION_REJECTED") or "ACTION_REJECTED"),
					message=str(cmd_error.get("message", "action rejected") or "action rejected"),
					command_index=int(cmd_error.get("command_index", -1) or -1),
					command=dict(cmd_error.get("command", {}) or {}),
					details={"mismatch_reasons": list(cmd_error.get("mismatch_reasons", []) or [])},
					narrative=str(cmd_error.get("narrative", "") or ""),
				)
				return {"type": "rejected", "rejection": rejection.to_dict()}
			raise KernFailure(
				str(cmd_error.get("code", "COMMAND_COMPILATION_FAILED") or "COMMAND_COMPILATION_FAILED"),
				str(cmd_error.get("message", "command compilation failed") or "command compilation failed"),
				origin="interaction",
				phase="command_compilation",
				context=dict(cmd_error),
			)
		if not ops:
			return {"type": "noop"}
	return {
		"type": "apply_operations",
		"operations": [dict(x) for x in list(ops or []) if isinstance(x, dict)],
	}
	raise KernFailure(
		"INVALID_DECISION_TYPE",
		f"unsupported workflow decision type: {dtype}",
		origin="workflow",
		phase="decision_validation",
		context={"actor_id": str(actor_id or ""), "type": dtype},
	)


def _apply_operations(ws: Any, actor_id: str, operations: list[dict[str, Any]]) -> tuple[bool, bool]:
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	if not callable(execute):
		raise KernFailure(
			"EXECUTE_SERVICE_MISSING",
			"ws.services.execute is not callable",
			origin="workflow",
			phase="action_execution",
			context={"actor_id": str(actor_id or "")},
		)
	ops = [dict(x) for x in list(operations or []) if isinstance(x, dict)]
	for op in list(ops):
		bundle = op.get("bundle", {}) or {}
		ctx = op.get("context", {}) or {}
		if not isinstance(bundle, dict) or not isinstance(ctx, dict):
			raise KernFailure(
				"INVALID_ACTION_OPERATION",
				"workflow produced an invalid operation",
				origin="workflow",
				phase="action_execution",
				context={"actor_id": str(actor_id or ""), "operation": dict(op) if isinstance(op, dict) else str(op)},
			)
		execute(dict(bundle), dict(ctx))
	return False, bool(ops)


def run_workflow_cycle(
	ws: Any,
	actor_id: str,
	workflow: Any,
	reason: str,
	mode_context: dict[str, Any],
	max_commands: int | None = None,
) -> dict[str, Any]:
	prepared = prepare_workflow_decision_input(ws, actor_id, workflow, reason, mode_context)
	if str(prepared.get("status", "") or "") != "ready":
		return dict(prepared.get("outcome", {"type": "noop"}) or {"type": "noop"})
	decided = decide_from_prepared_workflow(prepared)
	return commit_workflow_decision(
		ws,
		actor_id,
		str(reason or ""),
		decided.get("decision_raw"),
		max_commands=max_commands,
		decide_error=str(decided.get("error", "") or "") if str(decided.get("status", "") or "") != "ok" else "",
	)


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
		if otype == "rejected":
			actions_executed += 1
			break
		if otype == "noop":
			break
		if otype != "apply_operations":
			raise KernFailure(
				"WORKFLOW_RUNTIME_INVALID_OUTCOME",
				f"workflow returned unsupported outcome type: {otype}",
				origin="workflow",
				phase="decision_commit",
				context={"actor_id": str(actor_id or ""), "outcome_type": otype},
			)
		stop_loop, consumed = _apply_operations(
			ws,
			actor_id,
			list((outcome or {}).get("operations", []) or []),
		)
		if consumed:
			actions_executed += 1
		if stop_loop:
			break
		worker_after = agent.get_component("WorkerComponent") if hasattr(agent, "get_component") else None
		if worker_after is not None and bool(getattr(worker_after, "current_task_id", "")):
			break
