from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from newserver.data.builder import build_world_state
from newserver.data.loader import load_data_bundle, load_json
from newserver.entity_ref_resolver import resolve_entity
from newserver.effect_contract import EFFECT_TYPES
from newserver.executor._effect_binder import BindError, bind_effect_input, get_binder_effect_types
from newserver.executor.executor import WorldExecutor, get_executor_effect_types
from newserver.models.components import CooldownComponent, TagComponent, UnknownComponent
from newserver.interaction.engine import InteractionEngine
from newserver.sim.trigger_system import TriggerSystem


PARAM_REF_RE = re.compile(r"^param:([A-Za-z0-9_]+)$")
TEMPLATE_RE = re.compile(r"^\{([A-Za-z0-9_]+)\}$")


@dataclass
class ProbeResult:
	registry_errors: list[str]
	bind_errors: list[dict[str, Any]]
	exec_errors: list[dict[str, Any]]
	recipe_success: set[str]
	recipe_failed: dict[str, list[str]]
	reaction_triggered: set[str]
	reaction_untriggered: set[str]


@dataclass
class Runtime:
	ws: Any
	executor: WorldExecutor
	engine: InteractionEngine
	trigger: TriggerSystem


def _iter_effect_dicts(node: Any, source: str) -> list[tuple[str, dict[str, Any]]]:
	out: list[tuple[str, dict[str, Any]]] = []
	stack: list[tuple[str, Any]] = [(source, node)]
	while stack:
		cur_source, cur = stack.pop()
		if isinstance(cur, dict):
			if isinstance(cur.get("effect"), str):
				out.append((cur_source, dict(cur)))
			for k, v in cur.items():
				stack.append((f"{cur_source}.{k}", v))
		elif isinstance(cur, list):
			for i, v in enumerate(cur):
				stack.append((f"{cur_source}[{i}]", v))
	return out


def _collect_effects(bundle: Any) -> list[tuple[str, dict[str, Any]]]:
	all_effects: list[tuple[str, dict[str, Any]]] = []
	all_effects.extend(_iter_effect_dicts(bundle.recipes, "recipes"))
	all_effects.extend(_iter_effect_dicts(bundle.reactions, "reactions"))
	return all_effects


def _new_runtime(bundle: Any) -> Runtime:
	build = build_world_state(bundle.world, bundle.entity_templates, bundle.recipes)
	ws = build.world_state
	executor = WorldExecutor(entity_templates=bundle.entity_templates)
	engine = InteractionEngine(recipe_db=bundle.recipes)
	trigger = TriggerSystem(rules=list((bundle.reactions or {}).get("rules", []) or []))
	ws.services["execute"] = lambda eff, ctx: executor.execute(ws, eff, ctx)
	return Runtime(ws=ws, executor=executor, engine=engine, trigger=trigger)


def _all_entities(ws: Any) -> list[Any]:
	return list((getattr(ws, "entities", {}) or {}).values())


def _all_locations(ws: Any) -> list[Any]:
	return list((getattr(ws, "locations", {}) or {}).values())


def _entity_ids_by_tag(ws: Any, tag: str) -> list[str]:
	ids: list[str] = []
	for ent in _all_entities(ws):
		try:
			if ent.has_tag(str(tag)):
				ids.append(str(ent.entity_id))
		except Exception:
			continue
	return ids


def _inventory_item_ids(entity: Any) -> list[str]:
	try:
		cc = entity.get_component("ContainerComponent")
		if cc is None or not hasattr(cc, "get_all_item_ids"):
			return []
		return [str(x) for x in list(cc.get_all_item_ids() or [])]
	except Exception:
		return []


def _extract_param_keys(node: Any) -> set[str]:
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
			t = TEMPLATE_RE.match(cur.strip())
			if t:
				keys.add(str(t.group(1)))
	return keys


def _pick_first(items: list[str], fallback: str = "") -> str:
	return str(items[0]) if items else str(fallback)


