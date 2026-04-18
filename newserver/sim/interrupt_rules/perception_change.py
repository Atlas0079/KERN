from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...agent_workflow.full_ws_view_builder import build_full_ws_view
from ...agent_workflow.observer import build_agent_perception
from .base import InterruptResult


@dataclass
class PerceptionChangeRule:
	"""
	Interrupts when the set of visible entities changes significantly (e.g. new agent sighted).
	
	Logic:
	- Maintains a "last known visible entity IDs" set in runtime state.
	- On each check, compares current visible entities with last known.
	- If a NEW entity (not in last known) appears, and it matches the filter (e.g. is an Agent), trigger interrupt.
	"""

	priority: int = 50
	trigger_on_agent_sighted: bool = True
	trigger_on_agent_left: bool = True

	def _recent_departure_destination(self, ws: Any, actor_id: str, source_location_id: str, now_tick: int) -> str:
		log = list(getattr(ws, "interaction_log", []) or [])
		for item in reversed(log):
			if not isinstance(item, dict):
				continue
			if int(item.get("tick", 0) or 0) < int(now_tick) - 3:
				break
			if str(item.get("actor_id", "") or "") != str(actor_id):
				continue
			if str(item.get("verb", "") or "") != "Travel":
				continue
			if str(item.get("status", "") or "") != "success":
				continue
			if str(item.get("location_id", "") or "") != str(source_location_id):
				continue
			to_name = str(item.get("to_location_name", "") or "")
			to_id = str(item.get("to_location_id", "") or "")
			if to_name:
				return to_name
			if to_id:
				loc = ws.get_location_by_id(to_id) if hasattr(ws, "get_location_by_id") else None
				if loc is not None:
					return str(getattr(loc, "location_name", "") or to_id)
				return to_id
		return ""

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		# 1. Get Arbiter and Runtime State
		agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
		if agent is None:
			return InterruptResult(interrupt=False, reason="", rule_type="PerceptionChange", priority=self.priority)
		
		arb = agent.get_component("DecisionArbiterComponent")
		if arb is None:
			return InterruptResult(interrupt=False, reason="", rule_type="PerceptionChange", priority=self.priority)
		
		# Check if rule is enabled in active preset
		params = arb.get_active_interrupt_rule_params("PerceptionChange")
		if params and not bool(params.get("enabled", True)):
			# Clear runtime state if disabled to avoid stale comparisons
			if isinstance(arb.interrupt_runtime_state, dict):
				arb.interrupt_runtime_state.pop("PerceptionChange", None)
			return InterruptResult(interrupt=False, reason="", rule_type="PerceptionChange", priority=self.priority)

		on_sighted = bool(self.trigger_on_agent_sighted)
		on_left = bool(self.trigger_on_agent_left)
		if isinstance(params, dict):
			if "trigger_on_agent_sighted" in params:
				on_sighted = bool(params.get("trigger_on_agent_sighted", on_sighted))
			if "trigger_on_agent_left" in params:
				on_left = bool(params.get("trigger_on_agent_left", on_left))

		# 2. Build workflow-side perception (no sim-side perception dependency)
		full_ws_view = build_full_ws_view(ws, agent_id, "", {})
		perception = build_agent_perception(full_ws_view, agent_id)
		if not (perception or {}).get("location"):
			rt = arb._get_rule_runtime("PerceptionChange")
			rt["known_ids"] = []
			return InterruptResult(interrupt=False, reason="", rule_type="PerceptionChange", priority=self.priority)

		# 3. Perceive current visible entities
		current_entities = perception.get("entities", []) or []
		current_ids = set()
		for ent_data in current_entities:
			eid = str(ent_data.get("id", "") or "")
			if eid and eid != str(agent_id): # Ignore self
				current_ids.add(eid)

		# 4. Compare with last known state
		# State structure: {"known_ids": [id1, id2, ...]}
		rt = arb._get_rule_runtime("PerceptionChange")
		last_known_ids = set(rt.get("known_ids", []) or [])
		
		# Update state immediately (so we don't interrupt again for the same set next tick)
		rt["known_ids"] = list(current_ids)

		new_ids = current_ids - last_known_ids
		left_ids = last_known_ids - current_ids
		entered_names: list[str] = []
		left_names: list[str] = []
		left_destinations: dict[str, str] = {}
		loc = ws.get_location_of_entity(agent_id) if hasattr(ws, "get_location_of_entity") else None
		source_loc_id = str(getattr(loc, "location_id", "") or "")
		now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		for new_id in new_ids:
			new_ent = ws.get_entity_by_id(new_id)
			if new_ent is None:
				continue
			if on_sighted and new_ent.get_component("AgentControlComponent") is None:
				continue
			entered_names.append(f"{new_ent.entity_name} ({new_id})")
		for left_id in left_ids:
			left_ent = ws.get_entity_by_id(left_id)
			if left_ent is None:
				label = f"{left_id}"
			else:
				if on_left and left_ent.get_component("AgentControlComponent") is None:
					continue
				label = f"{left_ent.entity_name} ({left_id})"
			dest = self._recent_departure_destination(ws, left_id, source_loc_id, now_tick)
			if dest:
				left_destinations[left_id] = dest
				label = f"{label} -> {dest}"
			left_names.append(label)
		if entered_names or left_names:
			parts: list[str] = []
			if entered_names:
				parts.append(f"entered: {', '.join(entered_names)}")
			if left_names:
				parts.append(f"left: {', '.join(left_names)}")
			reason_msg = "Perception changed: " + "; ".join(parts)
			return InterruptResult(
				interrupt=True,
				reason=reason_msg,
				rule_type="PerceptionChange",
				priority=self.priority,
				data={"new_ids": list(new_ids), "left_ids": list(left_ids), "left_destinations": dict(left_destinations)},
			)

		return InterruptResult(interrupt=False, reason="", rule_type="PerceptionChange", priority=self.priority)
