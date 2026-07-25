from __future__ import annotations

from typing import Any


WORKFLOW_DECISION_TYPES = frozenset({"action_plan", "end_turn"})


def build_end_turn_decision(meta: dict[str, Any] | None = None) -> dict[str, Any]:
	return {
		"type": "end_turn",
		"meta": dict(meta or {}),
	}


def build_action_plan_decision(actions: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
	out_actions: list[dict[str, Any]] = []
	for item in list(actions or []):
		if isinstance(item, dict):
			out_actions.append(dict(item))
	return {"type": "action_plan", "actions": out_actions, "meta": dict(meta or {})}


def validate_workflow_decision(raw: Any) -> tuple[dict[str, Any] | None, str]:
	if not isinstance(raw, dict):
		return None, "decision must be object"
	d = dict(raw)
	dtype = str(d.get("type", "") or "").strip()
	if dtype not in WORKFLOW_DECISION_TYPES:
		return None, "decision.type must be action_plan/end_turn"
	if dtype == "end_turn":
		return {"type": "end_turn", "meta": dict(d.get("meta", {}) or {})}, ""
	if dtype == "action_plan":
		actions = d.get("actions")
		if not isinstance(actions, list) or not actions:
			return None, "decision.actions must be a non-empty list when type=action_plan"
		out_actions: list[dict[str, Any]] = []
		for idx, item in enumerate(actions):
			if not isinstance(item, dict):
				return None, f"decision.actions[{idx}] must be object"
			verb = str(item.get("verb", "") or "").strip()
			if not verb:
				return None, f"decision.actions[{idx}].verb is required"
			params = item.get("parameters", {}) or {}
			if not isinstance(params, dict):
				return None, f"decision.actions[{idx}].parameters must be object"
			out = dict(item)
			out["verb"] = verb
			out["parameters"] = dict(params)
			out_actions.append(out)
		return {"type": "action_plan", "actions": out_actions, "meta": dict(d.get("meta", {}) or {})}, ""
	return None, "unsupported decision type"
