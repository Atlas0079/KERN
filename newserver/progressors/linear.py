from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sim.condition_evaluator import ConditionEvaluator


def _read_number_from_component(component: Any, prop_name: str, default: float = 0.0) -> float:
	if component is None:
		return float(default)

	if hasattr(component, "data") and isinstance(getattr(component, "data"), dict):
		val = component.data.get(prop_name, default)
		try:
			return float(val)
		except Exception:
			return float(default)

	val = getattr(component, prop_name, default)
	try:
		return float(val)
	except Exception:
		return float(default)


def _as_number(value: Any, field_name: str) -> float:
	try:
		return float(value)
	except Exception as e:
		raise ValueError(f"LinearProgressor: {field_name} must be number, got {value!r}") from e


def _resolve_term_value(ws: Any, ctx: dict[str, Any], term: dict[str, Any], field_prefix: str) -> float:
	has_value = "value" in term
	has_read = "read" in term
	if has_value == has_read:
		raise ValueError(f"LinearProgressor: {field_prefix} requires exactly one of 'value' or 'read'")
	if has_value:
		return _as_number(term.get("value"), f"{field_prefix}.value")
	read = term.get("read")
	if not isinstance(read, dict):
		raise ValueError(f"LinearProgressor: {field_prefix}.read must be object")
	target_ref = str(read.get("target", "self") or "self")
	component_name = str(read.get("component", "") or "").strip()
	property_name = str(read.get("property", "") or "").strip()
	default_value = read.get("default", 0.0)
	if not component_name:
		raise ValueError(f"LinearProgressor: {field_prefix}.read.component is required")
	if not property_name:
		raise ValueError(f"LinearProgressor: {field_prefix}.read.property is required")
	from ..entity_ref_resolver import resolve_entity
	target_entity = resolve_entity(ws, target_ref, ctx, allow_literal=True)
	if target_entity is None:
		return _as_number(default_value, f"{field_prefix}.read.default")
	component = target_entity.get_component(component_name) if hasattr(target_entity, "get_component") else None
	return _read_number_from_component(component, property_name, _as_number(default_value, f"{field_prefix}.read.default"))


def _validate_term(term: Any, field_prefix: str) -> dict[str, Any]:
	if not isinstance(term, dict):
		raise ValueError(f"LinearProgressor: {field_prefix} must be object")
	when = term.get("when", {})
	if when is None:
		when = {}
	if not isinstance(when, dict):
		raise ValueError(f"LinearProgressor: {field_prefix}.when must be object")
	return dict(term)


@dataclass
class LinearProgressor:
	progressor_id: str = "Linear"
	evaluator: ConditionEvaluator = field(default_factory=ConditionEvaluator)

	def compute_progress_delta(self, ws: Any, agent_id: str, task: Any, ticks: int) -> float:
		params = getattr(task, "progressor_params", {}) or {}
		if not isinstance(params, dict):
			raise ValueError("LinearProgressor: progressor_params must be object")
		if "progress_contributors" in params:
			raise ValueError("LinearProgressor: 'progress_contributors' is removed; use add_terms/mul_terms")

		base = _as_number(params.get("base_progress_per_tick", 1.0), "base_progress_per_tick")
		add_terms = params.get("add_terms", []) or []
		mul_terms = params.get("mul_terms", []) or []
		clamp = params.get("clamp", None)
		if not isinstance(add_terms, list):
			raise ValueError("LinearProgressor: add_terms must be list")
		if not isinstance(mul_terms, list):
			raise ValueError("LinearProgressor: mul_terms must be list")
		if clamp is not None and not isinstance(clamp, dict):
			raise ValueError("LinearProgressor: clamp must be object")

		ctx = {
			"self_id": str(agent_id or ""),
			"target_id": str(getattr(task, "target_entity_id", "") or ""),
			"task_id": str(getattr(task, "task_id", "") or ""),
			"parameters": dict(getattr(task, "parameters", {}) or {}),
		}

		delta = base
		for idx, term in enumerate(add_terms):
			t = _validate_term(term, f"add_terms[{idx}]")
			when = t.get("when", {}) or {}
			if not self.evaluator.evaluate(ws, when, ctx):
				continue
			delta += _resolve_term_value(ws, ctx, t, f"add_terms[{idx}]")

		for idx, term in enumerate(mul_terms):
			t = _validate_term(term, f"mul_terms[{idx}]")
			when = t.get("when", {}) or {}
			if not self.evaluator.evaluate(ws, when, ctx):
				continue
			delta *= _resolve_term_value(ws, ctx, t, f"mul_terms[{idx}]")

		if isinstance(clamp, dict):
			min_v = clamp.get("min", None)
			max_v = clamp.get("max", None)
			if min_v is not None:
				delta = max(delta, _as_number(min_v, "clamp.min"))
			if max_v is not None:
				delta = min(delta, _as_number(max_v, "clamp.max"))
		return delta * _as_number(ticks, "ticks")