def _build_base_context(ws: Any) -> dict[str, Any]:
	agent_ids = _entity_ids_by_tag(ws, "agent")
	self_id = _pick_first(agent_ids)
	target_id = _pick_first([x for x in agent_ids if x != self_id], self_id)
	locations = _all_locations(ws)
	loc_id = str(getattr(locations[0], "location_id", "") or "") if locations else ""
	neighbor_to = loc_id
	if self_id and hasattr(ws, "get_location_of_entity") and hasattr(ws, "get_paths_from"):
		loc = ws.get_location_of_entity(self_id)
		src = str(getattr(loc, "location_id", "") or "")
		if src:
			loc_id = src
			paths = ws.get_paths_from(src) or []
			for p in list(paths):
				p_to = str(getattr(p, "to_location_id", "") or "")
				if p_to and p_to != src:
					neighbor_to = p_to
					break
			if not neighbor_to:
				neighbor_to = src
	ctx: dict[str, Any] = {
		"self_id": self_id,
		"target_id": target_id,
		"event_entity_id": target_id or self_id,
		"task_id": "probe_task_id",
		"event": {"type": "ProbeEvent", "entity_id": target_id or self_id},
		"parameters": {"source_location_id": loc_id, "to_location_id": neighbor_to},
	}
	return ctx


def _guess_param_value(ws: Any, key: str, ctx: dict[str, Any]) -> Any:
	key_l = str(key).lower()
	self_id = str(ctx.get("self_id", "") or "")
	self_ent = ws.get_entity_by_id(self_id) if self_id else None
	inv_ids = _inventory_item_ids(self_ent) if self_ent is not None else []
	loc_self = ws.get_location_of_entity(self_id) if self_id and hasattr(ws, "get_location_of_entity") else None
	loc_id = str(getattr(loc_self, "location_id", "") or "")
	neighbors = ws.get_paths_from(loc_id) if loc_id and hasattr(ws, "get_paths_from") else []
	neighbor_to = str(getattr(neighbors[0], "to_location_id", "") or "") if neighbors else loc_id
	all_agent_ids = _entity_ids_by_tag(ws, "agent")
	all_item_ids = _entity_ids_by_tag(ws, "item")
	all_bullet_ids = _entity_ids_by_tag(ws, "bullet")
	all_revolver_ids = _entity_ids_by_tag(ws, "revolver")
	all_shock_ids = _entity_ids_by_tag(ws, "shock_pistol")
	target_id = str(ctx.get("target_id", "") or "")
	if key_l in {"preset_id"}:
		return "default"
	if key_l in {"rule_type"}:
		return "Idle"
	if key_l in {"key"}:
		return "threshold_on"
	if key_l in {"value"}:
		return 60
	if key_l in {"text"}:
		return "自动化链路探测记录"
	if key_l in {"importance"}:
		return 0.5
	if "to_location" in key_l or key_l == "destination_id":
		return neighbor_to or loc_id
	if "source_location" in key_l or key_l == "source_id":
		return loc_id
	if "weapon" in key_l:
		for iid in inv_ids:
			e = ws.get_entity_by_id(iid)
			if e is not None and (e.has_tag("revolver") or e.has_tag("shock_pistol")):
				return iid
		return _pick_first(all_revolver_ids or all_shock_ids)
	if "bullet" in key_l:
		for iid in inv_ids:
			e = ws.get_entity_by_id(iid)
			if e is not None and e.has_tag("bullet"):
				return iid
		return _pick_first(all_bullet_ids)
	if "item" in key_l:
		return _pick_first(inv_ids, _pick_first(all_item_ids))
	if key_l in {"target_id", "entity_id"}:
		return target_id or _pick_first([x for x in all_agent_ids if x != self_id], self_id)
	if "target" in key_l or "entity" in key_l:
		return _pick_first([x for x in all_agent_ids if x != self_id], self_id)
	if key_l.endswith("_id"):
		return target_id or _pick_first([x for x in all_agent_ids if x != self_id], self_id)
	return ""


