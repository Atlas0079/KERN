from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..effect_contract import EFFECT_TYPES, diff_effect_types
from ..executor._effect_binder import get_binder_effect_types
from ..executor.executor import get_executor_effect_types
from .loader import DataBundle


@dataclass
class ValidationReport:
	mode: str
	errors: list[str] = field(default_factory=list)
	warnings: list[str] = field(default_factory=list)

	@property
	def ok(self) -> bool:
		return len(self.errors) == 0


def _as_mode(mode: str) -> str:
	m = str(mode or "").strip().lower()
	if m in {"off", "fast", "strict"}:
		return m
	return "fast"


def _validate_effect(effect_obj: Any, where: str, report: ValidationReport) -> None:
	if not isinstance(effect_obj, dict):
		report.errors.append(f"{where}: effect must be object")
		return
	if "dynamic_outputs_from_component" in effect_obj:
		return
	eff = str(effect_obj.get("effect", "") or "").strip()
	if not eff:
		report.errors.append(f"{where}: missing effect")
		return
	if eff not in EFFECT_TYPES:
		report.errors.append(f"{where}: unknown effect '{eff}'")
	if eff == "MoveEntity":
		required = ["entity_ref", "from_ref", "to_ref"]
		for key in required:
			if not str(effect_obj.get(key, "") or "").strip():
				report.errors.append(f"{where}: MoveEntity missing '{key}'")
		legacy = [k for k in ["entity_id", "source_id", "destination_id", "target", "source", "destination"] if k in effect_obj]
		if legacy:
			report.errors.append(f"{where}: MoveEntity uses deprecated keys {sorted(legacy)}, use entity_ref/from_ref/to_ref")
	if eff == "ModifyProperty":
		for key in ["target", "component", "property"]:
			if not str(effect_obj.get(key, "") or "").strip():
				report.errors.append(f"{where}: ModifyProperty missing '{key}'")
		has_change = "change" in effect_obj
		has_value = "value" in effect_obj
		if not has_change and not has_value:
			report.errors.append(f"{where}: ModifyProperty requires exactly one of 'change' or 'value'")
		if has_change and has_value:
			report.errors.append(f"{where}: ModifyProperty cannot contain both 'change' and 'value'")
	if eff == "CreateTask":
		recipe = effect_obj.get("recipe", {})
		if not isinstance(recipe, dict) or not recipe:
			report.errors.append(f"{where}: CreateTask missing 'recipe' object")
		assign_to = str(effect_obj.get("assign_to", "") or "").strip()
		if not assign_to:
			report.errors.append(f"{where}: CreateTask missing 'assign_to'")
		if assign_to not in {"self", "target"}:
			report.errors.append(f"{where}: CreateTask assign_to must be 'self' or 'target'")
	if eff == "AgentControlTick":
		if "max_actions_in_tick" not in effect_obj:
			report.errors.append(f"{where}: AgentControlTick missing 'max_actions_in_tick'")
	if eff == "WorkerTick":
		if "ticks" not in effect_obj:
			report.errors.append(f"{where}: WorkerTick missing 'ticks'")
	if eff == "ApplyMetaAction":
		for key in ["target", "action_type", "params"]:
			if key not in effect_obj:
				report.errors.append(f"{where}: ApplyMetaAction missing '{key}'")
		params = effect_obj.get("params", None)
		if params is not None and not isinstance(params, dict):
			report.errors.append(f"{where}: ApplyMetaAction 'params' must be object")
	if eff == "AttachDetails":
		detail_type = str(effect_obj.get("detail_type", "") or "").strip()
		if detail_type not in {"entity", "interrupt_preset"}:
			report.errors.append(f"{where}: AttachDetails detail_type must be 'entity' or 'interrupt_preset'")
		if detail_type == "entity" and not str(effect_obj.get("target", "") or "").strip():
			report.errors.append(f"{where}: AttachDetails(entity) missing 'target'")
	if eff == "EmitEvent":
		if not str(effect_obj.get("event_type", "") or "").strip():
			report.errors.append(f"{where}: EmitEvent missing 'event_type'")
		if "payload" not in effect_obj:
			report.errors.append(f"{where}: EmitEvent missing 'payload'")
		elif not isinstance(effect_obj.get("payload"), dict):
			report.errors.append(f"{where}: EmitEvent 'payload' must be object")
	if eff == "ExchangeResources":
		for key in ["source", "target", "transfer_mode", "consume_items", "consume_money", "produce_items", "produce_money"]:
			if key not in effect_obj:
				report.errors.append(f"{where}: ExchangeResources missing '{key}'")
	if eff == "AbortSimulation":
		for key in ["reason", "detail", "severity", "stop"]:
			if key not in effect_obj:
				report.errors.append(f"{where}: AbortSimulation missing '{key}'")
		sev = str(effect_obj.get("severity", "") or "").strip().lower()
		if sev.startswith("param:"):
			sev = ""
		if sev and sev not in {"info", "warning", "error", "fatal"}:
			report.errors.append(f"{where}: AbortSimulation severity must be one of info/warning/error/fatal")
	deprecated_refs: list[str] = []
	stack: list[Any] = [effect_obj]
	while stack:
		item = stack.pop()
		if isinstance(item, dict):
			for v in item.values():
				stack.append(v)
		elif isinstance(item, list):
			for v in item:
				stack.append(v)
		elif isinstance(item, str):
			ref = str(item).strip()
			if ref == "agent":
				deprecated_refs.append("agent->self")
			elif ref.startswith("parameter:"):
				deprecated_refs.append("parameter:->param:")
			elif ref == "event.entity_id":
				deprecated_refs.append("event.entity_id->event_entity")
	if deprecated_refs:
		report.errors.append(f"{where}: deprecated refs {sorted(set(deprecated_refs))}")
	if report.mode == "strict":
		# TODO: strict schema will be tightened again after effect DSL is fully stabilized.
		if "context" in effect_obj:
			report.errors.append(f"{where}: deprecated key 'context', move fields to top-level effect keys")


