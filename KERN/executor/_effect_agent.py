from __future__ import annotations

from typing import Any

from ..execution_errors import is_execution_error_event
from ..log_manager import get_logger
from ..entity_ref_resolver import resolve_entity
from ..models.components import DecisionArbiterComponent, WorkerComponent
from ..agent_workflow.runtime import run_agent_control_tick
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
	if detail_type not in {"entity", "entity_recipe", "interrupt_preset"}:
		raise BindError(effect_type, ["detail_type"])
	out: dict[str, Any] = {"effect": effect_type, "detail_type": detail_type}
	if detail_type in {"entity", "entity_recipe"}:
		out["target"] = _require_str(params, effect_type, "target")
		return out, ctx
	preset_id = str(_resolve_param_token(params.get("preset_id", ""), ctx) or "").strip()
	if preset_id:
		out["preset_id"] = preset_id
	return out, ctx


def execute_agent_control_tick(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
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
	services = getattr(ws, "services", {}) or {}
	default_provider = services.get("default_action_provider")
	action_providers = services.get("action_providers", {}) or {}
	provider_id = str(getattr(ctrl, "provider_id", "") or "").strip()
	workflow = action_providers.get(provider_id) if provider_id and provider_id in action_providers else default_provider
	if workflow is None or not hasattr(workflow, "decide"):
		return []
	max_actions_in_tick = max(1, int(data.get("max_actions_in_tick") or 1))
	run_agent_control_tick(ws=ws, actor_id=self_id, workflow=workflow, max_actions_in_tick=max_actions_in_tick)
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
			"effects": [
				{
					"effect": "ProgressTask",
					"task_id": task.task_id,
					"delta": delta,
				}
			]
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
	tick_bundle = getattr(task, "tick_bundle", None)
	if tick_bundle is not None:
		execute(
			tick_bundle.to_dict(),
			{"self_id": self_id, "task_id": task.task_id, "target_id": task.target_entity_id},
		)
	if task.is_complete():
		finish_events = execute(
			{"effects": [{"effect": "FinishTask"}]},
			{"self_id": self_id, "task_id": task.task_id, "target_id": task.target_entity_id},
		)
		for ev in list(finish_events or []):
			if is_execution_error_event(ev):
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
		# TODO: this API exposes preset switching directly to agents.
		# That works, but it leaks internal configuration concepts into agent actions.
		# Future design should prefer higher-level intent actions such as changing alertness,
		# task focus, or threat sensitivity, then map those intents to arbiter configuration.
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
	if detail_type not in {"entity", "entity_recipe"}:
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
		"observed_description": "",
		"recipe_description": "",
		"components": {},
	}
	comps = getattr(target, "components", {}) or {}
	if isinstance(comps, dict):
		for cname, comp in comps.items():
			if str(cname) == "DescriptionComponent":
				if hasattr(comp, "observed_text"):
					payload["observed_description"] = str(comp.observed_text() or "")
				else:
					payload["observed_description"] = str(getattr(comp, "observed_description", "") or getattr(comp, "description", "") or "")
				if hasattr(comp, "recipe_text"):
					payload["recipe_description"] = str(comp.recipe_text() or "")
				else:
					payload["recipe_description"] = str(getattr(comp, "recipe_description", "") or "")
			if detail_type == "entity":
				payload["components"][str(cname)] = _safe(comp)
	if detail_type == "entity_recipe":
		payload.pop("components", None)
		payload.pop("observed_description", None)
	log = getattr(ws, "interaction_log", None)
	if isinstance(log, list) and log:
		last = log[-1]
		if isinstance(last, dict):
			last["details_text"] = json.dumps(payload, ensure_ascii=False, indent=2)
			last["private_to_actor"] = True
	return [{"type": "DetailsAttached", "detail_type": detail_type, "entity_id": payload["entity_id"]}]
