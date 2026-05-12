from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.components import CreatureComponent, DecisionArbiterComponent
from ..full_ws_view_builder import build_full_ws_view
from ..observer import build_agent_perception
from .base import InterruptResult


@dataclass
class CorpseSightedRule:
	priority: int = 5
	trigger_on_new_corpse: bool = True
	cooldown_ticks: int = 0
	eps: float = 1e-9

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		agent = ws.get_entity_by_id(agent_id)
		if not agent:
			return InterruptResult(False)

		cc = agent.get_component("CreatureComponent")
		if not isinstance(cc, CreatureComponent):
			return InterruptResult(False)

		arb = agent.get_component("DecisionArbiterComponent")
		params = arb.get_active_interrupt_rule_params("CorpseSighted") if isinstance(arb, DecisionArbiterComponent) else {}
		if params and not bool(params.get("enabled", True)):
			if isinstance(arb, DecisionArbiterComponent) and isinstance(getattr(arb, "interrupt_runtime_state", None), dict):
				getattr(arb, "interrupt_runtime_state").pop("CorpseSighted", None)
			return InterruptResult(False)
		rt = arb.get_rule_runtime("CorpseSighted") if isinstance(arb, DecisionArbiterComponent) else {}
		now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		if isinstance(params, dict) and not bool(params.get("trigger_on_new_corpse", self.trigger_on_new_corpse)):
			return InterruptResult(False)
		cooldown_ticks = int(params.get("cooldown_ticks", self.cooldown_ticks) if isinstance(params, dict) else self.cooldown_ticks)
		last_tick = int(rt.get("last_interrupt_tick", -10**9) or -10**9)
		if cooldown_ticks > 0 and now_tick - last_tick < cooldown_ticks:
			return InterruptResult(False)

		ws_view = build_full_ws_view(ws, agent_id, "corpse_sighted", {})
		perception = build_agent_perception(ws_view, agent_id)
		visible = perception.get("entities", []) or []

		for item in visible:
			ent = dict(item or {}) if isinstance(item, dict) else {}
			eid = str(ent.get("id", "")).strip()
			if not eid:
				continue
			tags = {str(x) for x in list(ent.get("tags", []) or [])}
			if not ({"corpse", "dead_body"} & tags):
				continue
			if isinstance(rt, dict):
				rt["last_interrupt_tick"] = now_tick
			return InterruptResult(
				interrupt=True,
				reason=f"corpse_sighted:{eid}",
				rule_type="CorpseSighted",
				priority=self.priority,
				data={"corpse_id": eid},
			)

		return InterruptResult(False)
