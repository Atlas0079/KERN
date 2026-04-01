from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...sim.interrupt_rules import CorpseSightedRule, IdleRule, LowNutritionRule, PerceptionChangeRule, InterruptResult
from .controller_resolver import resolve_enabled_controller_component


@dataclass
class DecisionArbiterComponent:
	"""
	Align with Godot `DecisionArbiterComponent.gd`:
	- Holds ruleset
	- Calls `check_if_interrupt_is_needed` every tick
	"""
	# TODO: interrupt preference modeling is currently too low-level:
	# presets, mutable rule params, and runtime latch/cooldown state live side by side here.
	# Future refactor should separate:
	# 1) preset library,
	# 2) active runtime overrides,
	# 3) internal runtime state used only by the arbiter.

	ruleset: list[Any] = field(default_factory=list)
	active_interrupt_preset_id: str = ""
	interrupt_presets: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
	interrupt_preset_descriptions: dict[str, str] = field(default_factory=dict)
	interrupt_runtime_state: dict[str, dict[str, Any]] = field(default_factory=dict)
	_runtime_preset_id: str = ""

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		# Arbiter component usually doesn't need progression, read-only check suffices.
		return

	def get_active_interrupt_rule_params(self, rule_type: str) -> dict[str, Any]:
		preset_id = str(self.active_interrupt_preset_id or "").strip()
		if not preset_id:
			return {}
		preset = (self.interrupt_presets or {}).get(preset_id, {})
		if not isinstance(preset, dict):
			return {}
		params = preset.get(str(rule_type), {})
		return dict(params) if isinstance(params, dict) else {}

	def _get_now_tick(self, ws: Any) -> int:
		return int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)

	def _reset_interrupt_runtime(self) -> None:
		self.interrupt_runtime_state = {}

	def _ensure_runtime_preset_tracking(self) -> None:
		pid = str(self.active_interrupt_preset_id or "")
		if pid != str(self._runtime_preset_id or ""):
			# TODO: switching preset currently resets runtime trigger state as a side effect.
			# If we later separate preference state from runtime state, revisit whether this reset
			# should still happen, and on which transitions it is actually desired.
			self._runtime_preset_id = pid
			self._reset_interrupt_runtime()

	def _get_rule_runtime(self, rule_type: str) -> dict[str, Any]:
		rt = (self.interrupt_runtime_state or {}).get(rule_type, None)
		if not isinstance(rt, dict):
			rt = {"latched": False, "last_fire_tick": -10**18}
			self.interrupt_runtime_state[str(rule_type)] = rt
		rt.setdefault("latched", False)
		rt.setdefault("last_fire_tick", -10**18)
		return rt

	def _get_creature_nutrition(self, ws: Any, agent_id: str) -> tuple[float | None, float | None]:
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

	def _normalize_threshold_value(self, raw: Any, max_nutrition: float | None) -> float | None:
		try:
			v = float(raw)
		except Exception:
			return None
		if max_nutrition is None:
			return v
		if 0 < v <= 1.0:
			return float(v) * float(max_nutrition)
		return v

	def _check_low_nutrition_with_latch(self, ws: Any, agent_id: str, rule: LowNutritionRule) -> InterruptResult:
		params = self.get_active_interrupt_rule_params("LowNutrition")
		if params and not bool(params.get("enabled", True)):
			if isinstance(self.interrupt_runtime_state, dict):
				self.interrupt_runtime_state.pop("LowNutrition", None)
			return InterruptResult(interrupt=False, reason="", rule_type="LowNutrition", priority=int(getattr(rule, "priority", 10)))

		rt = self._get_rule_runtime("LowNutrition")
		now_tick = self._get_now_tick(ws)

		cur, max_nut = self._get_creature_nutrition(ws, agent_id)
		threshold_on_raw = params.get("threshold_on", params.get("threshold", getattr(rule, "threshold", 50.0))) if isinstance(params, dict) else getattr(rule, "threshold", 50.0)
		threshold_off_raw = params.get("threshold_off", threshold_on_raw) if isinstance(params, dict) else threshold_on_raw
		threshold_off_val = self._normalize_threshold_value(threshold_off_raw, max_nut)

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

	@staticmethod
	def from_template_data(component_data: dict[str, Any]) -> "DecisionArbiterComponent":
		rules_raw = component_data.get("rules", []) if isinstance(component_data, dict) else []
		ruleset: list[Any] = []

		for rd in rules_raw:
			rule_type = (rd or {}).get("type")
			if rule_type == "Idle":
				ruleset.append(IdleRule(priority=int((rd or {}).get("priority", 999))))
			elif rule_type == "LowNutrition":
				ruleset.append(
					LowNutritionRule(
						priority=int((rd or {}).get("priority", 10)),
						threshold=float((rd or {}).get("threshold", 50)),
					)
				)
			elif rule_type == "PerceptionChange":
				ruleset.append(
					PerceptionChangeRule(
						priority=int((rd or {}).get("priority", 50)),
						trigger_on_agent_sighted=bool((rd or {}).get("trigger_on_agent_sighted", True)),
						trigger_on_agent_left=bool((rd or {}).get("trigger_on_agent_left", True)),
					)
				)
			elif rule_type == "CorpseSighted":
				ruleset.append(
					CorpseSightedRule(
						priority=int((rd or {}).get("priority", 30)),
						trigger_on_new_corpse=bool((rd or {}).get("trigger_on_new_corpse", True)),
					)
				)
			else:
				# Unmigrated rules: Ignore
				# Assuming existence: UnknownInterruptRule
				# Intent: Keep unknown rule data for debugging; Necessity: Facilitates gradual migration as rule types increase.
				continue

		# Check lower priority first (consistent with your Godot version)
		ruleset.sort(key=lambda r: int(getattr(r, "priority", 999999)))
		active_interrupt_preset_id = str((component_data or {}).get("active_interrupt_preset_id", "") or "")
		interrupt_presets = (component_data or {}).get("interrupt_presets", {}) or {}
		interrupt_preset_descriptions = (component_data or {}).get("interrupt_preset_descriptions", {}) or {}
		if not isinstance(interrupt_presets, dict):
			interrupt_presets = {}
		if not isinstance(interrupt_preset_descriptions, dict):
			interrupt_preset_descriptions = {}
		return DecisionArbiterComponent(
			ruleset=ruleset,
			active_interrupt_preset_id=active_interrupt_preset_id,
			interrupt_presets=dict(interrupt_presets),
			interrupt_preset_descriptions={str(k): str(v or "") for k, v in dict(interrupt_preset_descriptions).items()},
		)

	def check_if_interrupt_is_needed(self, ws: Any, agent_id: str) -> InterruptResult:
		self._ensure_runtime_preset_tracking()

		# If the entity has no "available controller", do not enter decision (avoid hardcoding control methods in Manager/Arbiter).
		agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
		_ctrl_name, ctrl = resolve_enabled_controller_component(agent)
		if ctrl is None:
			return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
		worker = agent.get_component("WorkerComponent") if agent is not None else None
		has_task = bool(getattr(worker, "current_task_id", "") or "") if worker is not None else False

		for rule in self.ruleset:
			if has_task and isinstance(rule, IdleRule):
				continue
			if isinstance(rule, LowNutritionRule):
				result = self._check_low_nutrition_with_latch(ws, agent_id, rule)
			else:
				result = rule.should_interrupt(ws, agent_id)
			if result.interrupt:
				return result
		return InterruptResult(interrupt=False, reason="", rule_type="", priority=999999)
