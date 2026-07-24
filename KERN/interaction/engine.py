from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..sim.condition_evaluator import ConditionEvaluator


@dataclass
class InteractionEngine:
	"""
	Minimal Recipe Engine (Align with Godot InteractionEngine.gd):
	- Match recipe via verb + selector + condition
	- Output effects list and context
	"""

	recipe_db: dict[str, Any]
	evaluator: ConditionEvaluator = field(default_factory=ConditionEvaluator)

	def _is_duration_process(self, process_data: dict[str, Any]) -> bool:
		process = dict(process_data or {}) if isinstance(process_data, dict) else {}
		duration = process.get("duration", {}) or {}
		if isinstance(duration, dict) and duration:
			return True
		required_progress = float(process.get("required_progress", 0) or 0)
		return required_progress != 0

	def process_command(self, ws: Any, self_id: str, command_data: dict[str, Any]) -> dict[str, Any]:
		verb = command_data.get("verb")
		target_id = command_data.get("target_id")
		params = command_data.get("parameters", {}) or {}
		if not isinstance(params, dict):
			params = {}
		verb_text = str(verb or "")
		if verb_text == "Talk":
			if str(target_id or "").strip():
				return {"status": "rejected", "reason": "TALK_TARGET_FORBIDDEN", "message": "Talk must not provide target_id"}
			text = str(params.get("text", "") or "").strip()
			if not text:
				return {"status": "rejected", "reason": "MISSING_DIALOGUE_TEXT", "message": "Talk requires parameters.text as opening line"}
			target = ws.get_entity_by_id(str(self_id))
			target_id = str(self_id)
		else:
			target = ws.get_entity_by_id(str(target_id))
		if target is None:
			return {"status": "rejected", "reason": "TARGET_MISSING", "message": f"Target entity not found: {target_id}"}

		resolved_params = dict(params)
		recipe, mismatch_reasons = self._find_matching_recipe(ws=ws, verb=verb_text, self_id=str(self_id), target=target, params=resolved_params)
		if not recipe:
			return {
				"status": "rejected",
				"reason": "NO_RECIPE",
				"message": "No matching recipe found for this interaction.",
				"mismatch_reasons": list(mismatch_reasons or []),
				"recipe": {},
			}
		assign_to = str((recipe.get("process", {}) or {}).get("assign_to", "") or "").strip()
		# context only carries invocation environment; effect-private config must stay in effect data.
		context = {"self_id": self_id, "target_id": str(target_id), "parameters": dict(resolved_params)}

		process_data = recipe.get("process", {}) or {}
		if self._is_duration_process(process_data):
			if assign_to not in {"self", "target"}:
				return {"status": "rejected", "reason": "invalid_process_assign_to"}
			return {
				"status": "success",
				"bundle": {
					"effects": [
						{
							"effect": "CreateTask",
							"recipe": recipe,
							"assign_to": assign_to,
						}
					]
				},
				"context": context,
				"recipe": dict(recipe),
			}

		bundle = effect_bundle_from_raw(recipe.get("bundle", {}) or {})
		return {"status": "success", "bundle": bundle.to_dict(), "context": context, "recipe": dict(recipe)}

	def _find_matching_recipe(self, ws: Any, verb: str, self_id: str, target: Any, params: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
		mismatch_reasons: list[dict[str, Any]] = []
		for recipe_id, recipe in (self.recipe_db or {}).items():
			if (recipe or {}).get("verb") != verb:
				continue
			recipe_selector = recipe.get("selector", {}) or {}
			recipe_condition = recipe.get("condition", {}) or {}
			ctx = {
				"self_id": str(self_id),
				"target_id": str(getattr(target, "entity_id", "") or ""),
				"parameters": dict(params or {}),
			}
			if isinstance(recipe_selector, dict) and recipe_selector:
				selector_eval = self.evaluator.explain(ws, recipe_selector, ctx, path="selector")
				if not bool(selector_eval.get("ok", False)):
					mismatch_reasons.append(
						{
							"recipe_id": str(recipe_id),
							"stage": "selector",
							"reason": str(selector_eval.get("reason", "") or "SELECTOR_FAILED"),
							"path": str(selector_eval.get("path", "") or "selector"),
							"detail": dict(selector_eval.get("detail", {}) or {}),
						}
					)
					continue
			if isinstance(recipe_condition, dict) and recipe_condition:
				condition_eval = self.evaluator.explain(ws, recipe_condition, ctx, path="condition")
				if not bool(condition_eval.get("ok", False)):
					mismatch_reasons.append(
						{
							"recipe_id": str(recipe_id),
							"stage": "condition",
							"reason": str(condition_eval.get("reason", "") or "CONDITION_FAILED"),
							"path": str(condition_eval.get("path", "") or "condition"),
							"detail": dict(condition_eval.get("detail", {}) or {}),
						}
					)
					continue

			result = dict(recipe)
			result["id"] = str(recipe_id)
			return result, []

		return None, mismatch_reasons[:8]
