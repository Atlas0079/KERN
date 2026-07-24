from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .condition_evaluator import ConditionEvaluator
from ..interaction.narrative import render_interaction_narrative


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
		effect_type = str(event.get("effect", "") or "")
		event_entity_id = str(event.get("entity_id", "") or "")
		base_ctx = dict(ctx)
		base_ctx["event"] = dict(event)
		base_ctx["effect"] = effect_type
		base_ctx["effect_input"] = dict(event.get("input", {}) or {}) if isinstance(event.get("input", {}), dict) else {}
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
			on_effect = str(rule.get("on_effect", "") or "")
			if on_effect and on_effect != effect_type:
				continue
			rule_id = str(rule.get("id", "") or "")
			selector = rule.get("selector", {}) or {}
			condition = rule.get("condition", {}) or {}
			if not self.evaluator.evaluate(ws, selector if isinstance(selector, dict) else {}, base_ctx):
				continue
			if not self.evaluator.evaluate(ws, condition if isinstance(condition, dict) else {}, base_ctx):
				continue
			bundle = rule.get("bundle", {}) or {}
			req_ctx = dict(base_ctx)
			req_ctx["reaction_rule_id"] = rule_id
			req_ctx["reaction_trigger_event_type"] = event_type
			reaction_verb = str(rule.get("reaction_verb", "") or "").strip() or rule_id
			req_ctx["reaction_verb"] = reaction_verb
			narrative_template = str(rule.get("narrative_success", "") or "").strip()
			compiled_bundle = dict(bundle) if isinstance(bundle, dict) else {}
			effects = [
				item
				for item in list(compiled_bundle.get("effects", []) or [])
				if not (isinstance(item, dict) and str(item.get("effect", "") or "") == "RecordInteraction")
			]
			if narrative_template:
				narrative = render_interaction_narrative(
					ws,
					narrative_template,
					req_ctx,
					values={"event_type": event_type, "reaction_id": rule_id},
				)
				effects.insert(
					0,
					{
						"effect": "RecordInteraction",
						"actor_id": str(req_ctx.get("actor_id", "") or req_ctx.get("self_id", "") or ""),
						"verb": reaction_verb,
						"target_id": str(req_ctx.get("target_id", "") or req_ctx.get("event_entity_id", "") or ""),
						"status": "success",
						"reason": "",
						"extra": {
							"narrative": narrative,
							"interaction_type": "reaction",
							"source_id": rule_id,
							"reaction_id": rule_id,
							"trigger_event_type": event_type,
						},
					},
				)
			compiled_bundle["effects"] = effects
			requests.append(
				{
					"bundle": compiled_bundle,
					"context": req_ctx,
				}
			)
		return requests
