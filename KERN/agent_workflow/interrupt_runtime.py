from __future__ import annotations

from typing import Any

from .interrupt_rules import (
	CorpseSightedRule,
	InterruptResult,
	LowNutritionRule,
	NoActiveTaskRule,
	PerceptionChangeRule,
)
from ..models.components.controller_resolver import resolve_enabled_controller_component


def _get_now_tick(ws: Any) -> int:
	return int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)


def _ensure_runtime_preset_tracking(wake_policy: Any) -> None:
	pid = str(getattr(wake_policy, "active_interrupt_preset_id", "") or "")
	last = str(getattr(wake_policy, "_runtime_preset_id", "") or "")
	if pid == last:
		return
	setattr(wake_policy, "_runtime_preset_id", pid)
	setattr(wake_policy, "interrupt_runtime_state", {})


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


def _check_low_nutrition_with_latch(ws: Any, agent_id: str, wake_policy: Any, rule: LowNutritionRule) -> InterruptResult:
	params = wake_policy.get_active_interrupt_rule_params("LowNutrition") if hasattr(wake_policy, "get_active_interrupt_rule_params") else {}
	if params and not bool(params.get("enabled", True)):
		if isinstance(getattr(wake_policy, "interrupt_runtime_state", None), dict):
			getattr(wake_policy, "interrupt_runtime_state").pop("LowNutrition", None)
		return InterruptResult(interrupt=False, reason="", rule_type="LowNutrition", priority=int(getattr(rule, "priority", 10)))

	rt = wake_policy._get_rule_runtime("LowNutrition") if hasattr(wake_policy, "_get_rule_runtime") else {}
	now_tick = _get_now_tick(ws)

	cur, max_nut = _get_creature_nutrition(ws, agent_id)
	default_threshold = getattr(rule, "nutrition_threshold", 30)
	threshold_on_raw = params.get("threshold_on", params.get("threshold", default_threshold)) if isinstance(params, dict) else default_threshold
	threshold_off_raw = params.get("threshold_off", threshold_on_raw) if isinstance(params, dict) else threshold_on_raw
	threshold_on_val = _normalize_threshold_value(threshold_on_raw, max_nut)
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

	active_rule = rule
	if threshold_on_val is not None:
		active_rule = LowNutritionRule(priority=int(getattr(rule, "priority", 10)), nutrition_threshold=float(threshold_on_val))
	result = active_rule.should_interrupt(ws, agent_id)
	if bool(getattr(result, "interrupt", False)):
		rt["latched"] = True
		rt["last_fire_tick"] = int(now_tick)
	return result


def _rule_from_data(rule_data: dict[str, Any]) -> Any | None:
	rule_type = str((rule_data or {}).get("type", "") or "").strip()
	priority_raw = (rule_data or {}).get("priority", 999999)
	try:
		priority = int(priority_raw)
	except Exception:
		priority = 999999
	if rule_type == "NoActiveTask":
		return NoActiveTaskRule(priority=priority)
	if rule_type == "LowNutrition":
		threshold_raw = (rule_data or {}).get("nutrition_threshold", (rule_data or {}).get("threshold", 30))
		try:
			threshold = float(threshold_raw)
		except Exception:
			threshold = 30.0
		return LowNutritionRule(priority=priority, nutrition_threshold=threshold)
	if rule_type == "PerceptionChange":
		cd_raw = (rule_data or {}).get("cooldown_ticks", 2)
		try:
			cooldown_ticks = int(cd_raw)
		except Exception:
			cooldown_ticks = 2
		return PerceptionChangeRule(
			priority=priority,
			cooldown_ticks=cooldown_ticks,
			trigger_on_agent_sighted=bool((rule_data or {}).get("trigger_on_agent_sighted", True)),
			trigger_on_agent_left=bool((rule_data or {}).get("trigger_on_agent_left", True)),
		)
	if rule_type == "CorpseSighted":
		cd_raw = (rule_data or {}).get("cooldown_ticks", 0)
		try:
			cooldown_ticks = int(cd_raw)
		except Exception:
			cooldown_ticks = 0
		return CorpseSightedRule(
			priority=priority,
			trigger_on_new_corpse=bool((rule_data or {}).get("trigger_on_new_corpse", True)),
			cooldown_ticks=cooldown_ticks,
		)
	return None


def check_if_interrupt_is_needed(ws: Any, agent_id: str, wake_policy: Any) -> InterruptResult:
	_ensure_runtime_preset_tracking(wake_policy)
	agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
	_ctrl_name, ctrl = resolve_enabled_controller_component(agent)
	if ctrl is None:
		return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
	worker = agent.get_component("WorkerComponent") if agent is not None else None
	has_task = bool(getattr(worker, "current_task_id", "") or "") if worker is not None else False
	ruleset = list(getattr(wake_policy, "ruleset", []) or [])
	for item in list(ruleset):
		rule = item
		if isinstance(item, dict):
			rule = _rule_from_data(item)
		if rule is None:
			continue
		if has_task and isinstance(rule, NoActiveTaskRule):
			continue
		if isinstance(rule, LowNutritionRule):
			result = _check_low_nutrition_with_latch(ws, agent_id, wake_policy, rule)
		else:
			result = rule.should_interrupt(ws, agent_id)
		if bool(getattr(result, "interrupt", False)):
			return result
	return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
