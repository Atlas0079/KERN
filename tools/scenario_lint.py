from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.data.builder import build_world_state
from KERN.data.loader import DataBundle, load_data_bundle
from KERN.effect_contract import EFFECT_TYPES
from KERN.executor._effect_binder import get_binder_effect_types
from KERN.executor.executor import get_executor_effect_types
from KERN.models.components import __all__ as COMPONENT_EXPORTS

# Import package side effects so built-in progressors are registered.
import KERN.progressors  # noqa: F401
from KERN.progressors import registry as progressor_registry


PARAM_REF_RE = re.compile(r"^param:([A-Za-z0-9_]+)$")
TEMPLATE_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

KNOWN_CONDITION_TYPES = {
	"all",
	"any",
	"not",
	"event_field_eq",
	"has_tag",
	"has_tags",
	"has_component",
	"has_status",
	"compare_property",
	"inventory_contains",
	"inventory_has_tag",
	"same_location",
	"param_eq",
	"compare_fields",
}

RESERVED_ENTITY_REFS = {"self", "target", "event_entity"}

EVENT_FIELDS: dict[str, set[str]] = {
	"TickAdvanced": {"type", "total_ticks", "time"},
	"AdvanceTick": {"type", "entity_id", "ticks"},
	"PropertyModified": {"type", "entity_id", "component", "property", "delta", "new_value"},
	"EntityCreated": {"type", "entity_id", "template_id", "placed"},
	"EntityDestroyed": {"type", "entity_id"},
	"EntityMoved": {"type", "entity_id", "source_id", "destination_id"},
	"EntityDied": {"type", "entity_id", "corpse_id", "reason"},
	"TaskCreated": {"type", "task_id", "target_entity_id"},
	"TaskAssigned": {"type", "task_id", "worker_id"},
	"TaskAccepted": {"type", "task_id", "worker_id", "host_id"},
	"TaskProgressed": {"type", "task_id", "delta", "new_progress", "required"},
	"TaskFinished": {"type", "task_id"},
	"TaskInterrupted": {"type", "task_id", "old_status", "new_status", "reason", "interrupt_source", "interrupt_mode", "worker_id"},
	"TaskCancelled": {"type", "task_id", "old_status", "reason", "interrupt_source", "worker_id"},
	"StatusAdded": {"type", "entity_id", "status_id", "expire_at_tick"},
	"StatusRemoved": {"type", "entity_id", "status_id"},
	"StatusExpired": {"type", "entity_id", "status_id"},
	"ConversationStarted": {"type", "conversation_id", "location_id", "participants", "budget_limit", "budget_used_before"},
	"ConversationSpoken": {"type", "conversation_id", "speaker_id", "location_id", "text", "utterance_index"},
	"ConversationEnded": {"type", "conversation_id", "location_id", "utterance_count", "spoken_count", "budget_used_after", "budget_limit", "transcript", "joined_participants"},
	"ResourcesExchanged": {"type", "source_id", "target_id", "mode", "money_delta", "items_processed", "items_produced_templates"},
	"SimulationAbortRequested": {"type", "reason", "detail", "severity", "stop", "actor_id"},
	"MetaActionApplied": {"type", "entity_id", "action_type", "params", "changed"},
	"DetailsAttached": {"type", "detail_type", "entity_id"},
	"MemoryPatched": {"type", "entity_id"},
	"MemoryNoteAdded": {"type", "entity_id"},
	"EventEmitted": {"type", "event_type", "payload"},
	"TagAdded": {"type", "entity_id", "tag"},
	"TagRemoved": {"type", "entity_id", "tag", "removed"},
}


@dataclass
class Issue:
	severity: str
	where: str
	message: str


@dataclass
class LintContext:
	project_root: Path
	config_path: Path
	env: dict[str, str]
	bundle: DataBundle
	world_json: str
	recipes_jsons: list[str]
	reactions_jsons: list[str]
	entities_dirs: list[str]
	issues: list[Issue] = field(default_factory=list)

	def error(self, where: str, message: str) -> None:
		self.issues.append(Issue("ERROR", str(where), str(message)))

	def warn(self, where: str, message: str) -> None:
		self.issues.append(Issue("WARN", str(where), str(message)))

	def info(self, where: str, message: str) -> None:
		self.issues.append(Issue("INFO", str(where), str(message)))


def _read_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def _cfg_get(cfg: dict[str, str], key: str, default: str = "") -> str:
	return str(cfg.get(str(key), default) or default).strip()


def _split_csv(text: str, default: list[str]) -> list[str]:
	items = [x.strip() for x in str(text or "").split(",") if x.strip()]
	return items if items else list(default)


def _load_env_config(project_root: Path, config_arg: str) -> tuple[dict[str, str], Path]:
	config_path = Path(str(config_arg or "").strip() or "runtime_config.json")
	if not config_path.is_absolute():
		config_path = project_root / config_path
	raw = _read_json(config_path)
	if not isinstance(raw, dict) or not isinstance(raw.get("env"), dict):
		raise ValueError(f"runtime config must be object with env object: {config_path}")
	env: dict[str, str] = {}
	for k, v in dict(raw.get("env", {}) or {}).items():
		key = str(k or "").strip()
		if key and v is not None:
			env[key] = str(v)
	return env, config_path


