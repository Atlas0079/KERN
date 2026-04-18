from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .memory_policy import build_memory_patch
from .observer import build_agent_perception
from .workflow_contract import build_apply_commands_decision, build_noop_decision


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
			return build_noop_decision(meta={"provider": "simple_policy", "reason": "missing_full_ws_view"})
		obs = build_agent_perception(full_ws_view, str(actor_id))
		_ = recipe_db
		_ = reason
		_ = mode_context
		for ent in list(obs.get("entities", []) or []):
			tags = ent.get("tags", []) or []
			if "edible" in tags:
				return build_apply_commands_decision(
					commands=[{"verb": "Consume", "target_id": ent.get("id"), "parameters": {}}],
					meta={"provider": "simple_policy", "reason": "edible_visible"},
				)
		return build_noop_decision(meta={"provider": "simple_policy", "reason": "no_action"})

	def decide_dialogue(self, perception: dict[str, Any], conversation_context: dict[str, Any], self_id: str | None = None) -> str:
		return "PASS"

	def build_memory_patch_data(self, ws_view: Any, recipe_db: dict[str, Any] | None, actor_id: str) -> dict[str, Any] | None:
		view_payload = dict(ws_view or {}) if isinstance(ws_view, dict) else {}
		full_ws_view = dict(view_payload.get("full_ws_view", {}) or {}) if isinstance(view_payload.get("full_ws_view", {}), dict) else {}
		if not full_ws_view:
			return None
		recipe_db_view = dict(recipe_db or {}) if isinstance(recipe_db, dict) else {}
		return build_memory_patch(full_ws_view=full_ws_view, recipe_db=recipe_db_view, actor_id=str(actor_id))