def _build_context_for_node(ws: Any, node: dict[str, Any]) -> dict[str, Any]:
	ctx = _build_base_context(ws)
	eff = str(node.get("effect", "") or "")
	if eff in {"AddCondition", "RemoveCondition"}:
		cond = str(node.get("condition_id", "") or "")
		candidates = _all_entities(ws)
		for ent in candidates:
			comp = ent.get_component("ConditionComponent")
			if comp is None:
				continue
			if "revolver" in cond and not ent.has_tag("revolver"):
				continue
			if "shock" in cond and not ent.has_tag("shock_pistol"):
				continue
			ctx["target_id"] = str(ent.entity_id)
			break
	if eff == "ModifyProperty":
		comp_name = str(node.get("component", "") or "")
		prop = str(node.get("property", "") or "")
		if comp_name == "ContainerComponent" and prop.startswith("slots.main"):
			for ent in _all_entities(ws):
				comp = ent.get_component("ContainerComponent")
				if comp is None or not hasattr(comp, "slots"):
					continue
				slots = getattr(comp, "slots", {}) or {}
				if isinstance(slots, dict) and "main" in slots:
					ctx["target_id"] = str(ent.entity_id)
					break
	params = dict(ctx.get("parameters", {}) or {})
	for key in sorted(_extract_param_keys(node)):
		params[key] = _guess_param_value(ws, key, ctx)
	ctx["parameters"] = params
	if str(node.get("effect", "") or "") == "MoveEntity":
		entity_id = str(params.get("entity_id", "") or "")
		if not entity_id:
			entity_id = str(ctx.get("target_id", "") or "")
		source_id = str(params.get("source_id", params.get("from_ref", "")) or "")
		destination_id = str(params.get("destination_id", params.get("to_ref", "")) or "")
		if source_id and destination_id and source_id == destination_id:
			if hasattr(ws, "get_paths_from"):
				paths = ws.get_paths_from(source_id) or []
				for p in list(paths):
					alt = str(getattr(p, "to_location_id", "") or "")
					if alt and alt != source_id:
						destination_id = alt
						break
		ctx["entity_id"] = entity_id
		ctx["source_id"] = source_id
		ctx["destination_id"] = destination_id
	return ctx


def _fill_templates(node: Any, params: dict[str, Any]) -> Any:
	if isinstance(node, str):
		m = TEMPLATE_RE.match(node.strip())
		if m:
			k = str(m.group(1))
			if k in params:
				return params.get(k)
		return node
	if isinstance(node, list):
		return [_fill_templates(v, params) for v in node]
	if isinstance(node, dict):
		return {k: _fill_templates(v, params) for k, v in node.items()}
	return node


def _ensure_condition_component(ent: Any) -> list[str] | None:
	if ent is None:
		return None
	comp = ent.get_component("ConditionComponent")
	if comp is None:
		comp = UnknownComponent(data={"conditions": []})
		ent.components["ConditionComponent"] = comp
	if hasattr(comp, "data") and isinstance(getattr(comp, "data"), dict):
		comp.data.setdefault("conditions", [])
		if isinstance(comp.data["conditions"], list):
			return comp.data["conditions"]
	return None