def _known_component_names() -> set[str]:
	names = {str(x) for x in COMPONENT_EXPORTS if str(x).endswith("Component")}
	names.update({"AgentSetting"})
	return names


def _progressor_ids() -> set[str]:
	reg = getattr(progressor_registry, "_REGISTRY", {}) or {}
	return {str(k) for k in dict(reg).keys() if str(k)}


def _iter_param_refs(node: Any) -> set[str]:
	keys: set[str] = set()
	stack: list[Any] = [node]
	while stack:
		cur = stack.pop()
		if isinstance(cur, dict):
			for v in cur.values():
				stack.append(v)
		elif isinstance(cur, list):
			for v in cur:
				stack.append(v)
		elif isinstance(cur, str):
			m = PARAM_REF_RE.match(cur.strip())
			if m:
				keys.add(str(m.group(1)))
	return keys


def _iter_template_fields(node: Any) -> set[str]:
	keys: set[str] = set()
	stack: list[Any] = [node]
	while stack:
		cur = stack.pop()
		if isinstance(cur, dict):
			for v in cur.values():
				stack.append(v)
		elif isinstance(cur, list):
			for v in cur:
				stack.append(v)
		elif isinstance(cur, str):
			for m in TEMPLATE_RE.finditer(cur):
				keys.add(str(m.group(1)))
	return keys


def _is_param_token(value: Any) -> bool:
	text = str(value or "").strip()
	return text.startswith("param:") and bool(str(text[len("param:") :]).strip())


def _has_nonempty_value(node: dict[str, Any], key: str) -> bool:
	return key in node and bool(str(node.get(key, "") or "").strip())


def _is_entity_ref(value: Any) -> bool:
	text = str(value or "").strip()
	if not text:
		return False
	return text in RESERVED_ENTITY_REFS or text.startswith("param:") or text.startswith("event.")


def _entity_ids_from_world(world: dict[str, Any]) -> set[str]:
	ids: set[str] = set()
	for loc in list(world.get("locations", []) or []):
		if not isinstance(loc, dict):
			continue
		for ent in list(loc.get("entities", []) or []):
			if isinstance(ent, dict) and str(ent.get("instance_id", "") or "").strip():
				ids.add(str(ent.get("instance_id")).strip())
	for ent in list(world.get("entities", []) or []):
		if isinstance(ent, dict) and str(ent.get("instance_id", "") or "").strip():
			ids.add(str(ent.get("instance_id")).strip())
	return ids


def _location_ids_from_world(world: dict[str, Any]) -> set[str]:
	return {str(x.get("location_id", "") or "").strip() for x in list(world.get("locations", []) or []) if isinstance(x, dict) and str(x.get("location_id", "") or "").strip()}


def _entity_template_has_component(bundle: DataBundle, template_id: str, component_name: str) -> bool:
	template = dict((bundle.entity_templates or {}).get(str(template_id), {}) or {})
	components = template.get("components", {}) or {}
	return isinstance(components, dict) and str(component_name) in components


def _validate_world_shape(ctx: LintContext) -> None:
	world = ctx.bundle.world if isinstance(ctx.bundle.world, dict) else {}
	if not isinstance(ctx.bundle.entity_templates, dict) or not ctx.bundle.entity_templates:
		ctx.error("entities", "no entity templates loaded")
	if not isinstance(world.get("locations", []), list):
		ctx.error(ctx.world_json, "locations must be list")
		return
	location_ids: set[str] = set()
	entity_ids: set[str] = set()
	for idx, loc in enumerate(list(world.get("locations", []) or [])):
		where = f"{ctx.world_json}.locations[{idx}]"
		if not isinstance(loc, dict):
			ctx.error(where, "location must be object")
			continue
		lid = str(loc.get("location_id", "") or "").strip()
		if not lid:
			ctx.error(where, "missing location_id")
		elif lid in location_ids:
			ctx.error(where, f"duplicate location_id: {lid}")
		else:
			location_ids.add(lid)
		if not isinstance(loc.get("entities", []), list):
			ctx.error(where, "entities must be list")
			continue
		for eidx, ent in enumerate(list(loc.get("entities", []) or [])):
			ewhere = f"{where}.entities[{eidx}]"
			_validate_world_entity_snapshot(ctx, ent, ewhere, entity_ids, allow_parent=False)
	for idx, ent in enumerate(list(world.get("entities", []) or [])):
		_validate_world_entity_snapshot(ctx, ent, f"{ctx.world_json}.entities[{idx}]", entity_ids, allow_parent=True)
	for idx, path in enumerate(list(world.get("paths", []) or [])):
		where = f"{ctx.world_json}.paths[{idx}]"
		if not isinstance(path, dict):
			ctx.error(where, "path must be object")
			continue
		for key in ["path_id", "from_location_id", "to_location_id"]:
			if not str(path.get(key, "") or "").strip():
				ctx.error(where, f"missing {key}")
		for key in ["from_location_id", "to_location_id"]:
			lid = str(path.get(key, "") or "").strip()
			if lid and lid not in location_ids:
				ctx.error(where, f"{key} references unknown location: {lid}")
	for idx, task in enumerate(list(world.get("tasks", []) or [])):
		_validate_world_task(ctx, task, f"{ctx.world_json}.tasks[{idx}]", entity_ids)
	_validate_parent_containers(ctx, world, entity_ids)


