from __future__ import annotations

from typing import Any

from ..entity_ref_resolver import resolve_entity_id
from ..effect_contract import EFFECT_TYPES, resolve_effect_binder_callable


class BindError(RuntimeError):
	def __init__(self, effect_type: str, missing: list[str]):
		self.effect_type = str(effect_type or "")
		self.missing = [str(x) for x in list(missing or []) if str(x)]
		super().__init__(f"{self.effect_type}: missing required context {self.missing}")


def _as_dict(x: Any) -> dict[str, Any]:
	return dict(x) if isinstance(x, dict) else {}


def _resolve_ref_id(ref: Any, ctx: dict[str, Any]) -> str:
	return resolve_entity_id(ref, ctx, allow_literal=False)


def _resolve_param_token(value: Any, ctx: dict[str, Any]) -> Any:
	if isinstance(value, str):
		key = str(value).strip()
		if key.startswith("param:"):
			params = ctx.get("parameters", {}) or {}
			if isinstance(params, dict):
				return params.get(key[len("param:") :], "")
			return ""
		return value
	if isinstance(value, list):
		return [_resolve_param_token(v, ctx) for v in value]
	if isinstance(value, dict):
		return {str(k): _resolve_param_token(v, ctx) for k, v in value.items()}
	return value


def _require_param(params: dict[str, Any], effect_type: str, key: str) -> Any:
	if key not in params:
		raise BindError(effect_type, [key])
	return params.get(key)


def _require_str(params: dict[str, Any], effect_type: str, key: str) -> str:
	raw = _require_param(params, effect_type, key)
	value = str(raw or "").strip()
	if not value:
		raise BindError(effect_type, [key])
	return value


def _require_int(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> int:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	try:
		return int(raw)
	except Exception:
		raise BindError(effect_type, [key])


def _require_float(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> float:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	try:
		return float(raw)
	except Exception:
		raise BindError(effect_type, [key])


def _require_dict(params: dict[str, Any], effect_type: str, key: str, ctx: dict[str, Any]) -> dict[str, Any]:
	raw = _resolve_param_token(_require_param(params, effect_type, key), ctx)
	if not isinstance(raw, dict):
		raise BindError(effect_type, [key])
	return dict(raw)


def _base_bind(effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
	src = _as_dict(effect_data)
	ctx = _as_dict(context)
	effect_type = str(src.get("effect", "") or "")
	params = {k: v for k, v in src.items() if k != "effect"}
	return effect_type, params, ctx


def get_binder_effect_types() -> set[str]:
	ok: set[str] = set()
	for effect_name in EFFECT_TYPES:
		binder = resolve_effect_binder_callable(str(effect_name))
		if callable(binder):
			ok.add(str(effect_name))
	return ok


def bind_effect_input(ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	base_data = _as_dict(effect_data)
	if "context" in base_data:
		eff = str(base_data.get("effect", "") or "")
		raise BindError(eff, ["effect.context is removed; move fields to top-level effect keys"])
	effect_type = str(base_data.get("effect", "") or "")
	if not effect_type:
		return {}, _as_dict(context)
	binder = resolve_effect_binder_callable(effect_type)
	if binder is None:
		if effect_type in EFFECT_TYPES:
			raise BindError(effect_type, ["binder_missing"])
		_, _, ctx = _base_bind(base_data, context)
		return base_data, ctx
	return binder(ws, base_data, context)
