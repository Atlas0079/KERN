from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sim.condition_evaluator import ConditionEvaluator


@dataclass
class InteractionEngine:
	"""
	Minimal Recipe Engine (Align with Godot InteractionEngine.gd):
	- Match recipe via verb + target_tags + parameter_match
	- Output effects list and context
	"""

	recipe_db: dict[str, Any]
	evaluator: ConditionEvaluator = field(default_factory=ConditionEvaluator)

	def process_command(self, ws: Any, self_id: str, command_data: dict[str, Any]) -> dict[str, Any]:
		verb = command_data.get("verb")
		target_id = command_data.get("target_id")
		params = command_data.get("parameters", {}) or {}
		if not isinstance(params, dict):
			params = {}
		verb_text = str(verb or "")
		if verb_text == "Talk":
			if str(target_id or "").strip():
				return {"status": "failed", "reason": "TALK_TARGET_FORBIDDEN", "message": "Talk must not provide target_id"}
			text = str(params.get("text", "") or "").strip()
			if not text:
				return {"status": "failed", "reason": "MISSING_DIALOGUE_TEXT", "message": "Talk requires parameters.text as opening line"}
			target = ws.get_entity_by_id(str(self_id))
			target_id = str(self_id)
		else:
			target = ws.get_entity_by_id(str(target_id))
		if target is None:
			return {"status": "failed", "reason": "TARGET_MISSING", "message": f"Target entity not found: {target_id}"}

		resolved_params = dict(params)
		if verb_text == "Travel":
			to_location_id = str(resolved_params.get("to_location_id", "") or "")
			if not to_location_id:
				return {"status": "failed", "reason": "MISSING_TRAVEL_TARGET", "message": "Travel requires parameters.to_location_id"}
			source_location = ws.get_location_of_entity(self_id)
			if source_location is None:
				return {"status": "failed", "reason": "SOURCE_LOCATION_MISSING", "message": f"Source location not found for agent: {self_id}"}
			selected_path = None
			for p in ws.get_paths_from(source_location.location_id):
				if str(p.to_location_id) == to_location_id and not bool(p.is_blocked):
					selected_path = p
					break
			if selected_path is None:
				return {
					"status": "failed",
					"reason": "NO_PATH",
					"message": f"No available path from {source_location.location_id} to {to_location_id}",
				}
			resolved_params["source_location_id"] = str(source_location.location_id)
			resolved_params["to_location_id"] = to_location_id
			resolved_params["travel_required_progress"] = max(1.0, float(selected_path.distance))

		recipe = self._find_matching_recipe(ws=ws, verb=verb_text, self_id=str(self_id), target=target, params=resolved_params)
		if not recipe:
			return {"status": "failed", "reason": "NO_RECIPE", "message": "No matching recipe found for this interaction."}
		if verb_text == "Travel":
			process = dict(recipe.get("process", {}) or {})
			process["required_progress"] = float(resolved_params["travel_required_progress"])
			recipe["process"] = process

		assign_to = recipe.get("process", {}).get("assign_to", "self")
		context = {"self_id": self_id, "target_id": str(target_id), "recipe": recipe, "parameters": dict(resolved_params), "assign_to": assign_to}
		if verb_text == "Travel":
			to_id = str(resolved_params.get("to_location_id", "") or "")
			to_name = ""
			to_loc = ws.get_location_by_id(to_id) if hasattr(ws, "get_location_by_id") else None
			if to_loc is not None:
				to_name = str(getattr(to_loc, "location_name", "") or "")
			context["interaction_extra"] = {
				"travel_phase": "depart",
				"to_location_id": to_id,
				"to_location_name": to_name,
				"source_location_id": str(resolved_params.get("source_location_id", "") or ""),
			}

		expanded_effects = self._expand_dynamic_outputs(target, recipe.get("outputs", []) or [])
		expanded_effects = self._apply_param_templates(expanded_effects, resolved_params)
		context["recipe"]["outputs"] = expanded_effects

		process_data = recipe.get("process", {}) or {}
		required_progress = float(process_data.get("required_progress", 0))
		if required_progress != 0:
			return {"status": "success", "effects": [{"effect": "CreateTask"}], "context": context}

		return {"status": "success", "effects": expanded_effects, "context": context}

	def _find_matching_recipe(self, ws: Any, verb: str, self_id: str, target: Any, params: dict[str, Any]) -> dict[str, Any] | None:
		for recipe_id, recipe in (self.recipe_db or {}).items():
			if (recipe or {}).get("verb") != verb:
				continue

			required_tags = (recipe or {}).get("target_tags", []) or []
			tag_match_mode = str((recipe or {}).get("target_tags_match", "all") or "all").strip().lower()
			if required_tags:
				if tag_match_mode == "any":
					if not any(target.has_tag(str(tag)) for tag in required_tags):
						continue
				else:
					ok = True
					for tag in required_tags:
						if not target.has_tag(str(tag)):
							ok = False
							break
					if not ok:
						continue

			if "parameter_match" in (recipe or {}):
				pm = recipe.get("parameter_match") or {}
				if pm:
					key = list(pm.keys())[0]
					val = pm[key]
					if params.get(key) != val:
						continue
			recipe_selector = recipe.get("selector", {}) or {}
			recipe_condition = recipe.get("condition", {}) or {}
			ctx = {
				"self_id": str(self_id),
				"target_id": str(getattr(target, "entity_id", "") or ""),
				"parameters": dict(params or {}),
			}
			if isinstance(recipe_selector, dict) and recipe_selector:
				if not self.evaluator.evaluate(ws, recipe_selector, ctx):
					continue
			if isinstance(recipe_condition, dict) and recipe_condition:
				if not self.evaluator.evaluate(ws, recipe_condition, ctx):
					continue

			result = dict(recipe)
			result["id"] = str(recipe_id)
			return result

		return None

	def _expand_dynamic_outputs(self, target: Any, outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
		effects: list[dict[str, Any]] = []
		for eff in outputs:
			if "dynamic_outputs_from_component" in eff:
				dyn = eff["dynamic_outputs_from_component"] or {}
				comp_name = dyn.get("component")
				prop_name = dyn.get("property")
				comp = target.get_component(str(comp_name))
				val = None
				if hasattr(comp, "data") and isinstance(getattr(comp, "data"), dict):
					val = comp.data.get(str(prop_name))
				else:
					val = getattr(comp, str(prop_name), None)
				if isinstance(val, list):
					effects.extend([x for x in val if isinstance(x, dict)])
			else:
				if isinstance(eff, dict):
					effects.append(eff)
		return effects

	def _apply_param_templates(self, effects: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
		def replace_any(x: Any) -> Any:
			if isinstance(x, str) and len(x) >= 3 and x.startswith("{") and x.endswith("}"):
				key = x[1:-1]
				if key in (params or {}):
					return (params or {}).get(key)
			if isinstance(x, list):
				return [replace_any(v) for v in x]
			if isinstance(x, dict):
				return {k: replace_any(v) for k, v in x.items()}
			return x

		out: list[dict[str, Any]] = []
		for eff in list(effects or []):
			if isinstance(eff, dict):
				out.append(replace_any(eff))
		return out
