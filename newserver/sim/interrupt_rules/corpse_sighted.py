from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...agent_workflow.full_ws_view_builder import build_full_ws_view
from ...agent_workflow.observer import build_agent_perception
from .base import InterruptResult


@dataclass
class CorpseSightedRule:
	priority: int = 40
	trigger_on_new_corpse: bool = True

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
		if agent is None:
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		arb = agent.get_component("DecisionArbiterComponent")
		if arb is None:
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		params = arb.get_active_interrupt_rule_params("CorpseSighted")
		if params and not bool(params.get("enabled", True)):
			if isinstance(arb.interrupt_runtime_state, dict):
				arb.interrupt_runtime_state.pop("CorpseSighted", None)
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		on_new = bool(self.trigger_on_new_corpse)
		cooldown_ticks = 0
		if isinstance(params, dict):
			if "trigger_on_new_corpse" in params:
				on_new = bool(params.get("trigger_on_new_corpse", on_new))
			try:
				cooldown_ticks = int(params.get("cooldown_ticks", 0) or 0)
			except Exception:
				cooldown_ticks = 0
		perception = build_agent_perception(build_full_ws_view(ws, agent_id, "", {}), agent_id)
		if not (perception or {}).get("location"):
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		entities = list((perception or {}).get("entities", []) or [])
		corpse_ids: set[str] = set()
		corpse_labels: list[str] = []
		for item in entities:
			if not isinstance(item, dict):
				continue
			tags = [str(x) for x in list(item.get("tags", []) or [])]
			if "corpse" not in tags and "dead_body" not in tags:
				continue
			eid = str(item.get("id", "") or "")
			if not eid:
				continue
			corpse_ids.add(eid)
			name = str(item.get("name", "") or eid)
			corpse_labels.append(f"{name} ({eid})")
		if not corpse_ids:
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		rt = arb._get_rule_runtime("CorpseSighted")
		last_seen = set([str(x) for x in list(rt.get("seen_corpse_ids", []) or [])])
		new_ids = sorted(list(corpse_ids - last_seen))
		rt["seen_corpse_ids"] = sorted(list(corpse_ids))
		now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		last_fire = int(rt.get("last_fire_tick", -10**18) or -10**18)
		if cooldown_ticks > 0 and (now_tick - last_fire) < int(cooldown_ticks):
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		if on_new and not new_ids:
			return InterruptResult(interrupt=False, reason="", rule_type="CorpseSighted", priority=self.priority)
		rt["last_fire_tick"] = int(now_tick)
		reason = "发现尸体: " + ", ".join(corpse_labels[:3])
		return InterruptResult(
			interrupt=True,
			reason=reason,
			rule_type="CorpseSighted",
			priority=self.priority,
			data={"corpse_ids": sorted(list(corpse_ids)), "new_corpse_ids": new_ids},
		)
