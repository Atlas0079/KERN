from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ._effect_binder import BindError, bind_effect_input
from ..effect_bundle import effect_bundle_from_raw
from ..effects import EffectCatalog, EffectResolutionError, build_core_effect_catalog
from ..execution_errors import ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE, executor_error, is_execution_error_event
from ..entity_ref_resolver import resolve_entity
from ..models.components import ContainerComponent


def get_executor_effect_types(effect_catalog: EffectCatalog | None = None) -> set[str]:
	catalog = effect_catalog or build_core_effect_catalog()
	ok: set[str] = set()
	for effect_name in catalog.effect_ids():
		handler = catalog.resolve_handler(str(effect_name))
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
	effect_catalog: EffectCatalog = field(default_factory=build_core_effect_catalog)

	def __post_init__(self) -> None:
		self.effect_catalog.freeze()

	def execute(self, ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			normalized_data, merged_ctx = bind_effect_input(ws, effect_data, context, self.effect_catalog)
		except BindError as e:
			return [
				{
					"type": "BindError",
					"kind": ERROR_KIND_CONTRACT,
					"effect": str(getattr(e, "effect_type", "") or ""),
					"missing": list(getattr(e, "missing", []) or []),
					"message": str(e),
					"recoverable": False,
				}
			]
		except EffectResolutionError as exc:
			return executor_error(
				str(exc),
				kind=ERROR_KIND_CONTRACT,
				code="EFFECT_BINDER_RESOLUTION_FAILED",
				effect=exc.effect_id,
			)
		effect_type = normalized_data.get("effect")
		if not effect_type:
			return executor_error("missing effect type", kind=ERROR_KIND_CONTRACT, code="MISSING_EFFECT_TYPE")
		effect_name = str(effect_type)
		if not self.effect_catalog.contains(effect_name):
			return executor_error(f"unknown effect type: {effect_type}", kind=ERROR_KIND_CONTRACT, code="UNKNOWN_EFFECT_TYPE", effect=effect_name)
		try:
			handler = self.effect_catalog.resolve_handler(effect_name)
		except EffectResolutionError as exc:
			return executor_error(
				str(exc),
				kind=ERROR_KIND_CONTRACT,
				code="EFFECT_HANDLER_RESOLUTION_FAILED",
				effect=exc.effect_id,
			)
		if not callable(handler):
			return executor_error(f"effect handler missing: {effect_name}", kind=ERROR_KIND_CONTRACT, code="EFFECT_HANDLER_MISSING", effect=effect_name)
		snapshot = self._snapshot_world(ws)
		try:
			events = handler(self, ws, normalized_data, merged_ctx)
		except Exception as exc:
			self._restore_world(ws, snapshot)
			return executor_error(f"{effect_name}: handler exception ({exc})", kind=ERROR_KIND_ENGINE, code="EFFECT_HANDLER_EXCEPTION", effect=effect_name)
		error_event = self._first_error_event(events)
		if error_event is not None:
			self._restore_world(ws, snapshot)
			clean_error = dict(error_event)
			clean_error["effect_rolled_back"] = True
			clean_error.setdefault("failed_effect", effect_name)
			return [clean_error]
		return events

	def execute_bundle(self, ws: Any, bundle_data: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
		bundle = effect_bundle_from_raw(bundle_data)
		snapshot = self._snapshot_world(ws)
		context_snapshot = deepcopy(context) if isinstance(context, dict) else None
		events: list[dict[str, Any]] = []
		for idx, effect in enumerate(list(bundle.effects or [])):
			if not isinstance(effect, dict):
				continue
			effect_events = self.execute(ws, effect, context)
			error_event = self._first_error_event(effect_events)
			if error_event is not None:
				self._restore_world(ws, snapshot)
				if isinstance(context, dict) and isinstance(context_snapshot, dict):
					context.clear()
					context.update(context_snapshot)
				clean_error = dict(error_event)
				clean_error["bundle_rolled_back"] = True
				clean_error["failed_effect_index"] = int(idx)
				clean_error.setdefault("failed_effect", str(effect.get("effect", "") or ""))
				return [clean_error]
			events.extend(effect_events)
		return events

	def _first_error_event(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
		for ev in list(events or []):
			if is_execution_error_event(ev):
				return dict(ev)
		return None

	def _snapshot_world(self, ws: Any) -> dict[str, Any]:
		return {
			"game_time": deepcopy(getattr(ws, "game_time", None)),
			"entities": deepcopy(getattr(ws, "entities", {})),
			"locations": deepcopy(getattr(ws, "locations", {})),
			"environment_scopes": deepcopy(getattr(ws, "environment_scopes", {})),
			"tasks": deepcopy(getattr(ws, "tasks", {})),
			"paths": deepcopy(getattr(ws, "paths", {})),
			"event_log": deepcopy(getattr(ws, "event_log", [])),
			"_event_seq": int(getattr(ws, "_event_seq", 0) or 0),
			"interaction_log": deepcopy(getattr(ws, "interaction_log", [])),
			"_interaction_seq": int(getattr(ws, "_interaction_seq", 0) or 0),
		}

	def _restore_world(self, ws: Any, snapshot: dict[str, Any]) -> None:
		for key, value in dict(snapshot or {}).items():
			setattr(ws, key, deepcopy(value))

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

	def require_entity(
		self,
		ws: Any,
		ctx: dict[str, Any],
		key_or_idkey: str,
		effect_name: str,
		missing_label: str | None = None,
	):
		entity = self._resolve_entity_from_ctx(ws, ctx, key_or_idkey)
		if entity is None:
			label = str(missing_label or key_or_idkey or "entity")
			return None, executor_error(f"{effect_name}: {label} missing")
		return entity, None

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
