from __future__ import annotations

from dataclasses import dataclass

from .base import InterruptResult
from ...models.components import CreatureComponent


@dataclass
class LowNutritionRule:
	"""
	Align with Godot `RuleLowNutrition.gd`: Trigger interrupt when nutrition is below threshold.
	"""

	priority: int = 10
	threshold: float = 50.0

	def should_interrupt(self, ws: object, agent_id: str) -> InterruptResult:
		agent = ws.get_entity_by_id(agent_id)
		if agent is None:
			return InterruptResult(interrupt=False, rule_type="LowNutrition", priority=self.priority)

		arb = agent.get_component("DecisionArbiterComponent")
		params = arb.get_active_interrupt_rule_params("LowNutrition") if arb is not None and hasattr(arb, "get_active_interrupt_rule_params") else {}
		if params and not bool(params.get("enabled", True)):
			return InterruptResult(interrupt=False, rule_type="LowNutrition", priority=self.priority)

		creature = agent.get_component("CreatureComponent")
		if not isinstance(creature, CreatureComponent):
			return InterruptResult(interrupt=False, rule_type="LowNutrition", priority=self.priority)

		creature.ensure_initialized()
		if creature.current_nutrition is None:
			return InterruptResult(interrupt=False, rule_type="LowNutrition", priority=self.priority)

		threshold_raw = params.get("threshold", self.threshold) if isinstance(params, dict) else self.threshold
		try:
			threshold_raw = float(threshold_raw)
		except Exception:
			threshold_raw = float(self.threshold)

		max_nutrition = float(getattr(creature, "max_nutrition", 100.0) or 100.0)
		threshold_value = threshold_raw * max_nutrition if 0 < threshold_raw <= 1.0 else threshold_raw
		cur = float(creature.current_nutrition)

		if cur < float(threshold_value):
			return InterruptResult(
				interrupt=True,
				reason=f"Low nutrition ({cur:.1f} < {float(threshold_value):.1f})",
				rule_type="LowNutrition",
				priority=self.priority,
				data={
					"current_nutrition": cur,
					"threshold": float(threshold_raw),
					"threshold_value": float(threshold_value),
					"preset_id": str(getattr(arb, "active_interrupt_preset_id", "") or "") if arb is not None else "",
				},
			)

		return InterruptResult(interrupt=False, rule_type="LowNutrition", priority=self.priority)
