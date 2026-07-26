from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import AgentTurnSession, DecisionFrame, EndTurn, SubmitAction, TurnStart
from .dialogue import DialogueFrame, Pass


@dataclass
class SimplePolicyActionProvider:
	"""
	Minimal Automatic Policy (For "Automatic Simulation Loop" bootstrapping):
	- If edible entity seen (tag: edible), execute Consume on it

	Intent: Decouple action generation from Manager; Necessity: No change to simulation main loop when plugging in LLM later.
	"""

	def begin_turn(self, _start: TurnStart) -> AgentTurnSession:
		return _SimplePolicyTurnSession()

	def decide_utterance(self, _frame: DialogueFrame):
		return Pass()


class _SimplePolicyTurnSession:
	def next_step(self, frame: DecisionFrame):
		for ent in list(frame.perception.get("entities", []) or []):
			tags = ent.get("tags", []) or []
			if "edible" in tags:
				return SubmitAction(
					intent={"verb": "Consume", "target_id": ent.get("id"), "parameters": {}},
					meta={"provider": "simple_policy", "reason": "edible_visible"},
				)
		return EndTurn(meta={"provider": "simple_policy", "reason": "no_action"})
