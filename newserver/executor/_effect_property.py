from __future__ import annotations

from typing import Any

from ..models.components import CreatureComponent, TagComponent
from ._effect_binder import BindError, _base_bind, _require_float, _require_str, _resolve_param_token


def _set_nested_value(obj: Any, path: str, value: Any, delta_mode: bool = False) -> Any:
	parts = path.split(".")
	current = obj
	for i, part in enumerate(parts[:-1]):
		if isinstance(current, dict):
			current = current.get(part)
		elif hasattr(current, part):
			current = getattr(current, part)
		else:
			return None
		if current is None:
			return None
	
	last_key = parts[-1]
	old_val = None
	if isinstance(current, dict):
		old_val = current.get(last_key)
		new_val = value
		if delta_mode:
			try:
				new_val = float(old_val or 0) + float(value)
			except Exception:
				new_val = value
		current[last_key] = new_val
		return new_val
	elif hasattr(current, last_key):
		old_val = getattr(current, last_key)
		new_val = value
		if delta_mode:
			try:
				new_val = float(old_val or 0) + float(value)
			except Exception:
				new_val = value
		setattr(current, last_key, new_val)
		return new_val
	return None


def _bind_modify_property(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	component = _require_str(params, effect_type, "component")
	prop = _require_str(params, effect_type, "property")
	has_change = "change" in params
	has_value = "value" in params
	missing: list[str] = []
	if not has_change and not has_value:
		missing.append("change_or_value")
	if has_change and has_value:
		missing.append("change_or_value_xor")
	if missing:
		raise BindError(effect_type, missing)
	out: dict[str, Any] = {"effect": effect_type, "target": target, "component": component, "property": prop}
	if has_change:
		out["change"] = _require_float(params, effect_type, "change", ctx)
	elif has_value:
		out["value"] = _resolve_param_token(params.get("value", None), ctx)
	return out, ctx


def _bind_add_tag(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	tag = _require_str(params, effect_type, "tag")
	return {"effect": effect_type, "target": target, "tag": tag}, ctx


def _bind_remove_tag(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _require_str(params, effect_type, "target")
	tag = _require_str(params, effect_type, "tag")
	return {"effect": effect_type, "target": target, "tag": tag}, ctx


def execute_modify_property(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "ModifyProperty: target missing"}]
	comp_name = str(data.get("component", ""))
	prop_name = str(data.get("property", ""))
	change = data.get("change")
	# If change is not provided, check if "value" is provided (for direct set)
	has_change = "change" in data
	val_set = data.get("value")
	
	comp = target.get_component(comp_name)
	if comp is None:
		return [{"type": "ExecutorError", "message": f"ModifyProperty: component missing: {comp_name}"}]

	# Support nested property access (dot notation)
	# e.g. "slots.main.config.transparent"
	if "." in prop_name:
		new_val = _set_nested_value(comp, prop_name, float(change) if has_change else val_set, delta_mode=has_change)
		if new_val is None:
			return [{"type": "ExecutorError", "message": f"ModifyProperty: nested property access failed: {prop_name}"}]
		return [
			{
				"type": "PropertyModified",
				"entity_id": target.entity_id,
				"component": comp_name,
				"property": prop_name,
				"delta": change if has_change else 0,
				"new_value": new_val,
			}
		]

	if isinstance(comp, CreatureComponent):
		comp.ensure_initialized()
		cur = getattr(comp, prop_name, None)
		if cur is None:
			return [{"type": "ExecutorError", "message": f"ModifyProperty: property missing: {prop_name}"}]
		
		# Allow 'value' for direct set, 'change' for delta
		new_val = 0.0
		if has_change:
			new_val = float(cur) + float(change)
		elif val_set is not None:
			new_val = float(val_set)
		else:
			new_val = float(cur) # No op

		setattr(comp, prop_name, new_val)
		return [
			{
				"type": "PropertyModified",
				"entity_id": target.entity_id,
				"component": comp_name,
				"property": prop_name,
				"delta": float(change) if has_change else 0.0,
				"new_value": new_val,
			}
		]
	
	if hasattr(comp, prop_name):
		cur = getattr(comp, prop_name)
		new_val = val_set if val_set is not None else change
		if has_change and isinstance(cur, (int, float)):
			new_val = float(cur) + float(change)
		setattr(comp, prop_name, new_val)
		return [
			{
				"type": "PropertyModified",
				"entity_id": target.entity_id,
				"component": comp_name,
				"property": prop_name,
				"delta": change if has_change else 0,
				"new_value": new_val,
			}
		]

	if hasattr(comp, "data") and isinstance(getattr(comp, "data"), dict):
		cur = comp.data.get(prop_name, 0)
		try:
			new_val = 0.0
			if has_change:
				new_val = float(cur) + float(change)
			elif val_set is not None:
				new_val = val_set
			else:
				new_val = cur

			comp.data[prop_name] = new_val
			return [
				{
					"type": "PropertyModified",
					"entity_id": target.entity_id,
					"component": comp_name,
					"property": prop_name,
					"delta": float(change) if has_change else 0.0,
					"new_value": new_val,
				}
			]
		except Exception:
			return [{"type": "ExecutorError", "message": "ModifyProperty: failed to write UnknownComponent"}]
	return [{"type": "ExecutorError", "message": "ModifyProperty: unsupported component type"}]


def execute_add_tag(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "target") or "target")
	target = executor._resolve_entity_from_ctx(ws, context, target_key)
	if target is None:
		return [{"type": "ExecutorError", "message": "AddTag: target missing"}]
	tag_name = str(data.get("tag", "") or "").strip()
	if not tag_name:
		return [{"type": "ExecutorError", "message": "AddTag: tag missing"}]
	tag_comp = target.get_component("TagComponent")
	if not isinstance(tag_comp, TagComponent):
		tag_comp = TagComponent(tags=[])
		target.add_component("TagComponent", tag_comp)
	if tag_name not in tag_comp.tags:
		tag_comp.tags.append(tag_name)
	return [{"type": "TagAdded", "entity_id": target.entity_id, "tag": tag_name}]


def execute_remove_tag(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = str(data.get("target", "target") or "target")
	target = executor._resolve_entity_from_ctx(ws, context, target_key)
	if target is None:
		return [{"type": "ExecutorError", "message": "RemoveTag: target missing"}]
	tag_name = str(data.get("tag", "") or "").strip()
	if not tag_name:
		return [{"type": "ExecutorError", "message": "RemoveTag: tag missing"}]
	tag_comp = target.get_component("TagComponent")
	if not isinstance(tag_comp, TagComponent):
		return [{"type": "TagRemoved", "entity_id": target.entity_id, "tag": tag_name, "removed": False}]
	if tag_name in tag_comp.tags:
		tag_comp.tags.remove(tag_name)
		return [{"type": "TagRemoved", "entity_id": target.entity_id, "tag": tag_name, "removed": True}]
	return [{"type": "TagRemoved", "entity_id": target.entity_id, "tag": tag_name, "removed": False}]
