from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..dynamic_text import DynamicTextError
from ..execution_errors import KernFailure
from .condition_evaluator import ConditionEvaluator
from ..interaction.narrative import render_interaction_narrative


@dataclass
class TriggerSystem:
	rules: list[dict[str, Any]] = field(default_factory=list)
	evaluator: ConditionEvaluator = field(default_factory=ConditionEvaluator)

	def begin_tick(self) -> None:
		return

	def build_reaction_effects(self, ws: Any, event: dict[str, Any], context: dict[str, Any] | None) -> list[dict[str, Any]]:
		ctx = dict(context or {})
		event_type = str(event["type"])
		payload = dict(event["payload"])
		event_entity_id = str(payload.get("entity_id", "") or "")
		base_ctx = dict(ctx)
		base_ctx["event"] = dict(event)
		base_ctx["effect_input"] = dict(event.get("input", {}))
		base_ctx["event_entity_id"] = event_entity_id
		if event_entity_id and not str(base_ctx.get("self_id", "") or ""):
			base_ctx["self_id"] = event_entity_id
		if event_entity_id and not str(base_ctx.get("target_id", "") or ""):
			base_ctx["target_id"] = event_entity_id
		requests: list[dict[str, Any]] = []
		for rule in self.rules:
			if not bool(rule.get("enabled", True)):
				continue
			on_event = str(rule.get("on_event", "") or "")
			if not on_event or "on_effect" in rule:
				raise KernFailure(
					"REACTION_RULE_INVALID",
					"reaction rule requires on_event and must not define on_effect",
					origin="reaction",
					phase="rule_validation",
					context={"reaction_rule_id": str(rule.get("id", "") or "")},
				)
			if on_event != event_type:
				continue
			rule_id = str(rule.get("id", "") or "")
			selector = rule.get("selector", {})
			condition = rule.get("condition", {})
			if not self.evaluator.evaluate(ws, selector, base_ctx):
				continue
			if not self.evaluator.evaluate(ws, condition, base_ctx):
				continue
			bundle = rule["bundle"]
			req_ctx = dict(base_ctx)
			req_ctx["reaction_rule_id"] = rule_id
			req_ctx["reaction_trigger_event_type"] = event_type
			reaction_verb = str(rule.get("reaction_verb", "") or "").strip() or rule_id
			req_ctx["reaction_verb"] = reaction_verb
			narrative_template = str(rule.get("narrative_success", "") or "").strip()
			compiled_bundle = dict(bundle)
			effects = list(compiled_bundle.get("effects", []) or [])
			if narrative_template:
				try:
					narrative = render_interaction_narrative(
						ws,
						narrative_template,
						req_ctx,
						values={"event_type": event_type, "reaction_id": rule_id},
					)
				except DynamicTextError as exc:
					raise KernFailure(
						"REACTION_NARRATIVE_RENDER_FAILED",
						str(exc),
						origin="reaction",
						phase="narrative_render",
						context={"reaction_rule_id": rule_id, "trigger_event_type": event_type},
					) from exc
				effects.insert(
					0,
					{
						"effect": "RecordInteraction",
						"actor_id": str(req_ctx.get("actor_id", "") or req_ctx.get("self_id", "") or ""),
						"verb": reaction_verb,
						"target_id": str(req_ctx.get("target_id", "") or req_ctx.get("event_entity_id", "") or ""),
						"status": "success",
						"reason": "",
						"interaction_origin": "reaction_narrative",
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