def _ensure_inventory_contains(ws: Any, owner: Any, item: Any) -> bool:
	if owner is None or item is None:
		return False
	owner_id = str(getattr(owner, "entity_id", "") or "")
	item_id = str(getattr(item, "entity_id", "") or "")
	if not owner_id or not item_id:
		return False
	cc_owner = owner.get_component("ContainerComponent")
	if cc_owner is None or not hasattr(cc_owner, "slots") or not isinstance(getattr(cc_owner, "slots"), dict):
		return False
	if hasattr(cc_owner, "has_item_id") and cc_owner.has_item_id(item_id):
		return True
	for ent in _all_entities(ws):
		cc = ent.get_component("ContainerComponent")
		if cc is None or not hasattr(cc, "slots") or not isinstance(getattr(cc, "slots"), dict):
			continue
		for slot in cc.slots.values():
			items = list(getattr(slot, "items", []) or [])
			if item_id in items:
				slot.items.remove(item_id)
	for loc in _all_locations(ws):
		if item_id in list(getattr(loc, "entities_in_location", []) or []):
			loc.remove_entity_id(item_id)
	for slot in cc_owner.slots.values():
		slot.items.append(item_id)
		return True
	return False


def _set_compare_property_truth(target: Any, component: str, prop: str, op: str, expected: Any) -> None:
	if target is None:
		return
	comp = target.get_component(component) if hasattr(target, "get_component") else None
	if comp is None or not prop:
		return
	v = expected
	try:
		num = float(expected)
		if op == "<":
			v = num - 1
		elif op == "<=":
			v = num
		elif op == ">":
			v = num + 1
		elif op == ">=":
			v = num
		elif op == "==":
			v = num
	except Exception:
		v = expected
	setattr(comp, prop, v)


def _satisfy_condition(ws: Any, cond: dict[str, Any], ctx: dict[str, Any]) -> None:
	if not isinstance(cond, dict) or not cond:
		return
	c_type = str(cond.get("type", "") or "")
	if c_type == "all":
		for sub in list(cond.get("conditions", []) or []):
			if isinstance(sub, dict):
				_satisfy_condition(ws, sub, ctx)
		return
	if c_type == "any":
		items = [x for x in list(cond.get("conditions", []) or []) if isinstance(x, dict)]
		if items:
			_satisfy_condition(ws, items[0], ctx)
		return
	if c_type == "not":
		return
	if c_type == "event_field_eq":
		event = ctx.setdefault("event", {})
		if isinstance(event, dict):
			event[str(cond.get("field", "") or "")] = cond.get("value")
		return
	if c_type == "has_tag":
		target = resolve_entity(ws, cond.get("target", "self"), ctx, allow_literal=True)
		tag = str(cond.get("tag", "") or "")
		if target is not None and tag:
			tc = target.get_component("TagComponent")
			if isinstance(tc, TagComponent):
				if tag not in tc.tags:
					tc.tags.append(tag)
		return
	if c_type == "has_condition":
		target = resolve_entity(ws, cond.get("target", "self"), ctx, allow_literal=True)
		cid = str(cond.get("condition_id", "") or "")
		lst = _ensure_condition_component(target)
		if lst is not None and cid and cid not in lst:
			lst.append(cid)
		return
	if c_type == "inventory_contains":
		owner = resolve_entity(ws, cond.get("owner", "self"), ctx, allow_literal=True)
		item = resolve_entity(ws, cond.get("item_ref", "target"), ctx, allow_literal=True)
		_ensure_inventory_contains(ws, owner, item)
		return
	if c_type == "check_cooldown":
		target = resolve_entity(ws, cond.get("target", "self"), ctx, allow_literal=True)
		key = str(cond.get("key", "") or "")
		duration = int(cond.get("duration", 0) or 0)
		if target is not None and key:
			comp = target.get_component("CooldownComponent")
			if not isinstance(comp, CooldownComponent):
				comp = CooldownComponent(cooldowns={})
				target.components["CooldownComponent"] = comp
			now = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
			comp.cooldowns[key] = int(now - duration - 1)
		return
	if c_type == "compare_property":
		target = resolve_entity(ws, cond.get("target", "self"), ctx, allow_literal=True)
		_set_compare_property_truth(
			target=target,
			component=str(cond.get("component", "") or ""),
			prop=str(cond.get("property", "") or ""),
			op=str(cond.get("op", "==") or "=="),
			expected=cond.get("value"),
		)
		return


