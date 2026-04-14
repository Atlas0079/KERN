from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._effect_binder import BindError, bind_effect_input
from ..entity_ref_resolver import resolve_entity
from ..effect_contract import EFFECT_TYPES, resolve_effect_handler_callable
from ..models.components import ContainerComponent


def get_executor_effect_types() -> set[str]:
	ok: set[str] = set()
	for effect_name in EFFECT_TYPES:
		handler = resolve_effect_handler_callable(str(effect_name))
		if callable(handler):
			ok.add(str(effect_name))
	return ok


@dataclass
class WorldExecutor:
	"""
	Executor: Single entry point for world "write operations" (Align with Godot WorldExecutor.gd).

	Note:
	- This class only concerns "how to write", not "why to write" (Decision logic in Manager/LLM/Policy layer).
	- Effect Input Contract:
	  - data(effect_data): declarative operation payload, describes what to do.
	  - context: runtime invocation environment, describes where/who this call runs in.
	  - Handlers should primarily consume normalized data produced by binder; context is for runtime identity and refs.
	"""

	# Template required when creating entity at runtime; if not provided, CreateEntity will report error event
	entity_templates: dict[str, Any] | None = None

	def execute(self, ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			normalized_data, merged_ctx = bind_effect_input(ws, effect_data, context)
		except BindError as e:
			return [
				{
					"type": "BindError",
					"effect": str(getattr(e, "effect_type", "") or ""),
					"missing": list(getattr(e, "missing", []) or []),
					"message": str(e),
				}
			]
		effect_type = normalized_data.get("effect")
		if not effect_type:
			return [{"type": "ExecutorError", "message": "missing effect type"}]
		effect_name = str(effect_type)
		if effect_name not in EFFECT_TYPES:
			return [{"type": "ExecutorError", "message": f"unknown effect type: {effect_type}"}]
		handler = resolve_effect_handler_callable(effect_name)
		if not callable(handler):
			return [{"type": "ExecutorError", "message": f"effect handler missing: {effect_name}"}]
		return handler(self, ws, normalized_data, merged_ctx)

	def _resolve_entity_from_ctx(self, ws: Any, ctx: dict[str, Any], key_or_idkey: str):
		ctx_dict = dict(ctx) if isinstance(ctx, dict) else {}
		key = str(key_or_idkey or "")
		if not key:
			return None
		direct_id = str(ctx_dict.get(key, "") or "")
		if direct_id:
			ent = ws.get_entity_by_id(direct_id)
			if ent is not None:
				return ent
		id_key = key if key.endswith("_id") else f"{key}_id"
		id_val = str(ctx_dict.get(id_key, "") or "")
		if id_val:
			ent = ws.get_entity_by_id(id_val)
			if ent is not None:
				return ent
		return resolve_entity(ws, key, ctx_dict, allow_literal=True)

	def _resolve_container_or_location_from_ctx(self, ws: Any, ctx: dict[str, Any], key_or_idkey: str):
		id_key = key_or_idkey if str(key_or_idkey).endswith("_id") else f"{key_or_idkey}_id"
		id_val = str((ctx or {}).get(id_key, ""))
		ent = ws.get_entity_by_id(id_val)
		if ent is not None and isinstance(ent.get_component("ContainerComponent"), ContainerComponent):
			return ent
		loc = ws.get_location_by_id(id_val)
		if loc is not None:
			return loc
		return None