def _validate_world_entity_snapshot(ctx: LintContext, ent: Any, where: str, entity_ids: set[str], allow_parent: bool) -> None:
	if not isinstance(ent, dict):
		ctx.error(where, "entity snapshot must be object")
		return
	instance_id = str(ent.get("instance_id", "") or "").strip()
	template_id = str(ent.get("template_id", "") or "").strip()
	if not instance_id:
		ctx.error(where, "missing instance_id")
	elif instance_id in entity_ids:
		ctx.error(where, f"duplicate instance_id: {instance_id}")
	else:
		entity_ids.add(instance_id)
	if not template_id:
		ctx.error(where, "missing template_id")
	elif template_id not in (ctx.bundle.entity_templates or {}):
		ctx.error(where, f"template_id references unknown template: {template_id}")
	parent = str(ent.get("parent_container", "") or "").strip()
	if parent and not allow_parent:
		ctx.error(where, "root location entity must not define parent_container")
	overrides = ent.get("component_overrides", {}) or {}
	if overrides and not isinstance(overrides, dict):
		ctx.error(where, "component_overrides must be object")
		return
	for comp_name in dict(overrides).keys():
		if str(comp_name) not in _known_component_names():
			ctx.warn(f"{where}.component_overrides", f"unknown component override name: {comp_name}")


def _validate_parent_containers(ctx: LintContext, world: dict[str, Any], entity_ids: set[str]) -> None:
	template_by_entity: dict[str, str] = {}
	for loc in list(world.get("locations", []) or []):
		if not isinstance(loc, dict):
			continue
		for ent in list(loc.get("entities", []) or []):
			if isinstance(ent, dict):
				template_by_entity[str(ent.get("instance_id", "") or "")] = str(ent.get("template_id", "") or "")
	for ent in list(world.get("entities", []) or []):
		if isinstance(ent, dict):
			template_by_entity[str(ent.get("instance_id", "") or "")] = str(ent.get("template_id", "") or "")
	for idx, ent in enumerate(list(world.get("entities", []) or [])):
		if not isinstance(ent, dict):
			continue
		parent = str(ent.get("parent_container", "") or "").strip()
		where = f"{ctx.world_json}.entities[{idx}]"
		if not parent:
			ctx.error(where, "nested entity missing parent_container")
			continue
		if parent not in entity_ids:
			ctx.error(where, f"parent_container references unknown entity: {parent}")
			continue
		parent_tpl = template_by_entity.get(parent, "")
		if parent_tpl and not _entity_template_has_component(ctx.bundle, parent_tpl, "ContainerComponent"):
			ctx.error(where, f"parent_container '{parent}' template has no ContainerComponent")


def _validate_world_task(ctx: LintContext, task: Any, where: str, entity_ids: set[str]) -> None:
	if not isinstance(task, dict):
		ctx.error(where, "task must be object")
		return
	for key in ["task_id", "task_type", "target_entity_id", "current_agent_id", "progressor_id"]:
		if not str(task.get(key, "") or "").strip():
			ctx.error(where, f"missing {key}")
	for key in ["target_entity_id", "current_agent_id"]:
		eid = str(task.get(key, "") or "").strip()
		if eid and eid not in entity_ids:
			ctx.error(where, f"{key} references unknown entity: {eid}")
	pid = str(task.get("progressor_id", "") or "").strip()
	if pid and pid not in _progressor_ids():
		ctx.error(where, f"unknown progressor_id: {pid}")
	_validate_bundle(ctx, task.get("completion_bundle", {}), f"{where}.completion_bundle")
	_validate_bundle(ctx, task.get("tick_bundle", {}), f"{where}.tick_bundle")


def _validate_component_templates(ctx: LintContext) -> None:
	for tid, template in (ctx.bundle.entity_templates or {}).items():
		where = f"template[{tid}]"
		if not isinstance(template, dict):
			ctx.error(where, "template must be object")
			continue
		components = template.get("components", {}) or {}
		if not isinstance(components, dict):
			ctx.error(where, "components must be object")
			continue
		for comp_name, comp_data in components.items():
			cname = str(comp_name)
			if cname not in _known_component_names():
				ctx.warn(where, f"unknown component name will be loaded as UnknownComponent: {cname}")
				continue
			if comp_data is not None and not isinstance(comp_data, dict):
				ctx.error(f"{where}.components.{cname}", "component data must be object")
				continue
			if cname == "EdibleComponent" and isinstance(comp_data, dict):
				_validate_bundle(ctx, comp_data.get("on_consume_bundle", {}), f"{where}.components.{cname}.on_consume_bundle")


