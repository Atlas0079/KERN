from __future__ import annotations

from typing import Any

from ..sim.interrupt_rules import IdleRule, InterruptResult, LowNutritionRule
from ..models.components.controller_resolver import resolve_enabled_controller_component


def _get_now_tick(ws: Any) -> int:
	return int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)


def _ensure_runtime_preset_tracking(arb: Any) -> None:
	pid = str(getattr(arb, "active_interrupt_preset_id", "") or "")
	last = str(getattr(arb, "_runtime_preset_id", "") or "")
	if pid == last:
		return
	setattr(arb, "_runtime_preset_id", pid)
	setattr(arb, "interrupt_runtime_state", {})


def _get_creature_nutrition(ws: Any, agent_id: str) -> tuple[float | None, float | None]:
	agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
	if agent is None:
		return (None, None)
	creature = agent.get_component("CreatureComponent")
	if creature is None:
		return (None, None)
	ensure = getattr(creature, "ensure_initialized", None)
	if callable(ensure):
		ensure()
	cur = getattr(creature, "current_nutrition", None)
	max_nut = getattr(creature, "max_nutrition", None)
	try:
		cur_f = float(cur) if cur is not None else None
	except Exception:
		cur_f = None
	try:
		max_f = float(max_nut) if max_nut is not None else None
	except Exception:
		max_f = None
	return (cur_f, max_f)


def _normalize_threshold_value(raw: Any, max_nutrition: float | None) -> float | None:
	try:
		v = float(raw)
	except Exception:
		return None
	if max_nutrition is None:
		return v
	if 0 < v <= 1.0:
		return float(v) * float(max_nutrition)
	return v


def _check_low_nutrition_with_latch(ws: Any, agent_id: str, arb: Any, rule: LowNutritionRule) -> InterruptResult:
	params = arb.get_active_interrupt_rule_params("LowNutrition") if hasattr(arb, "get_active_interrupt_rule_params") else {}
	if params and not bool(params.get("enabled", True)):
		if isinstance(getattr(arb, "interrupt_runtime_state", None), dict):
			getattr(arb, "interrupt_runtime_state").pop("LowNutrition", None)
		return InterruptResult(interrupt=False, reason="", rule_type="LowNutrition", priority=int(getattr(rule, "priority", 10)))

	rt = arb._get_rule_runtime("LowNutrition") if hasattr(arb, "_get_rule_runtime") else {}
	now_tick = _get_now_tick(ws)

	cur, max_nut = _get_creature_nutrition(ws, agent_id)
	threshold_on_raw = params.get("threshold_on", params.get("threshold", getattr(rule, "threshold", 50.0))) if isinstance(params, dict) else getattr(rule, "threshold", 50.0)
	threshold_off_raw = params.get("threshold_off", threshold_on_raw) if isinstance(params, dict) else threshold_on_raw
	threshold_off_val = _normalize_threshold_value(threshold_off_raw, max_nut)

	if bool(rt.get("latched", False)):
		if cur is not None and threshold_off_val is not None and float(cur) >= float(threshold_off_val):
			rt["latched"] = False
		return InterruptResult(interrupt=False, reason="", rule_type="LowNutrition", priority=int(getattr(rule, "priority", 10)))

	cooldown_ticks = 0
	if isinstance(params, dict):
		try:
			cooldown_ticks = int(params.get("cooldown_ticks", 0) or 0)
		except Exception:
			cooldown_ticks = 0

	last_fire = rt.get("last_fire_tick", -10**18)
	try:
		last_fire_i = int(last_fire)
	except Exception:
		last_fire_i = -10**18

	if cooldown_ticks > 0 and (int(now_tick) - int(last_fire_i)) < int(cooldown_ticks):
		return InterruptResult(interrupt=False, reason="", rule_type="LowNutrition", priority=int(getattr(rule, "priority", 10)))

	result = rule.should_interrupt(ws, agent_id)
	if bool(getattr(result, "interrupt", False)):
		rt["latched"] = True
		rt["last_fire_tick"] = int(now_tick)
	return result


def check_if_interrupt_is_needed(ws: Any, agent_id: str, arb: Any) -> InterruptResult:
	_ensure_runtime_preset_tracking(arb)
	agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
	_ctrl_name, ctrl = resolve_enabled_controller_component(agent)
	if ctrl is None:
		return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
	worker = agent.get_component("WorkerComponent") if agent is not None else None
	has_task = bool(getattr(worker, "current_task_id", "") or "") if worker is not None else False
	ruleset = list(getattr(arb, "ruleset", []) or [])
	for rule in list(ruleset):
		if has_task and isinstance(rule, IdleRule):
			continue
		if isinstance(rule, LowNutritionRule):
			result = _check_low_nutrition_with_latch(ws, agent_id, arb, rule)
		else:
			result = rule.should_interrupt(ws, agent_id)
		if bool(getattr(result, "interrupt", False)):
			return result
	return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
