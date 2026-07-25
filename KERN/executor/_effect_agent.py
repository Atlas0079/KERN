from __future__ import annotations

from typing import Any

from ..execution_errors import executor_error
from ..log_manager import get_logger
from ..models.components import DecisionArbiterComponent, WorkerComponent
from ._effect_binder import _base_bind, _require_dict, _require_int, _require_str, _resolve_param_token


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


def execute_worker_tick(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
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
	events = executor.execute_bundle(
		ws,
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
		tick_events = executor.execute_bundle(
			ws,
			tick_bundle.to_dict(),
			{
				"self_id": self_id,
				"task_id": task.task_id,
				"target_id": task.target_entity_id,
				"_interaction_origin": "task_lifecycle",
			},
		)
		events.extend(tick_events)
	if task.is_complete():
		finish_events = executor.execute_bundle(
			ws,
			{"effects": [{"effect": "FinishTask"}]},
			{"self_id": self_id, "task_id": task.task_id, "target_id": task.target_entity_id},
		)
		events.extend(finish_events)
		worker.stop_task()
	return events


def execute_apply_meta_action(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return executor_error("ApplyMetaAction: target missing")
	action_type = str(data.get("action_type", "") or "").strip()
	params = data.get("params", {}) or {}
	if not isinstance(params, dict):
		params = {}
	if action_type == "SwitchInterruptPreset":
		arb = target.get_component("DecisionArbiterComponent")
		if not isinstance(arb, DecisionArbiterComponent):
			return executor_error("ApplyMetaAction: DecisionArbiterComponent missing")
		# TODO: this API exposes preset switching directly to agents.
		# That works, but it leaks internal configuration concepts into agent actions.
		# Future design should prefer higher-level intent actions such as changing alertness,
		# task focus, or threat sensitivity, then map those intents to arbiter configuration.
		preset_id = str(params.get("preset_id", "") or "").strip()
		if not preset_id:
			return executor_error("ApplyMetaAction: missing preset_id")
		if preset_id not in (arb.interrupt_presets or {}):
			return executor_error(f"ApplyMetaAction: unknown preset_id: {preset_id}")
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
	return executor_error(f"ApplyMetaAction: unknown action_type: {action_type}")
