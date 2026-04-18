from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...sim.interrupt_rules import CorpseSightedRule, IdleRule, LowNutritionRule, PerceptionChangeRule, InterruptResult
from ...agent_workflow.interrupt_runtime import check_if_interrupt_is_needed as check_interrupt_in_workflow


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

	def _get_rule_runtime(self, rule_type: str) -> dict[str, Any]:
		rt = (self.interrupt_runtime_state or {}).get(rule_type, None)
		if not isinstance(rt, dict):
			rt = {"latched": False, "last_fire_tick": -10**18}
			self.interrupt_runtime_state[str(rule_type)] = rt
		rt.setdefault("latched", False)
		rt.setdefault("last_fire_tick", -10**18)
		return rt

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
		return check_interrupt_in_workflow(ws=ws, agent_id=str(agent_id or ""), arb=self)
