from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..entity_ref_resolver import resolve_entity
from ..models.components import StatusComponent


def compare_values(actual: Any, expected: Any, op: str) -> bool:
	operator = str(op or "==")
	if operator in ("==", "!="):
		return (actual == expected) if operator == "==" else (actual != expected)
	try:
		left = float(actual)
		right = float(expected)
	except Exception:
		return False
	if operator == "<":
		return left < right
	if operator == "<=":
		return left <= right
	if operator == ">":
		return left > right
	if operator == ">=":
		return left >= right
	return False


def resolve_value(ws: Any, ref: Any, context: dict[str, Any] | None) -> Any:
	if not isinstance(ref, str):
		return ref
	text = str(ref or "").strip()
	if not text:
		return None
	root, dot, remainder = text.partition(".")
	ctx = context if isinstance(context, dict) else {}
	if root == "event" and dot:
		return resolve_path_value(ctx.get("event", {}) or {}, remainder.split("."))
	if root == "param" and dot:
		params = ctx.get("parameters", {}) or {}
		return resolve_path_value(params if isinstance(params, dict) else {}, remainder.split("."))
	if root in {"self", "target", "event_entity"} and dot:
		entity = resolve_entity(ws, root, ctx, allow_literal=True)
		return resolve_entity_path(ws, entity, remainder.split("."))
	return ref


def resolve_path_value(value: Any, segments: list[str]) -> Any:
	current = value
	for raw_segment in segments:
		segment = str(raw_segment or "").strip()
		if not segment or current is None:
			return None
		if isinstance(current, dict):
			current = current.get(segment)
			continue
		if hasattr(current, "data") and isinstance(getattr(current, "data"), dict):
			data = getattr(current, "data")
			if segment in data:
				current = data.get(segment)
				continue
		if hasattr(current, segment):
			current = getattr(current, segment)
			continue
		return None
	return current


def resolve_entity_path(ws: Any, entity: Any, segments: list[str]) -> Any:
	current = entity
	for idx, raw_segment in enumerate(segments):
		segment = str(raw_segment or "").strip()
		if not segment or current is None:
			return None
		if isinstance(current, dict):
			current = current.get(segment)
			continue
		if idx == 0 and segment == "location_id":
			entity_id = str(getattr(current, "entity_id", "") or "")
			if not entity_id or not hasattr(ws, "get_location_of_entity"):
				return None
			location = ws.get_location_of_entity(entity_id)
			return str(getattr(location, "location_id", "") or "") if location is not None else None
		if idx == 0 and segment == "location":
			entity_id = str(getattr(current, "entity_id", "") or "")
			if not entity_id or not hasattr(ws, "get_location_of_entity"):
				return None
			current = ws.get_location_of_entity(entity_id)
			continue
		if hasattr(current, "get_component"):
			component = current.get_component(segment)
			if component is not None:
				current = component
				continue
		if hasattr(current, "data") and isinstance(getattr(current, "data"), dict):
			data = getattr(current, "data")
			if segment in data:
				current = data.get(segment)
				continue
		if hasattr(current, segment):
			current = getattr(current, segment)
			continue
		return None
	return current


