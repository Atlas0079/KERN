from __future__ import annotations

from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..execution_errors import executor_error, is_execution_error_event
from ..query import QueryEngine
from ._effect_binder import BindError, _base_bind, _require_param


def _bind_apply_to_query(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	query = _require_param(params, effect_type, "query")
	bundle = _require_param(params, effect_type, "bundle")
	if not isinstance(query, dict):
		raise BindError(effect_type, ["query_object"])
	if not isinstance(bundle, dict):
		raise BindError(effect_type, ["bundle_object"])
	limit = params.get("limit", None)
	if limit is not None:
		try:
			limit_value = max(0, int(limit))
		except Exception:
			raise BindError(effect_type, ["limit"])
	else:
		limit_value = None
	return {
		"effect": effect_type,
		"query": dict(query),
		"bundle": effect_bundle_from_raw(bundle).to_dict(),
		"limit": limit_value,
	}, ctx


def execute_apply_to_query(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	query = dict(data.get("query", {}) or {})
	select = query.get("select", []) or []
	if isinstance(select, list) and select:
		has_entity_id = False
		for item in list(select):
			if isinstance(item, str) and item.strip() in {"entity_id", "target.entity_id"}:
				has_entity_id = True
			if isinstance(item, dict) and str(item.get("as", "") or "").strip() == "entity_id":
				has_entity_id = True
		if not has_entity_id:
			query["select"] = [*select, {"field": "target.entity_id", "as": "entity_id"}]
	bundle = dict(data.get("bundle", {}) or {})
	limit = data.get("limit", None)
	if limit is not None:
		try:
			limit_value = max(0, int(limit))
		except Exception:
			return executor_error("ApplyToQuery: invalid limit")
		query_limit = query.get("limit", None)
		if query_limit is None:
			query["limit"] = limit_value
		else:
			try:
				query["limit"] = min(max(0, int(query_limit)), limit_value)
			except Exception:
				return executor_error("ApplyToQuery: invalid query.limit")
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	if not callable(execute):
		return executor_error("ApplyToQuery: execute service missing")
	rows = QueryEngine().execute(ws, query, context)
	events: list[dict[str, Any]] = []
	applied = 0
	matched = 0
	for index, row in enumerate(list(rows or [])):
		if not isinstance(row, dict):
			continue
		matched += 1
		entity_id = str(row.get("entity_id", "") or "").strip()
		if not entity_id:
			continue
		if hasattr(ws, "get_entity_by_id") and ws.get_entity_by_id(entity_id) is None:
			continue
		child_context = dict(context or {})
		if "target_id" in child_context and "outer_target_id" not in child_context:
			child_context["outer_target_id"] = str(child_context.get("target_id", "") or "")
		child_context["target_id"] = entity_id
		child_context["query_target_id"] = entity_id
		child_context["query_index"] = index
		child_context["query_row"] = dict(row)
		result_events = execute(bundle, child_context)
		events.extend(list(result_events or []))
		applied += 1
		for ev in list(result_events or []):
			if is_execution_error_event(ev):
				return events
	events.append({"type": "QueryApplied", "matched": matched, "applied": applied})
	return events