def _validate_query(ctx: LintContext, query: Any, where: str) -> None:
	if not isinstance(query, dict):
		ctx.error(where, "query must be object")
		return
	source = str(query.get("from", "entities") or "entities").strip()
	if source != "entities":
		ctx.error(where, "query.from must be entities")
	where_clause = query.get("where", {}) or {}
	_validate_condition(ctx, where_clause, f"{where}.where")
	select = query.get("select", []) or []
	if "select" in query and not isinstance(select, list):
		ctx.error(where, "query.select must be list")
	order_by = query.get("order_by", {}) or {}
	if "order_by" in query:
		if not isinstance(order_by, dict):
			ctx.error(where, "query.order_by must be object")
		else:
			field = str(order_by.get("field", "") or "").strip()
			direction = str(order_by.get("direction", "asc") or "asc").strip().lower()
			if not field:
				ctx.error(where, "query.order_by.field is required")
			if direction not in {"asc", "desc"}:
				ctx.error(where, "query.order_by.direction must be asc/desc")
	if "limit" in query:
		try:
			if int(query.get("limit")) < 0:
				ctx.error(where, "query.limit must be non-negative")
		except Exception:
			ctx.error(where, "query.limit must be integer")



def _validate_bundle(ctx: LintContext, bundle: Any, where: str) -> None:
	if not isinstance(bundle, dict):
		ctx.error(where, "bundle must be object")
		return
	effects = bundle.get("effects", []) or []
	if "react_per_effect" in bundle and not isinstance(bundle.get("react_per_effect"), bool):
		ctx.error(f"{where}.react_per_effect", "bundle.react_per_effect must be bool")
	if not isinstance(effects, list):
		ctx.error(where, "bundle.effects must be list")
		return
	for idx, eff in enumerate(effects):
		_validate_effect(ctx, eff, f"{where}.effects[{idx}]")


def _validate_condition(ctx: LintContext, condition: Any, where: str, known_event_type: str = "") -> None:
	if condition is None or condition == {}:
		return
	if not isinstance(condition, dict):
		ctx.error(where, "condition must be object")
		return
	c_type = str(condition.get("type", "") or "").strip()
	if not c_type:
		ctx.error(where, "condition missing type")
		return
	if c_type not in KNOWN_CONDITION_TYPES:
		ctx.error(where, f"unknown condition type: {c_type}")
		return
	if c_type in {"all", "any"}:
		items = condition.get("conditions", [])
		if not isinstance(items, list):
			ctx.error(where, "conditions must be list")
			return
		for idx, item in enumerate(items):
			_validate_condition(ctx, item, f"{where}.conditions[{idx}]", known_event_type)
		return
	if c_type == "not":
		_validate_condition(ctx, condition.get("condition", {}), f"{where}.condition", known_event_type)
		return
	if c_type == "event_field_eq":
		field = str(condition.get("field", "") or "").strip()
		if not field:
			ctx.error(where, "event_field_eq missing field")
		_validate_event_field(ctx, known_event_type, field, where)
		return
	if c_type in {"has_tag", "has_component", "has_status", "compare_property"}:
		_validate_entity_ref(ctx, condition.get("target", "self"), where, "target")
	if c_type == "has_tags":
		_validate_entity_ref(ctx, condition.get("target", "self"), where, "target")
		if not isinstance(condition.get("tags", []), list) or not condition.get("tags"):
			ctx.error(where, "has_tags requires non-empty tags list")
	if c_type == "has_component":
		comp = str(condition.get("component", "") or "").strip()
		if not comp:
			ctx.error(where, "has_component missing component")
		elif comp not in _known_component_names():
			ctx.warn(where, f"has_component references unknown component: {comp}")
	if c_type == "compare_property":
		comp = str(condition.get("component", "") or "").strip()
		prop = str(condition.get("property", "") or "").strip()
		if not comp:
			ctx.error(where, "compare_property missing component")
		elif comp not in _known_component_names():
			ctx.warn(where, f"compare_property references unknown component: {comp}")
		if not prop:
			ctx.error(where, "compare_property missing property")
	if c_type == "inventory_contains":
		_validate_entity_ref(ctx, condition.get("owner", "self"), where, "owner")
		_validate_entity_ref(ctx, condition.get("item_ref", "target"), where, "item_ref")
	if c_type == "inventory_has_tag":
		_validate_entity_ref(ctx, condition.get("owner", "self"), where, "owner")
		if not str(condition.get("tag", "") or "").strip():
			ctx.error(where, "inventory_has_tag missing tag")
	if c_type == "same_location":
		_validate_entity_ref(ctx, condition.get("left", "self"), where, "left")
		_validate_entity_ref(ctx, condition.get("right", "target"), where, "right")
	if c_type == "param_eq" and not str(condition.get("key", "") or "").strip():
		ctx.error(where, "param_eq missing key")
	if c_type == "compare_fields":
		for key in ["left", "right"]:
			ref = str(condition.get(key, "") or "").strip()
			if not ref:
				ctx.error(where, f"compare_fields missing {key}")
			elif ref.startswith("event."):
				_validate_event_field(ctx, known_event_type, ref[len("event.") :], where)


def _validate_event_field(ctx: LintContext, event_type: str, field: str, where: str) -> None:
	if not field or not event_type:
		return
	known = EVENT_FIELDS.get(str(event_type), set())
	if known and field not in known:
		ctx.warn(where, f"event field '{field}' is not known for event '{event_type}'")


