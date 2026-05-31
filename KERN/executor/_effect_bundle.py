from __future__ import annotations

from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..execution_errors import executor_error
from ._effect_binder import _base_bind


def _bind_invoke_bundle(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type, **params}, ctx


def execute_invoke_bundle(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	if isinstance(data.get("bundle"), dict):
		try:
			bundle = effect_bundle_from_raw(data.get("bundle", {}) or {})
		except Exception as exc:
			return executor_error(f"InvokeBundle: invalid bundle ({exc})")
		if not callable(execute):
			return executor_error("InvokeBundle: execute service missing")
		return execute(bundle.to_dict(), context)
	target_key = str(data.get("target", "target") or "target")
	target, err = executor.require_entity(ws, context, target_key, "InvokeBundle", "target")
	if err is not None:
		return err
	component_name = str(data.get("component", "") or "").strip()
	property_name = str(data.get("property", "") or "").strip()
	if not component_name or not property_name:
		return executor_error("InvokeBundle: missing bundle or component/property")
	component = target.get_component(component_name) if hasattr(target, "get_component") else None
	if component is None:
		return executor_error(f"InvokeBundle: component missing {component_name}")
	bundle_raw = getattr(component, property_name, None)
	if bundle_raw is None and hasattr(component, "data") and isinstance(getattr(component, "data"), dict):
		bundle_raw = component.data.get(property_name)
	if bundle_raw is None:
		return executor_error(f"InvokeBundle: bundle property missing {component_name}.{property_name}")
	try:
		bundle = effect_bundle_from_raw(bundle_raw)
	except Exception as exc:
		return executor_error(f"InvokeBundle: invalid component bundle ({exc})")
	if not callable(execute):
		return executor_error("InvokeBundle: execute service missing")
	return execute(bundle.to_dict(), context)