def _prime_recipe_preconditions(ws: Any, recipe: dict[str, Any], actor_id: str, target_id: str, params: dict[str, Any]) -> None:
	ctx = _build_base_context(ws)
	ctx["self_id"] = str(actor_id or "")
	ctx["target_id"] = str(target_id or "")
	ctx["event_entity_id"] = str(target_id or actor_id or "")
	ctx["parameters"] = dict(params or {})
	selector = recipe.get("selector", {}) or {}
	condition = recipe.get("condition", {}) or {}
	if isinstance(selector, dict):
		_satisfy_condition(ws, selector, ctx)
	if isinstance(condition, dict):
		_satisfy_condition(ws, condition, ctx)


def _prime_reaction_preconditions(ws: Any, rule: dict[str, Any], event: dict[str, Any], ctx: dict[str, Any]) -> None:
	local_ctx = dict(ctx or {})
	local_ctx["event"] = dict(event or {})
	selector = rule.get("selector", {}) or {}
	condition = rule.get("condition", {}) or {}
	if isinstance(selector, dict):
		_satisfy_condition(ws, selector, local_ctx)
	if isinstance(condition, dict):
		_satisfy_condition(ws, condition, local_ctx)
	event_obj = local_ctx.get("event", {}) or {}
	if isinstance(event_obj, dict):
		event.clear()
		event.update(event_obj)


def _probe_effect_bind_and_exec(ws: Any, executor: WorldExecutor, source: str, effect_obj: dict[str, Any], result: ProbeResult) -> None:
	ctx = _build_context_for_node(ws, effect_obj)
	params = dict((ctx or {}).get("parameters", {}) or {})
	eff_payload = _fill_templates(dict(effect_obj), params)
	if str((eff_payload or {}).get("effect", "") or "") == "AttachInterruptPresetDetails":
		if not isinstance(getattr(ws, "interaction_log", None), list):
			ws.interaction_log = []
		if not ws.interaction_log:
			ws.interaction_log.append({"actor_id": str(ctx.get("self_id", "") or ""), "verb": "probe"})
	try:
		bind_effect_input(ws, eff_payload, ctx)
	except BindError as e:
		result.bind_errors.append({"source": source, "effect": dict(eff_payload), "error": str(e)})
		return
	try:
		events = executor.execute(ws, dict(eff_payload), dict(ctx))
	except RecursionError as e:
		result.exec_errors.append({"source": source, "effect": dict(eff_payload), "event": {"type": "RecursionError", "message": str(e)}})
		return
	except Exception as e:
		result.exec_errors.append({"source": source, "effect": dict(eff_payload), "event": {"type": "Exception", "message": str(e)}})
		return
	for ev in list(events or []):
		if isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError"}:
			result.exec_errors.append({"source": source, "effect": dict(eff_payload), "event": dict(ev)})


def _targets_for_recipe(ws: Any, recipe: dict[str, Any], actor_id: str) -> list[str]:
	required_tags = [str(x) for x in list(recipe.get("target_tags", []) or [])]
	mode = str(recipe.get("target_tags_match", "all") or "all").strip().lower()
	actor_loc = ws.get_location_of_entity(actor_id) if hasattr(ws, "get_location_of_entity") else None
	actor_loc_id = str(getattr(actor_loc, "location_id", "") or "")
	local_first: list[str] = []
	other: list[str] = []
	self_ids: list[str] = []
	candidates: list[str] = []
	for ent in _all_entities(ws):
		try:
			eid = str(ent.entity_id)
			tags_ok = True
			if required_tags:
				if mode == "any":
					tags_ok = any(ent.has_tag(t) for t in required_tags)
				else:
					tags_ok = all(ent.has_tag(t) for t in required_tags)
			if tags_ok:
				if eid == str(actor_id):
					self_ids.append(eid)
					continue
				ent_loc = ws.get_location_of_entity(eid) if hasattr(ws, "get_location_of_entity") else None
				ent_loc_id = str(getattr(ent_loc, "location_id", "") or "")
				if actor_loc_id and ent_loc_id == actor_loc_id:
					local_first.append(eid)
				else:
					other.append(eid)
		except Exception:
			continue
	candidates = list(local_first) + list(other) + list(self_ids)
	if not candidates:
		candidates = [actor_id]
	return candidates


