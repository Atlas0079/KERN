from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .observer import build_agent_perception
from .workflow_contract import build_action_plan_decision, build_end_turn_decision


@dataclass
class SimplePolicyActionProvider:
	"""
	Minimal Automatic Policy (For "Automatic Simulation Loop" bootstrapping):
	- If edible entity seen (tag: edible), execute Consume on it

	Intent: Decouple action generation from Manager; Necessity: No change to simulation main loop when plugging in LLM later.
	"""

	def decide(
		self,
		ws_view: Any,
		recipe_db: dict[str, Any] | None,
		actor_id: str,
		reason: str,
		mode_context: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		view_payload = dict(ws_view or {}) if isinstance(ws_view, dict) else {}
		full_ws_view = dict(view_payload.get("full_ws_view", {}) or {}) if isinstance(view_payload.get("full_ws_view", {}), dict) else {}
		if not full_ws_view:
			return build_end_turn_decision(meta={"provider": "simple_policy", "reason": "missing_full_ws_view"})
		obs = build_agent_perception(full_ws_view, str(actor_id))
		_ = recipe_db
		_ = reason
		_ = mode_context
		for ent in list(obs.get("entities", []) or []):
			tags = ent.get("tags", []) or []
			if "edible" in tags:
				return build_action_plan_decision(
					actions=[{"verb": "Consume", "target_id": ent.get("id"), "parameters": {}}],
					meta={"provider": "simple_policy", "reason": "edible_visible"},
				)
		return build_end_turn_decision(meta={"provider": "simple_policy", "reason": "no_action"})

	def decide_dialogue(self, perception: dict[str, Any], conversation_context: dict[str, Any], self_id: str | None = None) -> str:
		return "PASS"