def _validate_entity_ref(ctx: LintContext, value: Any, where: str, field_name: str) -> None:
	text = str(value or "").strip()
	if not text:
		ctx.error(where, f"{field_name} is empty")
		return
	if text in RESERVED_ENTITY_REFS or text.startswith("param:") or text.startswith("event."):
		return
	world_ids = _entity_ids_from_world(ctx.bundle.world if isinstance(ctx.bundle.world, dict) else {})
	if text not in world_ids:
		ctx.warn(where, f"{field_name} literal entity ref not found in initial world: {text}")


def _validate_effect(ctx: LintContext, effect: Any, where: str) -> None:
	if not isinstance(effect, dict):
		ctx.error(where, "effect must be object")
		return
	eff = str(effect.get("effect", "") or "").strip()
	if not eff:
		ctx.error(where, "missing effect")
		return
	if eff not in EFFECT_TYPES:
		ctx.error(where, f"unknown effect: {eff}")
		return
	if eff not in get_binder_effect_types():
		ctx.error(where, f"effect binder missing: {eff}")
	if eff not in get_executor_effect_types():
		ctx.error(where, f"effect executor missing: {eff}")
	_validate_effect_required_fields(ctx, eff, effect, where)
	_validate_deprecated_refs(ctx, effect, where)
	_validate_effect_specific_refs(ctx, eff, effect, where)


def _validate_effect_required_fields(ctx: LintContext, eff: str, effect: dict[str, Any], where: str) -> None:
	if eff == "MoveEntity":
		for key in ["entity_ref", "from_ref", "to_ref"]:
			if not _has_nonempty_value(effect, key):
				ctx.error(where, f"MoveEntity missing {key}")
		legacy = [k for k in ["entity_id", "source_id", "destination_id", "target", "source", "destination"] if k in effect]
		if legacy:
			ctx.error(where, f"MoveEntity uses deprecated keys {sorted(legacy)}, use entity_ref/from_ref/to_ref")
	if eff == "ModifyProperty":
		for key in ["target", "component", "property"]:
			if not _has_nonempty_value(effect, key):
				ctx.error(where, f"ModifyProperty missing {key}")
		has_change = "change" in effect
		has_value = "value" in effect
		if not has_change and not has_value:
			ctx.error(where, "ModifyProperty requires exactly one of change/value")
		if has_change and has_value:
			ctx.error(where, "ModifyProperty cannot contain both change and value")
	if eff == "CreateEntity":
		if not _has_nonempty_value(effect, "template"):
			ctx.error(where, "CreateEntity missing template")
		if not isinstance(effect.get("destination", None), dict):
			ctx.error(where, "CreateEntity missing destination object")
	if eff == "CreateTask":
		recipe = effect.get("recipe", {})
		if not isinstance(recipe, dict) or not recipe:
			ctx.error(where, "CreateTask missing recipe object")
		assign_to = str(effect.get("assign_to", "") or "").strip()
		if assign_to not in {"self", "target"}:
			ctx.error(where, "CreateTask assign_to must be self/target")
	if eff == "InvokeBundle":
		has_inline_bundle = "bundle" in effect
		has_component_bundle = "component" in effect or "property" in effect
		if not has_inline_bundle and not has_component_bundle:
			ctx.error(where, "InvokeBundle requires bundle or component/property")
		if has_inline_bundle:
			_validate_bundle(ctx, effect.get("bundle", {}), f"{where}.bundle")
		if has_component_bundle:
			if not _has_nonempty_value(effect, "target"):
				ctx.error(where, "InvokeBundle(component) missing target")
			if not _has_nonempty_value(effect, "component"):
				ctx.error(where, "InvokeBundle(component) missing component")
			if not _has_nonempty_value(effect, "property"):
				ctx.error(where, "InvokeBundle(component) missing property")
	if eff == "ApplyToQuery":
		_validate_query(ctx, effect.get("query", {}), f"{where}.query")
		_validate_bundle(ctx, effect.get("bundle", {}), f"{where}.bundle")
		for idx, inner in enumerate(list(((effect.get("bundle", {}) or {}).get("effects", []) or []))):
			if isinstance(inner, dict) and str(inner.get("effect", "") or "") == "ApplyToQuery":
				ctx.warn(f"{where}.bundle.effects[{idx}]", "nested ApplyToQuery can be expensive; verify it is intentional")
		if "limit" in effect:
			try:
				if int(effect.get("limit")) < 0:
					ctx.error(where, "ApplyToQuery limit must be non-negative")
			except Exception:
				ctx.error(where, "ApplyToQuery limit must be integer")
	if eff == "AgentControlTick" and "max_actions_in_tick" not in effect:
		ctx.error(where, "AgentControlTick missing max_actions_in_tick")
	if eff == "WorkerTick" and "ticks" not in effect:
		ctx.error(where, "WorkerTick missing ticks")
	if eff == "ApplyMetaAction":
		for key in ["target", "action_type", "params"]:
			if key not in effect:
				ctx.error(where, f"ApplyMetaAction missing {key}")
		if "params" in effect and not isinstance(effect.get("params"), dict):
			ctx.error(where, "ApplyMetaAction params must be object")
	if eff == "AttachDetails":
		detail_type = str(effect.get("detail_type", "") or "").strip()
		if detail_type not in {"entity", "interrupt_preset"}:
			ctx.error(where, "AttachDetails detail_type must be entity/interrupt_preset")
		if detail_type == "entity" and not _has_nonempty_value(effect, "target"):
			ctx.error(where, "AttachDetails(entity) missing target")
	if eff == "EmitEvent":
		if not _has_nonempty_value(effect, "event_type"):
			ctx.error(where, "EmitEvent missing event_type")
		if "payload" not in effect:
			ctx.error(where, "EmitEvent missing payload")
		elif not isinstance(effect.get("payload"), dict):
			ctx.error(where, "EmitEvent payload must be object")
	if eff == "ExchangeResources":
		for key in ["source", "target", "transfer_mode", "consume_items", "consume_money", "produce_items", "produce_money"]:
			if key not in effect:
				ctx.error(where, f"ExchangeResources missing {key}")
		mode = str(effect.get("transfer_mode", "") or "").strip().lower()
		if mode and mode not in {"destroy", "transfer"}:
			ctx.error(where, "ExchangeResources transfer_mode must be destroy/transfer")
		for key in ["consume_items", "produce_items"]:
			if key in effect and not isinstance(effect.get(key), list):
				ctx.error(where, f"ExchangeResources {key} must be list")
	if eff == "AbortSimulation":
		for key in ["reason", "detail", "severity", "stop"]:
			if key not in effect:
				ctx.error(where, f"AbortSimulation missing {key}")
		severity = str(effect.get("severity", "") or "").strip().lower()
		if severity and not severity.startswith("param:") and severity not in {"info", "warning", "error", "fatal"}:
			ctx.error(where, "AbortSimulation severity must be info/warning/error/fatal")