def _params_for_recipe(ws: Any, recipe: dict[str, Any], actor_id: str, target_id: str) -> dict[str, Any]:
	ctx = _build_base_context(ws)
	ctx["self_id"] = actor_id
	ctx["target_id"] = target_id
	params: dict[str, Any] = {}
	for k in sorted(_extract_param_keys(recipe)):
		params[k] = _guess_param_value(ws, k, ctx)
	if str(recipe.get("verb", "") or "") == "Travel":
		loc = ws.get_location_of_entity(actor_id) if hasattr(ws, "get_location_of_entity") else None
		loc_id = str(getattr(loc, "location_id", "") or "")
		paths = ws.get_paths_from(loc_id) if loc_id and hasattr(ws, "get_paths_from") else []
		if paths:
			to_id = str(getattr(paths[0], "to_location_id", "") or "")
			if to_id and to_id != loc_id:
				params["to_location_id"] = to_id
				params["source_location_id"] = loc_id
		elif loc_id:
			params["source_location_id"] = loc_id
			params["to_location_id"] = loc_id
	return params


def _execute_interaction_effects(ws: Any, executor: WorldExecutor, response: dict[str, Any]) -> list[dict[str, Any]]:
	ctx = dict((response or {}).get("context", {}) or {})
	events: list[dict[str, Any]] = []
	for eff in list((response or {}).get("effects", []) or []):
		if isinstance(eff, dict):
			try:
				events.extend(executor.execute(ws, dict(eff), dict(ctx)))
			except RecursionError as e:
				events.append({"type": "RecursionError", "message": str(e)})
			except Exception as e:
				events.append({"type": "Exception", "message": str(e)})
	return events


def _try_complete_created_tasks(ws: Any, executor: WorldExecutor, actor_id: str, max_ticks: int = 20) -> list[dict[str, Any]]:
	evs: list[dict[str, Any]] = []
	for _ in range(max_ticks):
		try:
			worker_events = executor.execute(ws, {"effect": "WorkerTick", "entity_id": actor_id}, {"self_id": actor_id, "entity_id": actor_id})
		except RecursionError as e:
			evs.append({"type": "RecursionError", "message": str(e)})
			break
		except Exception as e:
			evs.append({"type": "Exception", "message": str(e)})
			break
		evs.extend(list(worker_events or []))
		has_active_task = False
		agent = ws.get_entity_by_id(actor_id)
		if agent is not None:
			wc = agent.get_component("WorkerComponent")
			has_active_task = bool(getattr(wc, "current_task_id", "") or "") if wc is not None else False
		if not has_active_task:
			break
	return evs


