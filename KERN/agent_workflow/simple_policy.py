from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import AgentTurnSession, EndTurn, SubmitAction, TurnFrame, TurnStart
from .dialogue import DialogueFrame, Pass
from .full_ws_view_builder import build_full_ws_view
from .observer import build_agent_perception
from .view_profile import active_workflow_view_profile


@dataclass
class SimplePolicyActionProvider:
	"""
	Minimal Automatic Policy (For "Automatic Simulation Loop" bootstrapping):
	- If edible entity seen (tag: edible), execute Consume on it

	Intent: Decouple action generation from Manager; Necessity: No change to simulation main loop when plugging in LLM later.
	"""

	def begin_turn(self, _ws: Any, _start: TurnStart) -> AgentTurnSession:
		return _SimplePolicyTurnSession()

	def decide_utterance(self, _frame: DialogueFrame):
		return Pass()


class _SimplePolicyTurnSession:
	def next_step(self, ws: Any, frame: TurnFrame):
		profile = active_workflow_view_profile(ws=ws, mode_context=frame.mode_context, full_ws_view={})
		full_view = build_full_ws_view(ws, frame.actor_id, frame.reason, frame.mode_context)
		full_view["workflow_view_profile"] = dict(profile)
		perception = build_agent_perception(full_view, frame.actor_id)
		for ent in list(perception.get("entities", []) or []):
			tags = ent.get("tags", []) or []
			if "edible" in tags:
				return SubmitAction(
					intent={"verb": "Consume", "target_id": ent.get("id"), "parameters": {}},
					meta={"provider": "simple_policy", "reason": "edible_visible"},
				)
		return EndTurn(meta={"provider": "simple_policy", "reason": "no_action"})
