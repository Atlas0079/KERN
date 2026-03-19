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


def validate_bundle(bundle: DataBundle, mode: str = "fast") -> ValidationReport:
	v_mode = _as_mode(mode)
	report = ValidationReport(mode=v_mode)
	if v_mode == "off":
		return report
	_validate_effect_contract_alignment(report)

	world = bundle.world if isinstance(bundle.world, dict) else {}
	recipes = bundle.recipes if isinstance(bundle.recipes, dict) else {}
	reactions = bundle.reactions if isinstance(bundle.reactions, dict) else {}
	entity_templates = bundle.entity_templates if isinstance(bundle.entity_templates, dict) else {}

	if not entity_templates:
		report.errors.append("entity_templates is empty")

	locations = world.get("locations", []) or []
	if not isinstance(locations, list):
		report.errors.append("world.locations must be a list")
		locations = []

	location_ids: set[str] = set()
	entity_ids: set[str] = set()
	entity_template_refs: list[tuple[str, str]] = []
	parent_refs: list[tuple[str, str]] = []

	for idx, loc in enumerate(locations):
		if not isinstance(loc, dict):
			report.errors.append(f"world.locations[{idx}] must be object")
			continue
		lid = str(loc.get("location_id", "") or "").strip()
		if not lid:
			report.errors.append(f"world.locations[{idx}] missing location_id")
			continue
		if lid in location_ids:
			report.errors.append(f"duplicate location_id: {lid}")
		location_ids.add(lid)
		entities = loc.get("entities", []) or []
		if not isinstance(entities, list):
			report.errors.append(f"world.locations[{idx}].entities must be list")
			continue
		for eidx, ent in enumerate(entities):
			if not isinstance(ent, dict):
				report.errors.append(f"world.locations[{idx}].entities[{eidx}] must be object")
				continue
			if "instance_patch" in ent:
				report.errors.append(f"entity[{idx}:{eidx}] uses deprecated field 'instance_patch', use 'component_overrides'")
			if "instance_component_patch" in ent:
				report.errors.append(f"entity[{idx}:{eidx}] uses deprecated field 'instance_component_patch', use 'component_overrides'")
			instance_id = str(ent.get("instance_id", "") or "").strip()
			template_id = str(ent.get("template_id", "") or "").strip()
			if not instance_id:
				report.errors.append(f"entity[{idx}:{eidx}] missing instance_id")
				continue
			if instance_id in entity_ids:
				report.errors.append(f"duplicate entity instance_id: {instance_id}")
			entity_ids.add(instance_id)
			if not template_id:
				report.errors.append(f"entity[{instance_id}] missing template_id")
			else:
				entity_template_refs.append((instance_id, template_id))
			parent = str(ent.get("parent_container", "") or "").strip()
			if parent:
				report.errors.append(f"entity[{instance_id}] in world.locations must not define parent_container; move it to world.entities")

	nested_entities = world.get("entities", []) or []
	if not isinstance(nested_entities, list):
		report.errors.append("world.entities must be a list")
		nested_entities = []
	for eidx, ent in enumerate(nested_entities):
		if not isinstance(ent, dict):
			report.errors.append(f"world.entities[{eidx}] must be object")
			continue
		if "instance_patch" in ent:
			report.errors.append(f"world.entities[{eidx}] uses deprecated field 'instance_patch', use 'component_overrides'")
		if "instance_component_patch" in ent:
			report.errors.append(f"world.entities[{eidx}] uses deprecated field 'instance_component_patch', use 'component_overrides'")
		instance_id = str(ent.get("instance_id", "") or "").strip()
		template_id = str(ent.get("template_id", "") or "").strip()
		if not instance_id:
			report.errors.append(f"world.entities[{eidx}] missing instance_id")
			continue
		if instance_id in entity_ids:
			report.errors.append(f"duplicate entity instance_id: {instance_id}")
		entity_ids.add(instance_id)
		if not template_id:
			report.errors.append(f"entity[{instance_id}] missing template_id")
		else:
			entity_template_refs.append((instance_id, template_id))
		parent = str(ent.get("parent_container", "") or "").strip()
		if not parent:
			report.errors.append(f"world.entities[{eidx}] missing parent_container")
		else:
			parent_refs.append((instance_id, parent))

	for eid, tid in entity_template_refs:
		if tid not in entity_templates:
			report.errors.append(f"entity[{eid}] references missing template '{tid}'")

	for child_id, parent_id in parent_refs:
		if parent_id not in entity_ids:
			report.errors.append(f"entity[{child_id}] parent_container '{parent_id}' not found")

	for rid, recipe in recipes.items():
		if not isinstance(recipe, dict):
			report.errors.append(f"recipe[{rid}] must be object")
			continue
		verb = str(recipe.get("verb", "") or "").strip()
		if not verb:
			report.errors.append(f"recipe[{rid}] missing verb")
		outputs = recipe.get("outputs", []) or []
		if not isinstance(outputs, list):
			report.errors.append(f"recipe[{rid}].outputs must be list")
			outputs = []
		for i, eff in enumerate(outputs):
			_validate_effect(eff, f"recipe[{rid}].outputs[{i}]", report)
		process = recipe.get("process", {}) or {}
		if process and not isinstance(process, dict):
			report.errors.append(f"recipe[{rid}].process must be object")
		if v_mode == "strict":
			tags = recipe.get("target_tags", []) or []
			if not isinstance(tags, list):
				report.errors.append(f"recipe[{rid}].target_tags must be list")

	rules = reactions.get("rules", []) or []
	if not isinstance(rules, list):
		report.errors.append("reactions.rules must be list")
		rules = []
	for i, rule in enumerate(rules):
		if not isinstance(rule, dict):
			report.errors.append(f"reactions.rules[{i}] must be object")
			continue
		on_event = str(rule.get("on_event", "") or "").strip()
		if not on_event:
			report.errors.append(f"reactions.rules[{i}] missing on_event")
		effects = rule.get("effects", []) or []
		if not isinstance(effects, list):
			report.errors.append(f"reactions.rules[{i}].effects must be list")
			effects = []
		for j, eff in enumerate(effects):
			_validate_effect(eff, f"reactions.rules[{i}].effects[{j}]", report)

	if v_mode == "strict":
		if "pathes" in world:
			report.errors.append("world uses deprecated field 'pathes', use 'paths'")
		paths = world.get("paths", []) or []
		if not isinstance(paths, list):
			report.errors.append("world.paths must be list")
		tasks = world.get("tasks", []) or []
		if not isinstance(tasks, list):
			report.errors.append("world.tasks must be list")

	return report
