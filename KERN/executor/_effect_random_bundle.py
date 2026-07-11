from __future__ import annotations

import random
from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..execution_errors import executor_error
from ._effect_binder import BindError, _base_bind
from ._effect_child_bundle import child_bundle_error_message, run_child_bundle


def _bind_random_bundle(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	entries_raw = params.get("entries", []) or []
	if not isinstance(entries_raw, list) or not entries_raw:
		raise BindError(effect_type, ["entries"])
	entries: list[dict[str, Any]] = []
	for idx, item in enumerate(entries_raw):
		if not isinstance(item, dict):
			raise BindError(effect_type, [f"entries[{idx}]"])
		try:
			weight = float(item.get("weight", 0.0) or 0.0)
		except Exception:
			raise BindError(effect_type, [f"entries[{idx}].weight"])
		if weight < 0:
			raise BindError(effect_type, [f"entries[{idx}].weight"])
		try:
			bundle = effect_bundle_from_raw(item.get("bundle", {}) or {})
		except Exception:
			raise BindError(effect_type, [f"entries[{idx}].bundle"])
		entries.append(
			{
				"id": str(item.get("id", "") or ""),
				"label": str(item.get("label", "") or ""),
				"weight": weight,
				"bundle": bundle.to_dict(),
			}
		)
	if sum(float(x.get("weight", 0.0) or 0.0) for x in entries) <= 0:
		raise BindError(effect_type, ["entries.total_weight"])
	return {"effect": effect_type, "table_id": str(params.get("table_id", "") or ""), "entries": entries}, ctx


def execute_random_bundle(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	entries = [dict(x) for x in list(data.get("entries", []) or []) if isinstance(x, dict)]
	weighted = [x for x in entries if float(x.get("weight", 0.0) or 0.0) > 0]
	if not weighted:
		return executor_error("RandomBundle: entries total_weight must be positive")
	total_weight = sum(float(x.get("weight", 0.0) or 0.0) for x in weighted)
	roll = random.uniform(0.0, total_weight)
	selected = weighted[-1]
	cumulative = 0.0
	for item in weighted:
		cumulative += float(item.get("weight", 0.0) or 0.0)
		if roll <= cumulative:
			selected = item
			break
	selected_index = entries.index(selected) if selected in entries else -1
	bundle = effect_bundle_from_raw(selected.get("bundle", {}) or {})
	resolved_event = {
		"type": "RandomBundleResolved",
		"table_id": str(data.get("table_id", "") or ""),
		"entry_id": str(selected.get("id", "") or ""),
		"entry_label": str(selected.get("label", "") or ""),
		"entry_index": int(selected_index),
		"weight": float(selected.get("weight", 0.0) or 0.0),
		"total_weight": float(total_weight),
		"roll": float(roll),
		"bundle_effect_count": int(len(bundle.effects or [])),
	}
	if bundle.is_empty():
		return [resolved_event]
	result = run_child_bundle(executor, ws, bundle.to_dict(), dict(context or {}))
	if result.failed:
		return [resolved_event, *executor_error(child_bundle_error_message(result, "RandomBundle", "selected"))]
	return [resolved_event, *result.events]
