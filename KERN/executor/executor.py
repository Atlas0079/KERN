from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ._effect_binder import BindError, bind_effect_input
from ..component_catalog import ComponentCatalog, build_core_component_catalog
from ..effect_bundle import effect_bundle_from_raw
from ..effect_record import build_effect_events
from ..effects import EffectCatalog, EffectResolutionError, build_core_effect_catalog
from ..external_runtime import ExternalRuntimeBridge
from ..execution_errors import ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE, KernFailure, executor_error
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

	# Template required when creating entity at runtime; missing templates raise KernFailure.
	entity_templates: dict[str, Any] | None = None
	effect_catalog: EffectCatalog = field(default_factory=build_core_effect_catalog)
	component_catalog: ComponentCatalog = field(default_factory=build_core_component_catalog)
	_bundle_depth: int = field(default=0, init=False, repr=False)
	_bundle_transaction_id: str = field(default="", init=False, repr=False)
	_bundle_id_stack: list[str] = field(default_factory=list, init=False, repr=False)
	_bundle_uses_external: bool = field(default=False, init=False, repr=False)
	_bundle_deferred_irreversible: list[tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=list, init=False, repr=False)

	def __post_init__(self) -> None:
		self.effect_catalog.freeze()
		self.component_catalog.freeze()

	def execute(self, ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		raw_effect = dict(effect_data) if isinstance(effect_data, dict) else effect_data
		execution_context = dict(context or {})
		# Effects invoked from a handler (for example a lifecycle or interaction
		# effect) remain part of the currently executing bundle.  Callers that are
		# already inside execute_bundle provide the explicit transaction fields;
		# this fallback keeps direct nested executor.execute calls traceable too.
		if self._bundle_id_stack:
			execution_context.setdefault("_kern_bundle_id", self._bundle_id_stack[-1])
			execution_context.setdefault(
				"_kern_parent_bundle_id",
				self._bundle_id_stack[-2] if len(self._bundle_id_stack) > 1 else "",
			)
			execution_context.setdefault("_kern_effect_index", -1)
		try:
			normalized_data, merged_ctx = bind_effect_input(ws, effect_data, execution_context, self.effect_catalog)
		except BindError as e:
			e.add_context(
				effect=str(getattr(e, "effect_type", "") or ""),
				missing=list(getattr(e, "missing", []) or []),
				raw_effect=raw_effect,
				invocation_context=execution_context,
			)
			raise
		except EffectResolutionError as exc:
			executor_error(
				str(exc),
				kind=ERROR_KIND_CONTRACT,
				code="EFFECT_BINDER_RESOLUTION_FAILED",
				effect=exc.effect_id,
				origin="binder",
				phase="effect_binding",
			)
		except KernFailure as exc:
			exc.add_context(raw_effect=raw_effect, invocation_context=execution_context)
			raise
		except Exception as exc:
			raise KernFailure(
				"EFFECT_BINDER_FAILED",
				f"effect binder failed: {exc}",
				origin="binder",
				phase="effect_binding",
				context={"raw_effect": raw_effect, "invocation_context": execution_context},
			) from exc
		if not isinstance(normalized_data, dict) or not isinstance(merged_ctx, dict):
			raise KernFailure(
				"EFFECT_BINDER_RESULT_INVALID",
				"effect binder must return (dict, dict)",
				origin="binder",
				phase="effect_binding",
				context={"effect": raw_effect, "normalized_data": normalized_data, "context": merged_ctx},
			)
		effect_type = normalized_data.get("effect")
		if not effect_type:
			executor_error("missing effect type", kind=ERROR_KIND_CONTRACT, code="MISSING_EFFECT_TYPE")
		effect_name = str(effect_type)
		if not self.effect_catalog.contains(effect_name):
			executor_error(f"unknown effect type: {effect_type}", kind=ERROR_KIND_CONTRACT, code="UNKNOWN_EFFECT_TYPE", effect=effect_name, phase="effect_resolution")
		try:
			handler = self.effect_catalog.resolve_handler(effect_name)
		except EffectResolutionError as exc:
			executor_error(
				str(exc),
				kind=ERROR_KIND_CONTRACT,
				code="EFFECT_HANDLER_RESOLUTION_FAILED",
				effect=exc.effect_id,
				origin="executor",
				phase="handler_resolution",
			)
		if not callable(handler):
			executor_error(f"effect handler missing: {effect_name}", kind=ERROR_KIND_CONTRACT, code="EFFECT_HANDLER_MISSING", effect=effect_name)
		snapshot = self._snapshot_world(ws)
		try:
			events = handler(self, ws, normalized_data, merged_ctx)
		except KernFailure as exc:
			self._restore_world(ws, snapshot)
			exc.add_context(effect=effect_name, phase="effect_execution", input=normalized_data, execution_context=merged_ctx)
			raise
		except Exception as exc:
			self._restore_world(ws, snapshot)
			raise KernFailure(
				"EFFECT_HANDLER_EXCEPTION",
				f"{effect_name}: handler exception ({exc})",
				origin="executor",
				phase="effect_execution",
				context={"effect": effect_name, "input": normalized_data, "execution_context": merged_ctx},
			) from exc
		if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
			self._restore_world(ws, snapshot)
			raise KernFailure(
				"EFFECT_HANDLER_RESULT_INVALID",
				f"{effect_name}: handler must return a list of event/fact objects",
				origin="executor",
				phase="effect_execution",
				context={"effect": effect_name, "input": normalized_data, "result": events},
			)
		return build_effect_events(
			effect_name,
			normalized_data,
			merged_ctx,
			events,
			bundle_id=str(merged_ctx.get("_kern_bundle_id", "") or ""),
			parent_bundle_id=str(merged_ctx.get("_kern_parent_bundle_id", "") or ""),
			action_id=str(merged_ctx.get("action_id", "") or ""),
			effect_index=int(merged_ctx.get("_kern_effect_index", -1)),
		)

	def execute_bundle(self, ws: Any, bundle_data: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			bundle = effect_bundle_from_raw(bundle_data)
		except Exception as exc:
			raise KernFailure(
				"INVALID_EFFECT_BUNDLE",
				str(exc),
				origin="executor",
				phase="bundle_binding",
				context={"bundle": bundle_data},
			) from exc
		effect_specs = []
		for index, effect in enumerate(bundle.effects):
			if not isinstance(effect, dict):
				executor_error(
					f"bundle effect[{index}] must be an object",
					kind=ERROR_KIND_CONTRACT,
					code="INVALID_EFFECT_ENTRY",
					context={"bundle": bundle_data, "effect_index": index},
				)
			effect_id = str(effect.get("effect", "") or "")
			if not effect_id:
				executor_error(
					"bundle effect is missing effect type",
					kind=ERROR_KIND_CONTRACT,
					code="MISSING_EFFECT_TYPE",
					context={"bundle": bundle_data, "effect_index": index},
				)
			if not self.effect_catalog.contains(effect_id):
				executor_error(
					f"unknown effect type: {effect_id}",
					kind=ERROR_KIND_CONTRACT,
					code="UNKNOWN_EFFECT_TYPE",
					effect=effect_id,
					phase="bundle_validation",
					context={"bundle": bundle_data, "effect_index": index},
				)
			spec = self.effect_catalog.require(effect_id)
			effect_specs.append(spec)
			if spec.side_effect == "external_irreversible" and index != len(bundle.effects) - 1:
				executor_error(
					f"external irreversible effect must be last in bundle: {effect_id}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_IRREVERSIBLE_NOT_LAST",
					effect=effect_id,
				)
		is_outer_bundle = self._bundle_depth == 0
		parent_bundle_id = self._bundle_id_stack[-1] if self._bundle_id_stack else ""
		bundle_id = str(uuid4())
		if is_outer_bundle:
			self._bundle_transaction_id = str(uuid4())
			self._bundle_uses_external = any(spec.side_effect != "world" for spec in effect_specs)
			self._bundle_deferred_irreversible = []
		transaction_id = str(self._bundle_transaction_id)
		if not is_outer_bundle and any(spec.side_effect != "world" for spec in effect_specs):
			self._bundle_uses_external = True
		if is_outer_bundle and self._bundle_uses_external:
			try:
				self._begin_external_bundle(ws, transaction_id)
			except KernFailure:
				raise
			except Exception as exc:
				raise KernFailure(
					"EXTERNAL_RUNTIME_BEGIN_FAILED",
					str(exc),
					origin="external_runtime",
					phase="bundle_begin",
					context={"transaction_id": transaction_id},
				) from exc
		self._bundle_depth += 1
		self._bundle_id_stack.append(bundle_id)
		snapshot = self._snapshot_world(ws)
		context_snapshot = deepcopy(context) if isinstance(context, dict) else None
		events: list[dict[str, Any]] = []
		try:
			for idx, effect in enumerate(list(bundle.effects or [])):
				if not isinstance(effect, dict):
					continue
				effect_id = str(effect.get("effect", "") or "")
				if self.effect_catalog.contains(effect_id) and self.effect_catalog.require(effect_id).side_effect == "external_irreversible":
					self._bundle_deferred_irreversible.append((effect, self._transaction_context(context, transaction_id, bundle_id, parent_bundle_id, idx)))
					continue
				effect_events = self.execute(ws, effect, self._transaction_context(context, transaction_id, bundle_id, parent_bundle_id, idx))
				events.extend(effect_events)
			if is_outer_bundle:
				for effect, deferred_context in self._bundle_deferred_irreversible:
					effect_events = self.execute(ws, effect, deferred_context)
					events.extend(effect_events)
			if is_outer_bundle and self._bundle_uses_external:
				self._notify_external_bundle_lifecycle(ws, "commit_bundle", transaction_id)
			return events
		except KernFailure as exc:
			self._restore_world(ws, snapshot)
			if isinstance(context, dict) and isinstance(context_snapshot, dict):
				context.clear()
				context.update(context_snapshot)
			exc.add_context(
				bundle_rolled_back=True,
				bundle_id=bundle_id,
				parent_bundle_id=parent_bundle_id,
				transaction_id=transaction_id,
				failed_effect_index=int(idx) if "idx" in locals() else None,
				failed_effect=str(effect.get("effect", "") or "") if "effect" in locals() and isinstance(effect, dict) else None,
			)
			if is_outer_bundle and self._bundle_uses_external:
				try:
					self._notify_external_bundle_lifecycle(ws, "rollback_bundle", transaction_id)
				except Exception as external_exc:
					exc.add_note(f"external rollback notification failed: {external_exc}")
			raise
		except Exception as exc:
			self._restore_world(ws, snapshot)
			raise KernFailure(
				"BUNDLE_EXECUTION_FAILED",
				f"bundle execution failed: {exc}",
				origin="executor",
				phase="bundle_execution",
				context={"bundle_rolled_back": True},
			) from exc
		finally:
			if self._bundle_id_stack:
				self._bundle_id_stack.pop()
			self._bundle_depth -= 1
			if is_outer_bundle:
				if self._bundle_uses_external:
					try:
						self._close_external_bundle(ws, transaction_id)
					except Exception:
						# The primary execution failure is already being propagated.  A
						# close failure must not mask it.
						pass
				self._bundle_transaction_id = ""
				self._bundle_uses_external = False
				self._bundle_deferred_irreversible = []

	def _transaction_context(
		self,
		context: dict[str, Any],
		transaction_id: str,
		bundle_id: str = "",
		parent_bundle_id: str = "",
		effect_index: int = -1,
	) -> dict[str, Any]:
		out = dict(context or {})
		out["_kern_bundle_id"] = str(bundle_id or "")
		out["_kern_parent_bundle_id"] = str(parent_bundle_id or "")
		out["_kern_effect_index"] = int(effect_index)
		if self._bundle_uses_external:
			out["external_transaction_id"] = str(transaction_id)
		return out

	def _external_bridge(self, ws: Any) -> ExternalRuntimeBridge | None:
		services = getattr(ws, "services", {}) or {}
		bridge = services.get("external_runtime_bridge") if isinstance(services, dict) else None
		return bridge if isinstance(bridge, ExternalRuntimeBridge) else None

	def _begin_external_bundle(self, ws: Any, transaction_id: str) -> None:
		bridge = self._external_bridge(ws)
		if bridge is not None:
			bridge.begin_bundle(transaction_id)

	def _notify_external_bundle_lifecycle(self, ws: Any, phase_method: str, transaction_id: str) -> None:
		bridge = self._external_bridge(ws)
		if bridge is None:
			return
		method = getattr(bridge, phase_method)
		method({"transaction_id": str(transaction_id), "receipts": self._external_bundle_receipts(ws, transaction_id)})

	def _external_bundle_receipts(self, ws: Any, transaction_id: str) -> list[dict[str, Any]]:
		bridge = self._external_bridge(ws)
		return bridge.bundle_receipts(transaction_id) if bridge is not None else []

	def _close_external_bundle(self, ws: Any, transaction_id: str) -> None:
		bridge = self._external_bridge(ws)
		if bridge is not None:
			bridge.close_bundle(transaction_id)

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
			"runtime_state": deepcopy(getattr(ws, "runtime_state", None)),
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