def _probe_recipes(bundle: Any, result: ProbeResult) -> None:
	seed_runtime = _new_runtime(bundle)
	agent_ids = _entity_ids_by_tag(seed_runtime.ws, "agent")
	recipe_db = dict(bundle.recipes or {})
	for recipe_id, recipe in (recipe_db or {}).items():
		if not isinstance(recipe, dict):
			continue
		verb = str(recipe.get("verb", "") or "").strip()
		if not verb:
			continue
		success = False
		fail_reasons: list[str] = []
		for actor_id in list(agent_ids):
			runtime_for_targets = _new_runtime(bundle)
			targets = _targets_for_recipe(runtime_for_targets.ws, recipe, actor_id)
			for target_id in targets[:30]:
				runtime = _new_runtime(bundle)
				params = _params_for_recipe(runtime.ws, recipe, actor_id, target_id)
				_prime_recipe_preconditions(runtime.ws, recipe, actor_id, target_id, params)
				command_payload: dict[str, Any] = {"verb": verb, "target_id": target_id, "parameters": dict(params)}
				if verb == "Talk":
					command_payload["target_id"] = ""
					p = dict(command_payload.get("parameters", {}) or {})
					if not str(p.get("text", "") or "").strip():
						p["text"] = "例行沟通：继续按分工推进。"
					command_payload["parameters"] = p
				resp = runtime.engine.process_command(runtime.ws, actor_id, command_payload)
				status = str((resp or {}).get("status", "") or "")
				if status != "success":
					fail_reasons.append(f"{actor_id}->{target_id}:{resp.get('reason','')}")
					continue
				events = _execute_interaction_effects(runtime.ws, runtime.executor, resp)
				for ev in list(events or []):
					if isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError", "RecursionError", "Exception"}:
						fail_reasons.append(f"{actor_id}->{target_id}:{ev.get('type')}:{ev.get('message','')}")
				task_events = _try_complete_created_tasks(runtime.ws, runtime.executor, actor_id)
				for ev in list(task_events or []):
					if isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError", "TaskFinishFailed", "RecursionError", "Exception"}:
						fail_reasons.append(f"{actor_id}:task:{ev.get('type')}:{ev.get('message','')}")
				success = True
				break
			if success:
				break
		if success:
			result.recipe_success.add(str(recipe_id))
		else:
			result.recipe_failed[str(recipe_id)] = fail_reasons[:10]


def _probe_reactions(bundle: Any, result: ProbeResult) -> None:
	reactions = dict(bundle.reactions or {})
	rules = list((reactions or {}).get("rules", []) or [])
	event_types = ["TickAdvanced", "TaskFinished", "EntityDestroyed", "EntityDied", "PropertyModified", "ConversationEnded"]
	for idx, rule in enumerate(rules):
		if not isinstance(rule, dict):
			continue
		rule_id = str(rule.get("id", "") or f"rule_{idx}")
		target_event = str(rule.get("on_event", "") or "")
		candidates = [target_event] if target_event else list(event_types)
		triggered = False
		for ev_type in candidates:
			runtime = _new_runtime(bundle)
			agent_ids = _entity_ids_by_tag(runtime.ws, "agent")
			entity_ids = [str(getattr(e, "entity_id", "") or "") for e in _all_entities(runtime.ws)]
			for eid in (agent_ids + entity_ids)[:30]:
				event = {"type": ev_type, "entity_id": eid}
				ctx = {"self_id": eid, "target_id": eid, "event_entity_id": eid}
				_prime_reaction_preconditions(runtime.ws, rule, event, ctx)
				reqs = runtime.trigger.build_reaction_effects(runtime.ws, event, ctx)
				if not reqs:
					continue
				for req in reqs:
					if not isinstance(req, dict):
						continue
					eff = req.get("effect", {}) or {}
					ectx = req.get("context", {}) or {}
					try:
						evs = runtime.executor.execute(runtime.ws, dict(eff), dict(ectx))
					except RecursionError as e:
						result.exec_errors.append({"source": f"reaction:{rule_id}", "effect": dict(eff), "event": {"type": "RecursionError", "message": str(e)}})
						evs = []
					except Exception as e:
						result.exec_errors.append({"source": f"reaction:{rule_id}", "effect": dict(eff), "event": {"type": "Exception", "message": str(e)}})
						evs = []
					for ev in list(evs or []):
						if isinstance(ev, dict) and str(ev.get("type", "") or "") in {"ExecutorError", "BindError", "RecursionError", "Exception"}:
							result.exec_errors.append({"source": f"reaction:{rule_id}", "effect": dict(eff), "event": dict(ev)})
				triggered = True
				break
			if triggered:
				break
		if triggered:
			result.reaction_triggered.add(rule_id)
		else:
			result.reaction_untriggered.add(rule_id)