def _validate_deprecated_refs(ctx: LintContext, effect: dict[str, Any], where: str) -> None:
	deprecated_refs: list[str] = []
	stack: list[Any] = [effect]
	while stack:
		item = stack.pop()
		if isinstance(item, dict):
			for value in item.values():
				stack.append(value)
		elif isinstance(item, list):
			for value in item:
				stack.append(value)
		elif isinstance(item, str):
			ref = str(item).strip()
			if ref == "agent":
				deprecated_refs.append("agent->self")
			elif ref.startswith("parameter:"):
				deprecated_refs.append("parameter:->param:")
			elif ref == "event.entity_id":
				deprecated_refs.append("event.entity_id->event_entity")
	if deprecated_refs:
		ctx.error(where, f"deprecated refs {sorted(set(deprecated_refs))}")


def _validate_effect_specific_refs(ctx: LintContext, eff: str, effect: dict[str, Any], where: str) -> None:
	if eff in {"ModifyProperty", "AddTag", "RemoveTag", "AddStatus", "RemoveStatus", "DestroyEntity", "KillEntity", "AcceptTask", "ApplyMetaAction"}:
		key = "target"
		if key in effect:
			_validate_entity_ref(ctx, effect.get(key), where, key)
	if eff == "ModifyProperty":
		comp = str(effect.get("component", "") or "").strip()
		if comp and comp not in _known_component_names():
			ctx.warn(where, f"ModifyProperty references unknown component: {comp}")
	if eff == "CreateEntity":
		template = str(effect.get("template", "") or "").strip()
		if template and template not in (ctx.bundle.entity_templates or {}):
			ctx.error(where, f"CreateEntity template not found: {template}")
		dest = effect.get("destination", {}) or {}
		if isinstance(dest, dict):
			dtype = str(dest.get("type", "") or "").strip()
			if dtype not in {"location", "container"}:
				ctx.error(where, "CreateEntity destination.type must be location/container")
			target = str(dest.get("target", "") or "").strip()
			if dtype == "location" and target and not _is_entity_ref(target) and target not in _location_ids_from_world(ctx.bundle.world):
				ctx.error(where, f"CreateEntity destination location not found: {target}")
	if eff == "KillEntity":
		template = str(effect.get("corpse_template", "") or "").strip()
		if template and template not in (ctx.bundle.entity_templates or {}):
			ctx.error(where, f"KillEntity corpse_template not found: {template}")
	if eff == "MoveEntity":
		for key in ["entity_ref", "from_ref", "to_ref"]:
			if key in effect and not _is_entity_ref(effect.get(key)):
				text = str(effect.get(key, "") or "").strip()
				if key in {"from_ref", "to_ref"} and text in _location_ids_from_world(ctx.bundle.world):
					continue
				ctx.warn(where, f"MoveEntity {key} is a literal ref; verify it is intentional: {text}")
	if eff == "ExchangeResources":
		for item in list(effect.get("produce_items", []) or []):
			text = str(item or "").strip()
			if text and not text.startswith("param:") and text not in (ctx.bundle.entity_templates or {}):
				ctx.error(where, f"ExchangeResources produce_items template not found: {text}")


