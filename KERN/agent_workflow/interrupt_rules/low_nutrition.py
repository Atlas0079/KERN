from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.components import CreatureComponent
from .base import InterruptResult


@dataclass
class LowNutritionRule:
	priority: int = 10
	nutrition_threshold: float = 30.0

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		agent = ws.get_entity_by_id(agent_id)
		if not agent:
			return InterruptResult(False)
		cc = agent.get_component("CreatureComponent")
		if not isinstance(cc, CreatureComponent):
			return InterruptResult(False)
		ensure = getattr(cc, "ensure_initialized", None)
		if callable(ensure):
			ensure()
		cur = getattr(cc, "current_nutrition", None)
		if cur is None:
			return InterruptResult(False)
		cur = float(cur)
		if cur < float(self.nutrition_threshold):
			return InterruptResult(
				interrupt=True,
				reason=f"low_nutrition:{cur:g}",
				rule_type="LowNutrition",
				priority=self.priority,
				data={"nutrition": cur, "threshold": float(self.nutrition_threshold)},
			)
		return InterruptResult(False)
