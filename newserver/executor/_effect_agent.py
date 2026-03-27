from __future__ import annotations

from typing import Any

from ..log_manager import get_logger
from ..entity_ref_resolver import resolve_entity
from ..models.components import DecisionArbiterComponent, WorkerComponent
from ._effect_binder import BindError, _base_bind, _require_dict, _require_int, _require_str, _resolve_param_token


def _bind_agent_control_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	entity_id = str((ctx or {}).get("entity_id", "") or "")
	max_actions = _require_int(params, effect_type, "max_actions_in_tick", ctx)
	return {"effect": effect_type, "entity_id": entity_id, "max_actions_in_tick": max_actions}, ctx


def _bind_worker_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	entity_id = str((ctx or {}).get("entity_id", "") or "")
	ticks = _require_int(params, effect_type, "ticks", ctx)
	return {"effect": effect_type, "entity_id": entity_id, "ticks": ticks}, ctx


def _bind_apply_meta_action(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	action_type = _require_str(params, effect_type, "action_type")
	meta_params = _require_dict(params, effect_type, "params", ctx)
	resolved_meta_params = _resolve_param_token(dict(meta_params), ctx)
	if not isinstance(resolved_meta_params, dict):
		resolved_meta_params = {}
	return {"effect": effect_type, "target": target, "action_type": action_type, "params": dict(resolved_meta_params)}, ctx


def _bind_attach_details(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	detail_type = _require_str(params, effect_type, "detail_type").lower()
	if detail_type not in {"entity", "interrupt_preset"}:
		raise BindError(effect_type, ["detail_type"])
	out: dict[str, Any] = {"effect": effect_type, "detail_type": detail_type}
	if detail_type == "entity":
		out["target"] = _require_str(params, effect_type, "target")
		return out, ctx
	preset_id = str(_resolve_param_token(params.get("preset_id", ""), ctx) or "").strip()
	if preset_id:
		out["preset_id"] = preset_id
	return out, ctx


def execute_agent_control_tick(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	logger = get_logger()
	self_id = str(
		data.get("entity_id")
		or (context or {}).get("entity_id", "")
		or (context or {}).get("event_entity_id", "")
		or ""
	)
	if not self_id:
		return []
	agent = ws.get_entity_by_id(self_id)
	if agent is None:
		return []
	ctrl = agent.get_component("AgentControlComponent")
	if ctrl is None or not bool(getattr(ctrl, "enabled", True)):
		return []
	arb = agent.get_component("DecisionArbiterComponent")
	if arb is None:
		return []
	interrupt = arb.check_if_interrupt_is_needed(ws, self_id)
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	services = getattr(ws, "services", {}) or {}
	perception_system = services.get("perception_system")
	interaction_engine = services.get("interaction_engine")
	default_action_provider = services.get("default_action_provider")
	action_providers = services.get("action_providers", {}) or {}
	pid = str(getattr(ctrl, "provider_id", "") or "").strip()
	action_provider = default_action_provider if not pid else action_providers.get(pid)
	pending_actions: list[dict[str, Any]] | None = None
	worker = agent.get_component("WorkerComponent")
	current_task_id = str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""
	if worker is not None and current_task_id:
		if not getattr(interrupt, "interrupt", False):
			return []
		reason = str(getattr(interrupt, "reason", "") or "")
		if action_provider is not None and perception_system is not None and interaction_engine is not None:
			perception = perception_system.perceive(ws, self_id)
			engine = (getattr(ws, "services", {}) or {}).get("interaction_engine")
			if engine is not None and hasattr(engine, "recipe_db") and isinstance(getattr(engine, "recipe_db"), dict):
				perception["recipe_db"] = dict(getattr(engine, "recipe_db"))
			perception["interrupt_decision_mode"] = True
			perception["interrupt_reason"] = reason
			try:
				actions = action_provider.decide(perception, reason, self_id)
			except TypeError:
				try:
					actions = action_provider.decide(perception, reason)
				except Exception:
					actions = []
			except Exception:
				actions = []
			if actions:
				first = dict(actions[0]) if isinstance(actions[0], dict) else {}
				first_verb = str(first.get("verb", "") or "")
				if first_verb == "ContinueCurrentTask":
					ws.record_event(
						{"type": "TaskContinueChosen", "task_id": current_task_id, "reason": reason},
						{"actor_id": self_id},
					)
					ws.record_interaction_attempt(
						actor_id=self_id,
						verb="ContinueCurrentTask",
						target_id=self_id,
						status="success",
						reason="",
						recipe_id="system.continue_current_task",
						extra={"interrupt_reason": reason, "task_id": current_task_id},
					)
					return []
				pending_actions = [dict(x) for x in list(actions or []) if isinstance(x, dict)]
			else:
				ws.record_event(
					{"type": "TaskContinueChosen", "task_id": current_task_id, "reason": reason, "decision": "no_new_action"},
					{"actor_id": self_id},
				)
				return []
		task = ws.get_task_by_id(current_task_id)
		if task is not None:
			is_shared_task = str(getattr(task, "target_entity_id", "") or "") != str(self_id)
			if is_shared_task:
				if hasattr(task, "assigned_agent_ids") and isinstance(getattr(task, "assigned_agent_ids"), list):
					task.assigned_agent_ids = []
				if hasattr(task, "task_status"):
					task.task_status = "Inactive"
				ws.record_event(
					{"type": "TaskReleased", "task_id": current_task_id, "reason": str(getattr(interrupt, "reason", "") or "")},
					{"actor_id": self_id},
				)
			elif hasattr(task, "task_status") and callable(execute):
				execute(
					{
						"effect": "UpdateTaskStatus",
						"task_id": current_task_id,
						"status": "Paused",
					},
					{"self_id": self_id, "task_id": current_task_id},
				)
		worker.stop_task()
		if task is not None and str(getattr(task, "target_entity_id", "") or "") == str(self_id):
			ws.record_event(
				{"type": "TaskInterrupted", "task_id": current_task_id, "reason": str(getattr(interrupt, "reason", "") or "")},
				{"actor_id": self_id},
			)
	elif not getattr(interrupt, "interrupt", False):
		return []
	if action_provider is None:
		return []
	if perception_system is None:
		return []
	if interaction_engine is None:
		return []
	max_actions_in_tick = int(data.get("max_actions_in_tick"))
	actions_executed = 0
	reason = str(getattr(interrupt, "reason", "") or "")
	while True:
		worker = agent.get_component("WorkerComponent")
		if worker is not None and bool(getattr(worker, "current_task_id", "")):
			break
		if pending_actions is None:
			interrupt = arb.check_if_interrupt_is_needed(ws, self_id)
			if not getattr(interrupt, "interrupt", False):
				break
			reason = str(getattr(interrupt, "reason", "") or "")
		perception = perception_system.perceive(ws, self_id)
		engine = (getattr(ws, "services", {}) or {}).get("interaction_engine")
		if engine is not None and hasattr(engine, "recipe_db") and isinstance(getattr(engine, "recipe_db"), dict):
			perception["recipe_db"] = dict(getattr(engine, "recipe_db"))
		if pending_actions is not None:
			actions = list(pending_actions)
			pending_actions = None
		else:
			try:
				actions = action_provider.decide(perception, reason, self_id)
			except TypeError:
				try:
					actions = action_provider.decide(perception, reason)
				except Exception as e:
					ws.record_event({"type": "ActionProviderError", "stage": "decide", "error": str(e)}, {"actor_id": self_id})
					return []
			except Exception as e:
				ws.record_event({"type": "ActionProviderError", "stage": "decide", "error": str(e)}, {"actor_id": self_id})
				return []
		if not actions:
			break
		meta_verbs: set[str] = set()
		recipe_db = getattr(interaction_engine, "recipe_db", {}) or {}
		if isinstance(recipe_db, dict):
			for r in recipe_db.values():
				if not isinstance(r, dict) or not bool(r.get("is_meta", False)):
					continue
				v = str(r.get("verb", "") or "").strip()
				if v:
					meta_verbs.add(v)
		for action in actions:
			action_dict = dict(action) if isinstance(action, dict) else {}
			verb = str(action_dict.get("verb", "") or "")
			target_id = str(action_dict.get("target_id", "") or "")
			if verb == "ContinueCurrentTask":
				worker_now = agent.get_component("WorkerComponent")
				if worker_now is not None and bool(getattr(worker_now, "current_task_id", "")):
					ws.record_interaction_attempt(
						actor_id=self_id,
						verb=verb,
						target_id=self_id,
						status="success",
						reason="",
						recipe_id="system.continue_current_task",
						extra=None,
					)
					return []
				logger.warn(
					"interaction",
					"command_failed",
					context={"self_id": self_id, "verb": verb, "target_id": self_id, "reason": "NO_CURRENT_TASK_TO_CONTINUE", "action": dict(action_dict)},
				)
				ws.record_interaction_attempt(
					actor_id=self_id,
					verb=verb,
					target_id=self_id,
					status="failed",
					reason="NO_CURRENT_TASK_TO_CONTINUE",
					recipe_id="system.continue_current_task",
					extra=None,
				)
				return []
			if verb in meta_verbs:
				action_dict["target_id"] = str(self_id)
				target_id = str(self_id)
			result = interaction_engine.process_command(ws, self_id, action_dict)
			status = str((result or {}).get("status", "") or "")
			if status != "success":
				reason_code = str((result or {}).get("reason", "") or "")
				mismatch_reasons = (result or {}).get("mismatch_reasons", []) or []
				logger.warn(
					"interaction",
					"command_failed",
					context={
						"self_id": self_id,
						"verb": verb,
						"target_id": target_id,
						"reason": reason_code,
						"mismatch_reasons": list(mismatch_reasons) if isinstance(mismatch_reasons, list) else [],
						"action": dict(action_dict),
					},
				)
				extra: dict[str, Any] = {}
				if isinstance(mismatch_reasons, list) and mismatch_reasons:
					extra["mismatch_reasons"] = [dict(x) for x in mismatch_reasons if isinstance(x, dict)]
				ws.record_interaction_attempt(
					actor_id=self_id,
					verb=verb,
					target_id=target_id,
					status="failed",
					reason=reason_code,
					recipe_id="",
					extra=extra if extra else None,
				)
				return []
			ctx = (result or {}).get("context", {}) or {}
			effective_target_id = str((ctx or {}).get("target_id", "") or target_id)
			recipe_id = str(((ctx or {}).get("recipe", {}) or {}).get("id", "") or "")
			extra = {}
			if isinstance(ctx, dict) and isinstance(ctx.get("interaction_extra", None), dict):
				extra = dict(ctx.get("interaction_extra") or {})
			target_name_snapshot = ""
			target_ent_before = ws.get_entity_by_id(effective_target_id) if hasattr(ws, "get_entity_by_id") else None
			if target_ent_before is not None:
				target_name_snapshot = str(getattr(target_ent_before, "entity_name", "") or "")
				if hasattr(target_ent_before, "get_component"):
					target_setting = target_ent_before.get_component("AgentSetting")
					if target_setting is not None:
						target_name_snapshot = str(getattr(target_setting, "agent_name", "") or target_name_snapshot)
			if target_name_snapshot and not str(extra.get("target_name", "") or "").strip():
				extra["target_name"] = target_name_snapshot
			effect_failed = False
			effect_fail_reason = ""
			for eff in (result or {}).get("effects", []) or []:
				if isinstance(eff, dict) and isinstance(ctx, dict):
					evs = execute(eff, ctx)
					for ev in list(evs or []):
						if not isinstance(ev, dict):
							continue
						ev_type = str(ev.get("type", "") or "")
						if ev_type in {"ExecutorError", "BindError"}:
							effect_failed = True
							effect_fail_reason = str(ev.get("message", "") or ev_type)
							break
					if effect_failed:
						break
			if effect_failed:
				logger.warn(
					"interaction",
					"command_effect_failed",
					context={
						"self_id": self_id,
						"verb": verb,
						"target_id": effective_target_id,
						"recipe_id": recipe_id,
						"reason": effect_fail_reason,
						"action": dict(action_dict),
					},
				)
				ws.record_interaction_attempt(
					actor_id=self_id,
					verb=verb,
					target_id=effective_target_id,
					status="failed",
					reason=effect_fail_reason,
					recipe_id=recipe_id,
					extra=extra,
				)
				return []
			ws.record_interaction_attempt(
				actor_id=self_id,
				verb=verb,
				target_id=effective_target_id,
				status="success",
				reason="",
				recipe_id=recipe_id,
				extra=extra,
			)
			worker_after = agent.get_component("WorkerComponent")
			if worker_after is not None and bool(getattr(worker_after, "current_task_id", "")):
				return []
			actions_executed += 1
			if actions_executed >= max_actions_in_tick:
				return []
	return []


def execute_worker_tick(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	logger = get_logger()
	self_id = str(
		data.get("entity_id")
		or (context or {}).get("entity_id", "")
		or (context or {}).get("event_entity_id", "")
		or ""
	)
	if not self_id:
		return []
	agent = ws.get_entity_by_id(self_id)
	if agent is None:
		return []
	worker = agent.get_component("WorkerComponent")
	if not isinstance(worker, WorkerComponent):
		return []
	if not bool(getattr(worker, "current_task_id", "") or ""):
		return []
	task = ws.get_task_by_id(worker.current_task_id)
	if task is None:
		worker.stop_task()
		return []
	from ..progressors import get_progressor
	ticks = int(data.get("ticks"))
	pid = str(getattr(task, "progressor_id", "") or "Linear")
	progressor = get_progressor(pid)
	delta = float(progressor.compute_progress_delta(ws, self_id, task, ticks))
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	execute(
		{
			"effect": "ProgressTask",
			"task_id": task.task_id,
			"delta": delta,
		},
		{"self_id": self_id, "task_id": task.task_id},
	)
	logger.debug(
		"task",
		"progress",
		context={
			"tick": int(getattr(ws.game_time, "total_ticks", 0) or 0),
			"self_id": self_id,
			"task_id": str(task.task_id),
			"task_type": str(task.task_type),
			"progress": float(getattr(task, "progress", 0.0) or 0.0),
			"required_progress": float(getattr(task, "required_progress", 0.0) or 0.0),
			"delta": float(delta),
		},
	)
	for eff in list(getattr(task, "tick_effects", []) or []):
		if isinstance(eff, dict):
			execute(
				eff,
				{"self_id": self_id, "task_id": task.task_id, "target_id": task.target_entity_id},
			)
	if task.is_complete():
		finish_events = execute(
			{"effect": "FinishTask"},
			{"self_id": self_id, "task_id": task.task_id, "target_id": task.target_entity_id},
		)
		for ev in list(finish_events or []):
			if not isinstance(ev, dict):
				continue
			ev_type = str(ev.get("type", "") or "")
			if ev_type in {"ExecutorError", "BindError"}:
				logger.warn(
					"task",
					"finish_failed",
					context={"self_id": self_id, "task_id": str(task.task_id), "error_event": dict(ev)},
				)
				break
		worker.stop_task()
	return []


def execute_apply_meta_action(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "ApplyMetaAction: target missing"}]
	action_type = str(data.get("action_type", "") or "").strip()
	params = data.get("params", {}) or {}
	if not isinstance(params, dict):
		params = {}
	if action_type == "SwitchInterruptPreset":
		arb = target.get_component("DecisionArbiterComponent")
		if not isinstance(arb, DecisionArbiterComponent):
			return [{"type": "ExecutorError", "message": "ApplyMetaAction: DecisionArbiterComponent missing"}]
		preset_id = str(params.get("preset_id", "") or "").strip()
		if not preset_id:
			return [{"type": "ExecutorError", "message": "ApplyMetaAction: missing preset_id"}]
		if preset_id not in (arb.interrupt_presets or {}):
			return [{"type": "ExecutorError", "message": f"ApplyMetaAction: unknown preset_id: {preset_id}"}]
		old = str(arb.active_interrupt_preset_id or "")
		arb.active_interrupt_preset_id = preset_id
		return [
			{
				"type": "MetaActionApplied",
				"entity_id": target.entity_id,
				"action_type": action_type,
				"params": {"preset_id": preset_id},
				"changed": {"active_interrupt_preset_id": {"from": old, "to": preset_id}},
			}
		]
	if action_type == "UpdateInterruptRuleParam":
		arb = target.get_component("DecisionArbiterComponent")
		if not isinstance(arb, DecisionArbiterComponent):
			return [{"type": "ExecutorError", "message": "ApplyMetaAction: DecisionArbiterComponent missing"}]
		preset_id = str(params.get("preset_id", "") or "").strip()
		rule_type = str(params.get("rule_type", "") or "").strip()
		key = str(params.get("key", "") or "").strip()
		value = params.get("value", None)
		if not preset_id or not rule_type or not key:
			return [{"type": "ExecutorError", "message": "ApplyMetaAction: UpdateInterruptRuleParam requires preset_id/rule_type/key/value"}]
		preset = (arb.interrupt_presets or {}).get(preset_id, None)
		if not isinstance(preset, dict):
			return [{"type": "ExecutorError", "message": f"ApplyMetaAction: unknown preset_id: {preset_id}"}]
		rule_params = preset.get(rule_type, None)
		if not isinstance(rule_params, dict):
			return [{"type": "ExecutorError", "message": f"ApplyMetaAction: rule not found in preset: {rule_type}"}]
		old_val = rule_params.get(key, None)
		rule_params[key] = value
		preset[rule_type] = rule_params
		arb.interrupt_presets[preset_id] = preset
		return [
			{
				"type": "MetaActionApplied",
				"entity_id": target.entity_id,
				"action_type": action_type,
				"params": {"preset_id": preset_id, "rule_type": rule_type, "key": key, "value": value},
				"changed": {"interrupt_presets": {"preset_id": preset_id, "rule_type": rule_type, "key": key, "from": old_val, "to": value}},
			}
		]
	return [{"type": "ExecutorError", "message": f"ApplyMetaAction: unknown action_type: {action_type}"}]


def execute_attach_details(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	import json
	def _safe(v: Any, depth: int = 0) -> Any:
		if depth > 4:
			return str(v)
		if v is None or isinstance(v, (str, int, float, bool)):
			return v
		if isinstance(v, list):
			return [_safe(x, depth + 1) for x in v]
		if isinstance(v, dict):
			return {str(k): _safe(val, depth + 1) for k, val in v.items()}
		d = getattr(v, "__dict__", None)
		if isinstance(d, dict):
			return {str(k): _safe(val, depth + 1) for k, val in d.items()}
		return str(v)
	detail_type = str((data or {}).get("detail_type", "") or "").strip().lower()
	if detail_type == "interrupt_preset":
		self_id = str((context or {}).get("self_id", "") or "")
		agent = ws.get_entity_by_id(self_id) if self_id else None
		arb = agent.get_component("DecisionArbiterComponent") if agent is not None else None
		if not isinstance(arb, DecisionArbiterComponent):
			return [{"type": "ExecutorError", "message": "AttachDetails: DecisionArbiterComponent missing"}]
		preset_id = str((data or {}).get("preset_id", "") or "").strip()
		presets = arb.interrupt_presets or {}
		descs = getattr(arb, "interrupt_preset_descriptions", {}) or {}
		if preset_id:
			selected = {preset_id: presets.get(preset_id)} if preset_id in presets else {}
		else:
			selected = dict(presets)
		lines: list[str] = []
		for pid in sorted(selected.keys()):
			desc = str(descs.get(pid, "") or "")
			lines.append(f"Preset {pid}: {desc}".strip())
		details = {"descriptions": dict(descs), "presets": selected}
		details_text = "\n".join([x for x in lines if x] + ["", json.dumps(details, ensure_ascii=False, indent=2)])
		log = getattr(ws, "interaction_log", None)
		if not isinstance(log, list) or not log:
			return [{"type": "ExecutorError", "message": "AttachDetails: interaction_log missing"}]
		last = log[-1]
		if isinstance(last, dict):
			last["details_text"] = details_text
			last["private_to_actor"] = True
		return []
	if detail_type != "entity":
		return [{"type": "ExecutorError", "message": f"AttachDetails: unknown detail_type: {detail_type}"}]
	target_ref = str((data or {}).get("target", (context or {}).get("target_id", "target")) or "target")
	target = resolve_entity(ws, target_ref, context or {}, allow_literal=True)
	if target is None:
		return [{"type": "ExecutorError", "message": "AttachDetails: target missing"}]
	payload = {
		"entity_id": str(getattr(target, "entity_id", "") or ""),
		"template_id": str(getattr(target, "template_id", "") or ""),
		"name": str(getattr(target, "entity_name", "") or ""),
		"tags": list(target.get_all_tags()) if hasattr(target, "get_all_tags") else [],
		"components": {},
	}
	comps = getattr(target, "components", {}) or {}
	if isinstance(comps, dict):
		for cname, comp in comps.items():
			payload["components"][str(cname)] = _safe(comp)
	log = getattr(ws, "interaction_log", None)
	if isinstance(log, list) and log:
		last = log[-1]
		if isinstance(last, dict):
			last["details_text"] = json.dumps(payload, ensure_ascii=False, indent=2)
			last["private_to_actor"] = True
	return [{"type": "DetailsAttached", "detail_type": "entity", "entity_id": payload["entity_id"]}]