def _validate_recipe(ctx: LintContext, rid: str, recipe: Any) -> None:
	where = f"recipe[{rid}]"
	if not isinstance(recipe, dict):
		ctx.error(where, "recipe must be object")
		return
	verb = str(recipe.get("verb", "") or "").strip()
	if not verb:
		ctx.error(where, "missing verb")
	selector = recipe.get("selector", {}) or {}
	condition = recipe.get("condition", {}) or {}
	_validate_condition(ctx, selector, f"{where}.selector")
	_validate_condition(ctx, condition, f"{where}.condition")
	process = recipe.get("process", {}) or {}
	if process and not isinstance(process, dict):
		ctx.error(where, "process must be object")
		process = {}
	_validate_process_duration(ctx, process, where)
	duration = process.get("duration", None) if isinstance(process, dict) else None
	is_duration = isinstance(duration, dict) and bool(duration)
	if is_duration:
		assign_to = str(process.get("assign_to", "") or "").strip()
		if assign_to not in {"self", "target"}:
			ctx.error(where, "duration recipe requires process.assign_to self/target")
		progression = recipe.get("progression", {}) or process.get("progression", {}) or {}
		if not isinstance(progression, dict) or not progression:
			ctx.error(where, "duration recipe requires progression object")
		else:
			_validate_progression(ctx, progression, f"{where}.progression")
	_validate_bundle(ctx, recipe.get("bundle", {}), f"{where}.bundle")
	for field in ["narrative_success", "narrative_fail"]:
		if field in recipe:
			_allowed = {"actor", "target", "reason", "to_location_id", "source_location_id"}
			for name in sorted(_iter_template_fields(recipe.get(field, "")) - _allowed):
				if name not in _iter_param_refs(recipe) and name not in {"actor_name", "target_name"}:
					ctx.warn(f"{where}.{field}", f"template field may have no source: {name}")


def _validate_progression(ctx: LintContext, progression: dict[str, Any], where: str) -> None:
	pid = str(progression.get("progressor", progression.get("progressor_id", "")) or "").strip()
	if not pid:
		ctx.error(where, "missing progressor")
	elif pid not in _progressor_ids():
		ctx.error(where, f"unknown progressor: {pid}")
	params = progression.get("params", {}) or {}
	if params and not isinstance(params, dict):
		ctx.error(where, "params must be object")
	elif pid == "Linear":
		_validate_linear_progression_params(ctx, params, where)
	_validate_bundle(ctx, progression.get("tick_bundle", {}), f"{where}.tick_bundle")


def _validate_recipes(ctx: LintContext) -> None:
	verbs: dict[str, list[str]] = {}
	for rid, recipe in (ctx.bundle.recipes or {}).items():
		if isinstance(recipe, dict):
			verb = str(recipe.get("verb", "") or "").strip()
			if verb:
				verbs.setdefault(verb, []).append(str(rid))
		_validate_recipe(ctx, str(rid), recipe)
	for verb, ids in sorted(verbs.items()):
		if len(ids) <= 1:
			continue
		for rid in ids:
			recipe = ctx.bundle.recipes.get(rid, {}) if isinstance(ctx.bundle.recipes, dict) else {}
			if isinstance(recipe, dict) and not isinstance(recipe.get("selector", None), dict) and not isinstance(recipe.get("condition", None), dict):
				ctx.warn(f"recipe[{rid}]", f"verb '{verb}' is duplicated and recipe has no selector/condition")


def _validate_process_duration(ctx: LintContext, process: Any, where: str) -> None:
	if not isinstance(process, dict):
		return
	duration = process.get("duration", None)
	if duration is None:
		return
	if not isinstance(duration, dict) or not duration:
		ctx.error(where, "process.duration must be object")
		return
	mode = str(duration.get("mode", "") or "").strip().lower()
	if mode not in {"fixed", "param", "path_distance"}:
		ctx.error(where, "process.duration.mode must be fixed/param/path_distance")
		return
	if mode == "fixed":
		if "value" not in duration:
			ctx.error(where, "process.duration.value is required for mode=fixed")
		return
	if mode == "param":
		if not _is_param_token(duration.get("from_param", "")):
			ctx.error(where, "process.duration.from_param must be param:<name> for mode=param")
		return
	if mode == "path_distance":
		if not _is_param_token(duration.get("to_param", "")):
			ctx.error(where, "process.duration.to_param must be param:<name> for mode=path_distance")


def _validate_linear_progression_params(ctx: LintContext, params: Any, where: str) -> None:
	if not isinstance(params, dict):
		ctx.error(where, "progression.params must be object")
		return
	if "progress_contributors" in params:
		ctx.error(where, "progression.params.progress_contributors is removed, use add_terms/mul_terms")
	for key in ["add_terms", "mul_terms"]:
		terms = params.get(key, [])
		if terms is None:
			terms = []
		if not isinstance(terms, list):
			ctx.error(where, f"progression.params.{key} must be list")
			continue
		for idx, term in enumerate(terms):
			twhere = f"{where}.params.{key}[{idx}]"
			if not isinstance(term, dict):
				ctx.error(twhere, "term must be object")
				continue
			when = term.get("when", {})
			if when is None:
				when = {}
			if not isinstance(when, dict):
				ctx.error(twhere, "when must be object")
			else:
				_validate_condition(ctx, when, f"{twhere}.when")
			has_value = "value" in term
			has_read = "read" in term
			if has_value == has_read:
				ctx.error(twhere, "term must contain exactly one of value/read")
			if has_read:
				read = term.get("read")
				if not isinstance(read, dict):
					ctx.error(twhere, "read must be object")
				else:
					component = str(read.get("component", "") or "").strip()
					prop = str(read.get("property", "") or "").strip()
					if not component:
						ctx.error(twhere, "read.component is required")
					elif component not in _known_component_names():
						ctx.warn(twhere, f"read.component references unknown component: {component}")
					if not prop:
						ctx.error(twhere, "read.property is required")
	clamp = params.get("clamp", None)
	if clamp is not None and not isinstance(clamp, dict):
		ctx.error(where, "progression.params.clamp must be object")