def _validate_effect_contract_alignment(report: ValidationReport) -> None:
	for msg in diff_effect_types(get_binder_effect_types(), EFFECT_TYPES, "binder registry"):
		report.errors.append(f"effect_contract: {msg}")
	for msg in diff_effect_types(get_executor_effect_types(), EFFECT_TYPES, "executor registry"):
		report.errors.append(f"effect_contract: {msg}")


def _validate_linear_progression_params(params: Any, where: str, report: ValidationReport) -> None:
	if not isinstance(params, dict):
		report.errors.append(f"{where}: progression.params must be object")
		return
	if "progress_contributors" in params:
		report.errors.append(f"{where}: progression.params.progress_contributors is removed, use add_terms/mul_terms")
	for key in ["add_terms", "mul_terms"]:
		terms = params.get(key, [])
		if terms is None:
			terms = []
		if not isinstance(terms, list):
			report.errors.append(f"{where}: progression.params.{key} must be list")
			continue
		for idx, term in enumerate(terms):
			if not isinstance(term, dict):
				report.errors.append(f"{where}: progression.params.{key}[{idx}] must be object")
				continue
			when = term.get("when", {})
			if when is None:
				when = {}
			if not isinstance(when, dict):
				report.errors.append(f"{where}: progression.params.{key}[{idx}].when must be object")
			has_value = "value" in term
			has_read = "read" in term
			if has_value == has_read:
				report.errors.append(f"{where}: progression.params.{key}[{idx}] must contain exactly one of value/read")
			if has_read:
				read = term.get("read")
				if not isinstance(read, dict):
					report.errors.append(f"{where}: progression.params.{key}[{idx}].read must be object")
				else:
					if not str(read.get("component", "") or "").strip():
						report.errors.append(f"{where}: progression.params.{key}[{idx}].read.component is required")
					if not str(read.get("property", "") or "").strip():
						report.errors.append(f"{where}: progression.params.{key}[{idx}].read.property is required")
	clamp = params.get("clamp", None)
	if clamp is not None and not isinstance(clamp, dict):
		report.errors.append(f"{where}: progression.params.clamp must be object")


def _is_param_token(value: Any) -> bool:
	text = str(value or "").strip()
	return text.startswith("param:") and bool(str(text[len("param:") :]).strip())


def _validate_process_duration(process: Any, where: str, report: ValidationReport) -> None:
	if not isinstance(process, dict):
		return
	duration = process.get("duration", None)
	if duration is None:
		return
	if not isinstance(duration, dict) or not duration:
		report.errors.append(f"{where}: process.duration must be object")
		return
	mode = str(duration.get("mode", "") or "").strip().lower()
	if mode not in {"fixed", "param", "path_distance"}:
		report.errors.append(f"{where}: process.duration.mode must be fixed/param/path_distance")
		return
	if mode == "fixed":
		if "value" not in duration:
			report.errors.append(f"{where}: process.duration.value is required for mode=fixed")
		return
	if mode == "param":
		if not _is_param_token(duration.get("from_param", "")):
			report.errors.append(f"{where}: process.duration.from_param must be param:<name> for mode=param")
		return
	if mode == "path_distance":
		if not _is_param_token(duration.get("to_param", "")):
			report.errors.append(f"{where}: process.duration.to_param must be param:<name> for mode=path_distance")


def validate_bundle(bundle: DataBundle, mode: str = "fast") -> ValidationReport:
	v_mode = _as_mode(mode)
	report = ValidationReport(mode=v_mode)
	if v_mode == "off":
		return report
	_validate_effect_contract_alignment(report)
	recipes = bundle.recipes if isinstance(bundle.recipes, dict) else {}
	reactions = bundle.reactions if isinstance(bundle.reactions, dict) else {}

	for rid, recipe in recipes.items():
		if not isinstance(recipe, dict):
			continue
		_validate_process_duration(recipe.get("process", {}) or {}, f"recipe[{rid}]", report)
		progression = recipe.get("progression", {}) or {}
		if isinstance(progression, dict):
			progressor = str(progression.get("progressor", progression.get("progressor_id", "")) or "").strip()
			if progressor == "Linear":
				_validate_linear_progression_params(
					progression.get("params", {}) or {},
					f"recipe[{rid}]",
					report,
				)
		outputs = recipe.get("outputs", []) or []
		if not isinstance(outputs, list):
			continue
		for i, eff in enumerate(outputs):
			_validate_effect(eff, f"recipe[{rid}].outputs[{i}]", report)

	rules = reactions.get("rules", []) if isinstance(reactions, dict) else []
	if not isinstance(rules, list):
		rules = []
	for i, rule in enumerate(rules):
		if not isinstance(rule, dict):
			continue
		effects = rule.get("effects", []) or []
		if not isinstance(effects, list):
			continue
		for j, eff in enumerate(effects):
			_validate_effect(eff, f"reactions.rules[{i}].effects[{j}]", report)

	return report