def _probe_registry(bundle: Any, result: ProbeResult) -> None:
	all_effects = _collect_effects(bundle)
	used = {str((eff or {}).get("effect", "") or "") for _, eff in all_effects if isinstance(eff, dict)}
	used = {x for x in used if x}
	binder_types = get_binder_effect_types()
	exec_types = get_executor_effect_types()
	for eff in sorted(used):
		if eff not in EFFECT_TYPES:
			result.registry_errors.append(f"unknown effect used by recipes/reactions: {eff}")
			continue
		if eff not in binder_types:
			result.registry_errors.append(f"binder missing effect: {eff}")
		if eff not in exec_types:
			result.registry_errors.append(f"executor missing effect: {eff}")


def _probe_effects(bundle: Any, result: ProbeResult) -> None:
	for src, eff in _collect_effects(bundle):
		runtime = _new_runtime(bundle)
		ctx = _build_context_for_node(runtime.ws, eff)
		params = dict((ctx or {}).get("parameters", {}) or {})
		eff_payload = _fill_templates(dict(eff), params)
		try:
			bind_effect_input(runtime.ws, eff_payload, ctx)
		except BindError as e:
			result.bind_errors.append({"source": src, "effect": dict(eff_payload), "error": str(e)})


def run_probe(project_root: Path, world_json_name: str) -> int:
	bundle = load_data_bundle(project_root)
	world_path = project_root / "Data" / world_json_name
	bundle.world = load_json(world_path)
	result = ProbeResult(
		registry_errors=[],
		bind_errors=[],
		exec_errors=[],
		recipe_success=set(),
		recipe_failed={},
		reaction_triggered=set(),
		reaction_untriggered=set(),
	)
	_probe_registry(bundle, result)
	_probe_effects(bundle, result)
	_probe_recipes(bundle, result)
	_probe_reactions(bundle, result)
	total_recipes = len([k for k, v in (bundle.recipes or {}).items() if isinstance(v, dict) and str(v.get("verb", "") or "").strip()])
	summary = {
		"registry_errors": len(result.registry_errors),
		"effects": {
			"bind_errors": len(result.bind_errors),
			"exec_errors": len(result.exec_errors),
		},
		"recipes": {
			"total": total_recipes,
			"success": len(result.recipe_success),
			"failed": len(result.recipe_failed),
		},
		"reactions": {
			"total": len(list((bundle.reactions or {}).get("rules", []) or [])),
			"triggered": len(result.reaction_triggered),
			"untriggered": len(result.reaction_untriggered),
		},
	}
	print(json.dumps(summary, ensure_ascii=False, indent=2))
	if result.registry_errors:
		print("REGISTRY_ERRORS_TOP:")
		for msg in result.registry_errors[:20]:
			print(msg)
	if result.bind_errors:
		print("BIND_ERRORS_TOP:")
		for row in result.bind_errors[:20]:
			print(json.dumps(row, ensure_ascii=False))
	if result.exec_errors:
		print("EXEC_ERRORS_TOP:")
		for row in result.exec_errors[:20]:
			print(json.dumps(row, ensure_ascii=False))
	if result.recipe_failed:
		print("RECIPE_FAILED_TOP:")
		for rid in sorted(result.recipe_failed.keys())[:30]:
			print(rid, result.recipe_failed[rid])
	if result.reaction_untriggered:
		print("REACTION_UNTRIGGERED:")
		for rid in sorted(result.reaction_untriggered):
			print(rid)
	has_error = bool(result.registry_errors or result.bind_errors or result.exec_errors or result.recipe_failed or result.reaction_untriggered)
	return 1 if has_error else 0


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--project-root", default=".", help="Project root path")
	parser.add_argument("--world", default="World_SpaceWerewolf.json", help="World json filename under Data/")
	args = parser.parse_args()
	root = Path(args.project_root).resolve()
	code = run_probe(root, str(args.world))
	sys.exit(code)


if __name__ == "__main__":
	main()