def _validate_reactions(ctx: LintContext) -> None:
	reactions = ctx.bundle.reactions if isinstance(ctx.bundle.reactions, dict) else {}
	rules = reactions.get("rules", []) if isinstance(reactions, dict) else []
	if not isinstance(rules, list):
		ctx.error("reactions.rules", "rules must be list")
		return
	seen: set[str] = set()
	for idx, rule in enumerate(rules):
		where = f"reactions.rules[{idx}]"
		if not isinstance(rule, dict):
			ctx.error(where, "rule must be object")
			continue
		rid = str(rule.get("id", "") or "").strip()
		if not rid:
			ctx.warn(where, "rule missing id")
		elif rid in seen:
			ctx.error(where, f"duplicate reaction id: {rid}")
		else:
			seen.add(rid)
		event_type = str(rule.get("on_event", "") or "").strip()
		if not event_type:
			ctx.warn(where, "rule has no on_event and may match all events")
		elif event_type not in EVENT_FIELDS:
			ctx.warn(where, f"on_event is not in known event catalog: {event_type}")
		_validate_condition(ctx, rule.get("selector", {}) or {}, f"{where}.selector", event_type)
		_validate_condition(ctx, rule.get("condition", {}) or {}, f"{where}.condition", event_type)
		_validate_bundle(ctx, rule.get("bundle", {}), f"{where}.bundle")


def lint_bundle(
	project_root: Path,
	config_path: Path,
	env: dict[str, str],
	bundle: DataBundle,
	world_json: str,
	recipes_jsons: list[str],
	reactions_jsons: list[str],
	entities_dirs: list[str],
) -> LintContext:
	ctx = LintContext(
		project_root=project_root,
		config_path=config_path,
		env=env,
		bundle=bundle,
		world_json=world_json,
		recipes_jsons=recipes_jsons,
		reactions_jsons=reactions_jsons,
		entities_dirs=entities_dirs,
	)
	ctx.info("config", f"loaded {config_path.name}")
	ctx.info("data", f"world={world_json}, recipes={len(bundle.recipes or {})}, reactions={len((bundle.reactions or {}).get('rules', []) or [])}, templates={len(bundle.entity_templates or {})}")
	_validate_world_shape(ctx)
	_validate_component_templates(ctx)
	_validate_recipes(ctx)
	_validate_reactions(ctx)
	try:
		build_world_state(bundle.world, bundle.entity_templates, bundle.recipes)
	except Exception as e:
		ctx.error("build_world_state", str(e))
	return ctx


def lint_config(project_root: Path, config_path: str) -> LintContext:
	env, resolved_config = _load_env_config(project_root, config_path)
	world_json = _cfg_get(env, "WORLD_JSON", "World.json")
	recipes_jsons = _split_csv(_cfg_get(env, "RECIPES_JSONS", "Recipes.json"), ["Recipes.json"])
	reactions_jsons = _split_csv(_cfg_get(env, "REACTIONS_JSONS", "Reactions.json"), ["Reactions.json"])
	entities_dirs = _split_csv(_cfg_get(env, "ENTITIES_DIRS", "Entities"), ["Entities"])
	bundle = load_data_bundle(
		project_root,
		recipes_jsons=recipes_jsons,
		reactions_jsons=reactions_jsons,
		entities_dirs=entities_dirs,
		world_json=world_json,
	)
	return lint_bundle(
		project_root=project_root,
		config_path=resolved_config,
		env=env,
		bundle=bundle,
		world_json=world_json,
		recipes_jsons=recipes_jsons,
		reactions_jsons=reactions_jsons,
		entities_dirs=entities_dirs,
	)


def run_lint(project_root: Path, config_path: str) -> int:
	ctx = lint_config(project_root, config_path)
	_print_report(ctx)
	return 1 if any(x.severity == "ERROR" for x in ctx.issues) else 0


def _print_report(ctx: LintContext) -> None:
	counts = {
		"ERROR": len([x for x in ctx.issues if x.severity == "ERROR"]),
		"WARN": len([x for x in ctx.issues if x.severity == "WARN"]),
		"INFO": len([x for x in ctx.issues if x.severity == "INFO"]),
	}
	print(json.dumps({"summary": counts}, ensure_ascii=False))
	for issue in ctx.issues:
		print(f"{issue.severity}\t{issue.where}\t{issue.message}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Static scenario data linter")
	parser.add_argument("--project-root", default=".", help="Project root path")
	parser.add_argument("--config", default="runtime_config.werewolf.json", help="runtime_config*.json path")
	args = parser.parse_args()
	try:
		code = run_lint(Path(args.project_root).resolve(), str(args.config))
	except Exception as e:
		print(json.dumps({"summary": {"ERROR": 1, "WARN": 0, "INFO": 0}}, ensure_ascii=False))
		print(f"ERROR\tstartup\t{e}")
		code = 1
	sys.exit(code)


if __name__ == "__main__":
	main()