def evaluate_predicate(ws: Any, predicate: dict[str, Any] | None, context: dict[str, Any] | None) -> bool:
	if not isinstance(predicate, dict) or not predicate:
		return True
	ctx = context if isinstance(context, dict) else {}
	p_type = str(predicate.get("type", "") or "").strip()
	if p_type == "all":
		items = predicate.get("conditions", []) or []
		return all(evaluate_predicate(ws, item if isinstance(item, dict) else {}, ctx) for item in items)
	if p_type == "any":
		items = predicate.get("conditions", []) or []
		return any(evaluate_predicate(ws, item if isinstance(item, dict) else {}, ctx) for item in items)
	if p_type == "not":
		sub = predicate.get("condition", {}) or {}
		return not evaluate_predicate(ws, sub if isinstance(sub, dict) else {}, ctx)
	if p_type == "event_field_eq":
		field_name = str(predicate.get("field", "") or "")
		expected = predicate.get("value")
		event = ctx.get("event", {}) or {}
		if not isinstance(event, dict) or not field_name:
			return False
		return event.get(field_name) == expected
	if p_type == "has_tag":
		target = resolve_entity(ws, predicate.get("target", "self"), ctx, allow_literal=True)
		tag = str(predicate.get("tag", "") or "")
		if target is None or not tag or not hasattr(target, "has_tag"):
			return False
		return bool(target.has_tag(tag))
	if p_type == "has_tags":
		target = resolve_entity(ws, predicate.get("target", "self"), ctx, allow_literal=True)
		tags_raw = predicate.get("tags", []) or []
		match_mode = str(predicate.get("match", "all") or "all").strip().lower()
		if target is None or not hasattr(target, "has_tag"):
			return False
		if not isinstance(tags_raw, list) or not tags_raw:
			return False
		tags = [str(item).strip() for item in tags_raw if str(item).strip()]
		if not tags:
			return False
		if match_mode == "any":
			return any(bool(target.has_tag(tag)) for tag in tags)
		return all(bool(target.has_tag(tag)) for tag in tags)
	if p_type == "has_component":
		target = resolve_entity(ws, predicate.get("target", "self"), ctx, allow_literal=True)
		component_name = str(predicate.get("component", "") or "")
		if target is None or not component_name or not hasattr(target, "get_component"):
			return False
		return target.get_component(component_name) is not None
	if p_type == "has_status":
		target = resolve_entity(ws, predicate.get("target", "self"), ctx, allow_literal=True)
		status_id = str(predicate.get("status_id", "") or "")
		if target is None or not status_id:
			return False
		component = target.get_component("StatusComponent") if hasattr(target, "get_component") else None
		if not isinstance(component, StatusComponent):
			return False
		return component.has_status(status_id)
	if p_type == "compare_property":
		target = resolve_entity(ws, predicate.get("target", "self"), ctx, allow_literal=True)
		component_name = str(predicate.get("component", "") or "")
		property_name = str(predicate.get("property", "") or "")
		op = str(predicate.get("op", "==") or "==")
		expected = predicate.get("value")
		if target is None or not component_name or not property_name:
			return False
		component = target.get_component(component_name) if hasattr(target, "get_component") else None
		if component is None:
			return False
		actual = getattr(component, property_name, None)
		return compare_values(actual, expected, op)
	if p_type == "compare_value":
		left = resolve_value(ws, predicate.get("left", ""), ctx)
		expected = predicate.get("value")
		op = str(predicate.get("op", "==") or "==")
		return compare_values(left, expected, op)
	if p_type == "compare_fields":
		left = resolve_value(ws, predicate.get("left", ""), ctx)
		right = resolve_value(ws, predicate.get("right", ""), ctx)
		op = str(predicate.get("op", "==") or "==")
		return compare_values(left, right, op)
	if p_type == "inventory_contains":
		owner = resolve_entity(ws, predicate.get("owner", "self"), ctx, allow_literal=True)
		item = resolve_entity(ws, predicate.get("item_ref", "target"), ctx, allow_literal=True)
		if owner is None or item is None or not hasattr(owner, "get_component"):
			return False
		container = owner.get_component("ContainerComponent")
		if container is None or not hasattr(container, "get_all_item_ids"):
			return False
		return str(getattr(item, "entity_id", "") or "") in set(container.get_all_item_ids())
	if p_type == "inventory_has_tag":
		owner = resolve_entity(ws, predicate.get("owner", "self"), ctx, allow_literal=True)
		tag = str(predicate.get("tag", "") or "").strip()
		min_count = int(predicate.get("min_count", 1) or 1)
		if owner is None or not tag or min_count <= 0 or not hasattr(owner, "get_component"):
			return False
		container = owner.get_component("ContainerComponent")
		if container is None or not hasattr(container, "get_all_item_ids"):
			return False
		count = 0
		for item_id in list(container.get_all_item_ids() or []):
			item = ws.get_entity_by_id(str(item_id)) if hasattr(ws, "get_entity_by_id") else None
			if item is None or not hasattr(item, "has_tag"):
				continue
			if bool(item.has_tag(tag)):
				count += 1
				if count >= min_count:
					return True
		return False
	if p_type == "same_location":
		left = resolve_entity(ws, predicate.get("left", "self"), ctx, allow_literal=True)
		right = resolve_entity(ws, predicate.get("right", "target"), ctx, allow_literal=True)
		if left is None or right is None or not hasattr(ws, "get_location_of_entity"):
			return False
		left_location = ws.get_location_of_entity(str(getattr(left, "entity_id", "") or ""))
		right_location = ws.get_location_of_entity(str(getattr(right, "entity_id", "") or ""))
		if left_location is None or right_location is None:
			return False
		return str(getattr(left_location, "location_id", "") or "") == str(getattr(right_location, "location_id", "") or "")
	if p_type == "param_eq":
		key = str(predicate.get("key", "") or "").strip()
		expected = predicate.get("value")
		if not key:
			return False
		params = ctx.get("parameters", {}) or {}
		if not isinstance(params, dict):
			return False
		return params.get(key) == expected
	return False


