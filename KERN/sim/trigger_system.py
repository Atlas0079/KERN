from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .condition_evaluator import ConditionEvaluator


@dataclass
class TriggerSystem:
	rules: list[dict[str, Any]] = field(default_factory=list)
	evaluator: ConditionEvaluator = field(default_factory=ConditionEvaluator)

	def begin_tick(self) -> None:
		return

	def build_reaction_effects(self, ws: Any, event: dict[str, Any], context: dict[str, Any] | None) -> list[dict[str, Any]]:
		if not isinstance(event, dict):
			return []
		ctx = dict(context or {})
		event_type = str(event.get("type", "") or "")
		event_entity_id = str(event.get("entity_id", "") or "")
		base_ctx = dict(ctx)
		base_ctx["event"] = dict(event)
		base_ctx["event_entity_id"] = event_entity_id
		if event_entity_id and not str(base_ctx.get("self_id", "") or ""):
			base_ctx["self_id"] = event_entity_id
		if event_entity_id and not str(base_ctx.get("target_id", "") or ""):
			base_ctx["target_id"] = event_entity_id
		requests: list[dict[str, Any]] = []
		for rule in list(self.rules or []):
			if not isinstance(rule, dict):
				continue
			if not bool(rule.get("enabled", True)):
				continue
			on_event = str(rule.get("on_event", "") or "")
			if on_event and on_event != event_type:
				continue
			rule_id = str(rule.get("id", "") or "")
			selector = rule.get("selector", {}) or {}
			condition = rule.get("condition", {}) or {}
			if not self.evaluator.evaluate(ws, selector if isinstance(selector, dict) else {}, base_ctx):
				continue
			if not self.evaluator.evaluate(ws, condition if isinstance(condition, dict) else {}, base_ctx):
				continue
			if hasattr(ws, "record_interaction_attempt"):
				actor_id = str(base_ctx.get("self_id", "") or "")
				target_id = str(base_ctx.get("target_id", "") or "")
				verb = str(rule.get("reaction_verb", "") or "").strip()
				if not verb:
					verb = f"ReactionTriggered:{rule_id}" if rule_id else "ReactionTriggered"
				ws.record_interaction_attempt(
					actor_id=actor_id,
					verb=verb,
					target_id=target_id,
					status="success",
					reason="",
					recipe_id=f"reaction_triggered:{rule_id}" if rule_id else "reaction_triggered",
					extra={
						"is_reaction": True,
						"reaction_phase": "triggered",
						"reaction_rule_id": rule_id,
						"trigger_event": event_type,
					},
				)
			effects = rule.get("effects", []) or []
			for eff in list(effects):
				if not isinstance(eff, dict):
					continue
				req_ctx = dict(base_ctx)
				req_ctx["reaction_rule_id"] = rule_id
				req_ctx["reaction_trigger_event_type"] = event_type
				requests.append({"effect": dict(eff), "context": req_ctx})
		return requests
