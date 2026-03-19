from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SimplePolicyActionProvider:
	"""
	Minimal Automatic Policy (For "Automatic Simulation Loop" bootstrapping):
	- If edible entity seen (tag: edible), execute Consume on it

	Intent: Decouple action generation from Manager; Necessity: No change to simulation main loop when plugging in LLM later.
	"""

	def decide(self, perception: dict[str, Any], reason: str) -> list[dict[str, Any]]:
		for ent in perception.get("entities", []):
			tags = ent.get("tags", []) or []
			if "edible" in tags:
				return [{"verb": "Consume", "target_id": ent.get("id")}]
		return []

	def decide_dialogue(self, perception: dict[str, Any], conversation_context: dict[str, Any], self_id: str | None = None) -> str:
		return "PASS"