def explain_predicate(ws: Any, predicate: dict[str, Any] | None, context: dict[str, Any] | None, path: str = "root") -> dict[str, Any]:
	if not isinstance(predicate, dict) or not predicate:
		return {"ok": True, "path": path, "reason": "", "detail": {}}
	ctx = context if isinstance(context, dict) else {}
	p_type = str(predicate.get("type", "") or "").strip()
	if p_type == "all":
		items = predicate.get("conditions", []) or []
		for idx, item in enumerate(items):
			child = explain_predicate(ws, item if isinstance(item, dict) else {}, ctx, f"{path}.conditions[{idx}]")
			if not bool(child.get("ok", False)):
				return {"ok": False, "path": path, "reason": "ALL_CHILD_FAILED", "detail": {"failed_index": idx, "child": child}}
		return {"ok": True, "path": path, "reason": "", "detail": {}}
	if p_type == "any":
		items = predicate.get("conditions", []) or []
		children: list[dict[str, Any]] = []
		for idx, item in enumerate(items):
			child = explain_predicate(ws, item if isinstance(item, dict) else {}, ctx, f"{path}.conditions[{idx}]")
			children.append(child)
			if bool(child.get("ok", False)):
				return {"ok": True, "path": path, "reason": "", "detail": {"matched_index": idx}}
		return {"ok": False, "path": path, "reason": "ANY_ALL_FAILED", "detail": {"children": children}}
	ok = evaluate_predicate(ws, predicate, ctx)
	return {"ok": bool(ok), "path": path, "reason": "" if ok else "PREDICATE_FALSE", "detail": {"type": p_type}}


@dataclass
class QueryEngine:
	def execute(self, ws: Any, query: dict[str, Any] | None, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		if not isinstance(query, dict):
			return []
		source = str(query.get("from", "entities") or "entities").strip()
		if source != "entities":
			return []
		ctx = context if isinstance(context, dict) else {}
		where = query.get("where", {}) or {}
		select = query.get("select", []) or []
		order_by = query.get("order_by", {}) or {}
		limit_raw = query.get("limit", None)
		rows: list[dict[str, Any]] = []
		entities = getattr(ws, "entities", {}) or {}
		for entity in list(entities.values()):
			entity_id = str(getattr(entity, "entity_id", "") or "")
			if not entity_id:
				continue
			row_context = dict(ctx)
			row_context["target_id"] = entity_id
			if isinstance(where, dict) and where:
				if not evaluate_predicate(ws, where, row_context):
					continue
			rows.append(self._build_row(ws, entity, select, row_context))
		if isinstance(order_by, dict) and order_by:
			field = str(order_by.get("field", "") or "").strip()
			direction = str(order_by.get("direction", "asc") or "asc").strip().lower()
			if field:
				rows.sort(key=lambda row: self._sort_key(row, field), reverse=direction == "desc")
		if limit_raw is not None:
			try:
				limit = max(0, int(limit_raw))
			except Exception:
				limit = 0
			rows = rows[:limit]
		return rows

	def _build_row(self, ws: Any, entity: Any, select: Any, context: dict[str, Any]) -> dict[str, Any]:
		entity_id = str(getattr(entity, "entity_id", "") or "")
		if not isinstance(select, list) or not select:
			return {"entity_id": entity_id}
		row: dict[str, Any] = {}
		for item in select:
			if isinstance(item, str):
				field = item.strip()
				if not field:
					continue
				row[self._field_key(field)] = resolve_value(ws, field, context)
				continue
			if isinstance(item, dict):
				key = str(item.get("as", "") or "").strip()
				field = str(item.get("field", "") or "").strip()
				if not key or not field:
					continue
				row[key] = resolve_value(ws, field, context)
		return row

	@staticmethod
	def _field_key(field: str) -> str:
		text = str(field or "").strip()
		if text.startswith("target."):
			text = text[len("target.") :]
		return text.replace(".", "_")

	@staticmethod
	def _sort_key(row: dict[str, Any], field: str) -> tuple[int, Any]:
		key = QueryEngine._field_key(field)
		value = row.get(key)
		if value is None:
			return (1, "")
		try:
			return (0, float(value))
		except Exception:
			return (0, str(value))
