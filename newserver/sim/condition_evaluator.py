from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..entity_ref_resolver import resolve_entity


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
		if c_type == "has_component":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			component_name = str(condition.get("component", "") or "")
			if target is None or not component_name or not hasattr(target, "get_component"):
				return False
			return target.get_component(component_name) is not None
		if c_type == "has_condition":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			condition_id = str(condition.get("condition_id", "") or "")
			if target is None or not condition_id:
				return False
			comp = target.get_component("ConditionComponent") if hasattr(target, "get_component") else None
			data = getattr(comp, "data", None)
			if not isinstance(data, dict):
				return False
			conditions = data.get("conditions", []) or []
			return condition_id in conditions
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
		if c_type == "check_cooldown":
			target = self._resolve_entity(ws, condition.get("target", "self"), ctx)
			key = str(condition.get("key", "") or "")
			duration = int(condition.get("duration", 0))
			if target is None or not key:
				return False
			comp = target.get_component("CooldownComponent") if hasattr(target, "get_component") else None
			if comp is None or not hasattr(comp, "is_ready"):
				return True
			current_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0))
			return comp.is_ready(key, current_tick, duration)
		if c_type == "inventory_contains":
			owner = self._resolve_entity(ws, condition.get("owner", "self"), ctx)
			item = self._resolve_entity(ws, condition.get("item_ref", "target"), ctx)
			if owner is None or item is None or not hasattr(owner, "get_component"):
				return False
			container = owner.get_component("ContainerComponent")
			if container is None or not hasattr(container, "get_all_item_ids"):
				return False
			return str(getattr(item, "entity_id", "") or "") in set(container.get_all_item_ids())
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
