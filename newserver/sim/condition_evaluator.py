from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..entity_ref_resolver import resolve_entity
from ..models.components import StatusComponent


@dataclass
class ConditionEvaluator:
	def evaluate(self, ws: Any, condition: dict[str, Any] | None, context: dict[str, Any] | None) -> bool:
		if not isinstance(condition, dict) or not condition:
			return True
		ctx = context if isinstance(context, dict) else {}
		c_type = str(condition.get("type", "") or "").strip()
		if c_type == "all":
			items = condition.get("conditions", []) or []
			return all(self.evaluate(ws, c if isinstance(c, dict) else {}, ctx) for c in items)
		if c_type == "any":
			items = condition.get("conditions", []) or []
			return any(self.evaluate(ws, c if isinstance(c, dict) else {}, ctx) for c in items)
		if c_type == "not":
			sub = condition.get("condition", {}) or {}
			return not self.evaluate(ws, sub if isinstance(sub, dict) else {}, ctx)
		if c_type == "event_field_eq":
			field_name = str(condition.get("field", "") or "")
			expected = condition.get("value")
			event = ctx.get("event", {}) or {}
			if not isinstance(event, dict) or not field_name:
				return False
			return event.get(field_name) == expected
		if c_type == "has_tag":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			tag = str(condition.get("tag", "") or "")
			if target is None or not tag or not hasattr(target, "has_tag"):
				return False
			return bool(target.has_tag(tag))
		if c_type == "has_tags":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			tags_raw = condition.get("tags", []) or []
			match_mode = str(condition.get("match", "all") or "all").strip().lower()
			if target is None or not hasattr(target, "has_tag"):
				return False
			if not isinstance(tags_raw, list) or not tags_raw:
				return False
			tags = [str(x).strip() for x in tags_raw if str(x).strip()]
			if not tags:
				return False
			if match_mode == "any":
				return any(bool(target.has_tag(tag)) for tag in tags)
			return all(bool(target.has_tag(tag)) for tag in tags)
		if c_type == "has_component":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			component_name = str(condition.get("component", "") or "")
			if target is None or not component_name or not hasattr(target, "get_component"):
				return False
			return target.get_component(component_name) is not None
		if c_type == "has_status":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			status_id = str(condition.get("status_id", "") or "")
			if target is None or not status_id:
				return False
			comp = target.get_component("StatusComponent") if hasattr(target, "get_component") else None
			if not isinstance(comp, StatusComponent):
				return False
			return comp.has_status(status_id)
		if c_type == "compare_property":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			comp_name = str(condition.get("component", "") or "")
			prop_name = str(condition.get("property", "") or "")
			op = str(condition.get("op", "==") or "==")
			expected = condition.get("value")
			if target is None or not comp_name or not prop_name:
				return False
			comp = target.get_component(comp_name) if hasattr(target, "get_component") else None
			if comp is None:
				return False
			actual = getattr(comp, prop_name, None)
			return self._compare(actual, expected, op)
		if c_type == "inventory_contains":
			owner = self._resolve_entity(ws, condition.get("owner", "self"), ctx)
			item = self._resolve_entity(ws, condition.get("item_ref", "target"), ctx)
			if owner is None or item is None or not hasattr(owner, "get_component"):
				return False
			container = owner.get_component("ContainerComponent")
			if container is None or not hasattr(container, "get_all_item_ids"):
				return False
			return str(getattr(item, "entity_id", "") or "") in set(container.get_all_item_ids())
		if c_type == "inventory_has_tag":
			owner = self._resolve_entity(ws, condition.get("owner", "self"), ctx)
			tag = str(condition.get("tag", "") or "").strip()
			min_count = int(condition.get("min_count", 1) or 1)
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
		if c_type == "same_location":
			left = self._resolve_entity(ws, condition.get("left", "self"), ctx)
			right = self._resolve_entity(ws, condition.get("right", "target"), ctx)
			if left is None or right is None:
				return False
			if not hasattr(ws, "get_location_of_entity"):
				return False
			left_loc = ws.get_location_of_entity(str(getattr(left, "entity_id", "") or ""))
			right_loc = ws.get_location_of_entity(str(getattr(right, "entity_id", "") or ""))
			if left_loc is None or right_loc is None:
				return False
			return str(getattr(left_loc, "location_id", "") or "") == str(getattr(right_loc, "location_id", "") or "")
		if c_type == "param_eq":
			key = str(condition.get("key", "") or "").strip()
			expected = condition.get("value")
			if not key:
				return False
			params = ctx.get("parameters", {}) or {}
			if not isinstance(params, dict):
				return False
			return params.get(key) == expected
		if c_type == "compare_fields":
			# Support comparing fields from event/context/entity properties
			# Left/Right can be "event.field", "self.location_id", "target.component.property" etc.
			# For MVP, we support:
			# - "event.field" (from context["event"])
			# - "self.location_id" (helper)
			# - "self.entity_id"
			left_ref = str(condition.get("left", "") or "")
			right_ref = str(condition.get("right", "") or "")
			op = str(condition.get("op", "==") or "==")
			
			def _resolve_val(ref: str) -> Any:
				if ref.startswith("event."):
					field = ref[len("event."):]
					event = ctx.get("event", {}) or {}
					if isinstance(event, dict):
						return event.get(field)
					return None
				if ref == "self.entity_id":
					return str(ctx.get("self_id", "") or "")
				if ref == "self.location_id":
					sid = str(ctx.get("self_id", "") or "")
					if sid and hasattr(ws, "get_location_of_entity"):
						loc = ws.get_location_of_entity(sid)
						return str(loc.location_id) if loc else None
					return None
				if ref.startswith("self."):
					raise NotImplementedError(f"compare_fields self.* is not implemented: {ref}")
				return ref # Treat as literal

			left_val = _resolve_val(left_ref)
			right_val = _resolve_val(right_ref)
			return self._compare(left_val, right_val, op)

		return False

	def explain(self, ws: Any, condition: dict[str, Any] | None, context: dict[str, Any] | None, path: str = "root") -> dict[str, Any]:
		if not isinstance(condition, dict) or not condition:
			return {"ok": True, "path": path, "reason": "", "detail": {}}
		ctx = context if isinstance(context, dict) else {}
		c_type = str(condition.get("type", "") or "").strip()
		if c_type == "all":
			items = condition.get("conditions", []) or []
			for idx, item in enumerate(items):
				child = self.explain(ws, item if isinstance(item, dict) else {}, ctx, f"{path}.conditions[{idx}]")
				if not bool(child.get("ok", False)):
					return {
						"ok": False,
						"path": path,
						"reason": "ALL_CHILD_FAILED",
						"detail": {"failed_index": idx, "child": child},
					}
			return {"ok": True, "path": path, "reason": "", "detail": {}}
		if c_type == "any":
			items = condition.get("conditions", []) or []
			children: list[dict[str, Any]] = []
			for idx, item in enumerate(items):
				child = self.explain(ws, item if isinstance(item, dict) else {}, ctx, f"{path}.conditions[{idx}]")
				children.append(child)
				if bool(child.get("ok", False)):
					return {"ok": True, "path": path, "reason": "", "detail": {"matched_index": idx}}
			return {"ok": False, "path": path, "reason": "ANY_ALL_FAILED", "detail": {"children": children}}
		if c_type == "not":
			sub = condition.get("condition", {}) or {}
			child = self.explain(ws, sub if isinstance(sub, dict) else {}, ctx, f"{path}.condition")
			if bool(child.get("ok", False)):
				return {"ok": False, "path": path, "reason": "NOT_CONDITION_MATCHED", "detail": {"child": child}}
			return {"ok": True, "path": path, "reason": "", "detail": {}}
		if c_type == "has_tag":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			tag = str(condition.get("tag", "") or "")
			if target is None:
				return {"ok": False, "path": path, "reason": "TARGET_MISSING", "detail": {"target": condition.get("target", "self")}}
			if not tag:
				return {"ok": False, "path": path, "reason": "TAG_MISSING", "detail": {}}
			ok = bool(hasattr(target, "has_tag") and target.has_tag(tag))
			return {"ok": ok, "path": path, "reason": "" if ok else "HAS_TAG_FALSE", "detail": {"tag": tag, "target_id": str(getattr(target, "entity_id", "") or "")}}
		if c_type == "has_tags":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			if target is None:
				return {"ok": False, "path": path, "reason": "TARGET_MISSING", "detail": {"target": condition.get("target", "self")}}
			tags_raw = condition.get("tags", []) or []
			if not isinstance(tags_raw, list) or not tags_raw:
				return {"ok": False, "path": path, "reason": "TAGS_MISSING", "detail": {}}
			tags = [str(x).strip() for x in tags_raw if str(x).strip()]
			match_mode = str(condition.get("match", "all") or "all").strip().lower()
			if match_mode == "any":
				ok = any(bool(target.has_tag(tag)) for tag in tags)
				return {"ok": ok, "path": path, "reason": "" if ok else "HAS_TAGS_ANY_FALSE", "detail": {"tags": tags, "target_id": str(getattr(target, "entity_id", "") or "")}}
			ok = all(bool(target.has_tag(tag)) for tag in tags)
			return {"ok": ok, "path": path, "reason": "" if ok else "HAS_TAGS_ALL_FALSE", "detail": {"tags": tags, "target_id": str(getattr(target, "entity_id", "") or "")}}
		if c_type == "has_status":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			status_id = str(condition.get("status_id", "") or "")
			if target is None:
				return {"ok": False, "path": path, "reason": "TARGET_MISSING", "detail": {"target": condition.get("target", "self")}}
			if not status_id:
				return {"ok": False, "path": path, "reason": "STATUS_ID_MISSING", "detail": {}}
			comp = target.get_component("StatusComponent") if hasattr(target, "get_component") else None
			statuses = list(comp.statuses) if isinstance(comp, StatusComponent) else []
			ok = bool(isinstance(comp, StatusComponent) and comp.has_status(status_id))
			return {"ok": ok, "path": path, "reason": "" if ok else "HAS_STATUS_FALSE", "detail": {"status_id": status_id, "target_id": str(getattr(target, "entity_id", "") or ""), "statuses": [str(x) for x in statuses]}}
		if c_type == "inventory_contains":
			owner = self._resolve_entity(ws, condition.get("owner", "self"), ctx)
			item = self._resolve_entity(ws, condition.get("item_ref", "target"), ctx)
			if owner is None:
				return {"ok": False, "path": path, "reason": "OWNER_MISSING", "detail": {"owner": condition.get("owner", "self")}}
			if item is None:
				return {"ok": False, "path": path, "reason": "ITEM_MISSING", "detail": {"item_ref": condition.get("item_ref", "target")}}
			container = owner.get_component("ContainerComponent") if hasattr(owner, "get_component") else None
			items = list(container.get_all_item_ids()) if container is not None and hasattr(container, "get_all_item_ids") else []
			ok = str(getattr(item, "entity_id", "") or "") in set(items)
			return {"ok": ok, "path": path, "reason": "" if ok else "INVENTORY_CONTAINS_FALSE", "detail": {"owner_id": str(getattr(owner, "entity_id", "") or ""), "item_id": str(getattr(item, "entity_id", "") or "")}}
		if c_type == "inventory_has_tag":
			owner = self._resolve_entity(ws, condition.get("owner", "self"), ctx)
			tag = str(condition.get("tag", "") or "").strip()
			min_count = int(condition.get("min_count", 1) or 1)
			if owner is None:
				return {"ok": False, "path": path, "reason": "OWNER_MISSING", "detail": {"owner": condition.get("owner", "self")}}
			container = owner.get_component("ContainerComponent") if hasattr(owner, "get_component") else None
			items = list(container.get_all_item_ids()) if container is not None and hasattr(container, "get_all_item_ids") else []
			count = 0
			for item_id in items:
				ent = ws.get_entity_by_id(str(item_id)) if hasattr(ws, "get_entity_by_id") else None
				if ent is not None and hasattr(ent, "has_tag") and bool(ent.has_tag(tag)):
					count += 1
			ok = count >= max(1, min_count)
			return {"ok": ok, "path": path, "reason": "" if ok else "INVENTORY_HAS_TAG_FALSE", "detail": {"owner_id": str(getattr(owner, "entity_id", "") or ""), "tag": tag, "count": int(count), "required": int(min_count)}}
		if c_type == "same_location":
			left = self._resolve_entity(ws, condition.get("left", "self"), ctx)
			right = self._resolve_entity(ws, condition.get("right", "target"), ctx)
			if left is None or right is None:
				return {"ok": False, "path": path, "reason": "SAME_LOCATION_ENTITY_MISSING", "detail": {"left": condition.get("left", "self"), "right": condition.get("right", "target")}}
			left_loc = ws.get_location_of_entity(str(getattr(left, "entity_id", "") or "")) if hasattr(ws, "get_location_of_entity") else None
			right_loc = ws.get_location_of_entity(str(getattr(right, "entity_id", "") or "")) if hasattr(ws, "get_location_of_entity") else None
			if left_loc is None or right_loc is None:
				return {"ok": False, "path": path, "reason": "SAME_LOCATION_LOC_MISSING", "detail": {"left_id": str(getattr(left, "entity_id", "") or ""), "right_id": str(getattr(right, "entity_id", "") or "")}}
			ok = str(getattr(left_loc, "location_id", "") or "") == str(getattr(right_loc, "location_id", "") or "")
			return {"ok": ok, "path": path, "reason": "" if ok else "SAME_LOCATION_FALSE", "detail": {"left_location_id": str(getattr(left_loc, "location_id", "") or ""), "right_location_id": str(getattr(right_loc, "location_id", "") or "")}}
		if c_type == "compare_property":
			ok = self.evaluate(ws, condition, ctx)
			if ok:
				return {"ok": True, "path": path, "reason": "", "detail": {}}
			return {
				"ok": False,
				"path": path,
				"reason": "COMPARE_PROPERTY_FALSE",
				"detail": {
					"target": condition.get("target", "self"),
					"component": condition.get("component", ""),
					"property": condition.get("property", ""),
					"op": condition.get("op", "=="),
					"value": condition.get("value"),
				},
			}
		ok = self.evaluate(ws, condition, ctx)
		return {
			"ok": bool(ok),
			"path": path,
			"reason": "" if ok else "CONDITION_FALSE",
			"detail": {"type": c_type},
		}

	def _resolve_entity(self, ws: Any, target_ref: Any, context: dict[str, Any]) -> Any:
		return resolve_entity(ws, target_ref, context, allow_literal=True)

	@staticmethod
	def _compare(actual: Any, expected: Any, op: str) -> bool:
		if op in ("==", "!="):
			return (actual == expected) if op == "==" else (actual != expected)
		try:
			a = float(actual)
			b = float(expected)
		except Exception:
			return False
		if op == "<":
			return a < b
		if op == "<=":
			return a <= b
		if op == ">":
			return a > b
		if op == ">=":
			return a >= b
		return False
