from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.components import AgentWakePolicyComponent
from ..full_ws_view_builder import build_full_ws_view
from ..observer import build_agent_perception
from .base import InterruptResult


@dataclass
class PerceptionChangeRule:
	priority: int = 15
	cooldown_ticks: int = 2
	trigger_on_agent_sighted: bool = True
	trigger_on_agent_left: bool = True
	eps: float = 1e-9

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		agent = ws.get_entity_by_id(agent_id)
		if not agent:
			return InterruptResult(False)

		wake_policy = agent.get_component("AgentWakePolicyComponent")
		if not isinstance(wake_policy, AgentWakePolicyComponent):
			return InterruptResult(False)

		params = wake_policy.get_active_interrupt_rule_params("PerceptionChange")
		if params and not bool(params.get("enabled", True)):
			if isinstance(getattr(wake_policy, "interrupt_runtime_state", None), dict):
				getattr(wake_policy, "interrupt_runtime_state").pop("PerceptionChange", None)
			return InterruptResult(False)

		now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		rt = wake_policy.get_rule_runtime("PerceptionChange")
		last_tick = int(rt.get("last_interrupt_tick", -10**9))
		cooldown_ticks = int(params.get("cooldown_ticks", self.cooldown_ticks) if isinstance(params, dict) else self.cooldown_ticks)
		if now_tick - last_tick < int(cooldown_ticks):
			return InterruptResult(False)

		ws_view = build_full_ws_view(ws, agent_id, "perception_change", {})
		perception = build_agent_perception(ws_view, agent_id)
		visible = perception.get("entities", []) or []

		cur_sig_items: list[str] = []
		for item in visible:
			ent = dict(item or {}) if isinstance(item, dict) else {}
			eid = str(ent.get("id", "")).strip()
			if not eid:
				continue
			tags = ",".join(sorted(str(x) for x in list(ent.get("tags", []) or [])))
			statuses = ",".join(sorted(str(x) for x in list(ent.get("statuses", []) or [])))
			contained_in = str(ent.get("contained_in", "") or "")
			cur_sig_items.append(f"{eid}|tags:{tags}|statuses:{statuses}|in:{contained_in}")
		cur_sig_items.sort()
		cur_sig = "|".join(cur_sig_items)

		prev_sig = str(rt.get("last_signature", ""))
		if not prev_sig:
			rt["last_signature"] = cur_sig
			return InterruptResult(False)

		if cur_sig != prev_sig:
			prev_ids = {x.split("|", 1)[0] for x in prev_sig.split("|") if x}
			cur_ids = {x.split("|", 1)[0] for x in cur_sig.split("|") if x}
			appeared = sorted(cur_ids - prev_ids)
			left = sorted(prev_ids - cur_ids)
			trigger_on_agent_sighted = bool(params.get("trigger_on_agent_sighted", self.trigger_on_agent_sighted)) if isinstance(params, dict) else bool(self.trigger_on_agent_sighted)
			trigger_on_agent_left = bool(params.get("trigger_on_agent_left", self.trigger_on_agent_left)) if isinstance(params, dict) else bool(self.trigger_on_agent_left)
			rt["last_signature"] = cur_sig
			should_fire = (not appeared and not left) or (bool(appeared) and trigger_on_agent_sighted) or (bool(left) and trigger_on_agent_left)
			if not should_fire:
				return InterruptResult(False)
			rt["last_interrupt_tick"] = now_tick
			return InterruptResult(
				interrupt=True,
				reason="perception_changed",
				rule_type="PerceptionChange",
				priority=self.priority,
				data={"visible_count": len(cur_sig_items), "appeared": appeared, "left": left},
			)

		return InterruptResult(False)
