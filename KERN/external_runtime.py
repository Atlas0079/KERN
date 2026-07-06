from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .execution_errors import ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE, executor_error


@runtime_checkable
class ExternalRuntimeAdapter(Protocol):
	"""
	Protocol implemented by an external application/runtime adapter.

	KERN owns the effect contract and execution boundary. External runtimes own
	their domain-specific operation semantics, such as social messages, phone
	calls, browser actions, or platform notifications.
	"""

	def invoke(self, operation: str, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		"""Run one external operation and return KERN event dictionaries."""
		...


@dataclass
class ExternalRuntimeBridge:
	"""
	Single runtime service for domain-specific external adapters.

	Concrete effect handlers should remain explicit, for example
	SendSocialMessage or ReadSocialInbox. Those handlers use this bridge to
	route their normalized payload to the external runtime that owns the domain.
	"""

	adapters: dict[str, Any] = field(default_factory=dict)

	def has_adapter(self, runtime_id: str) -> bool:
		return bool(str(runtime_id or "").strip() in self.adapters)

	def get_adapter(self, runtime_id: str) -> Any | None:
		rid = str(runtime_id or "").strip()
		if not rid:
			return None
		return self.adapters.get(rid)

	def _validate_events(self, events: Any, *, runtime_id: str, operation: str, source: str) -> list[dict[str, Any]]:
		rid = str(runtime_id or "").strip()
		op = str(operation or "").strip()
		label = f"{rid}.{op}" if op else rid
		if events is None:
			return []
		if not isinstance(events, list):
			return executor_error(
				f"ExternalRuntimeBridge: {source} returned non-list events: {label}",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_BAD_EVENTS",
			)
		out: list[dict[str, Any]] = []
		for idx, ev in enumerate(events):
			if not isinstance(ev, dict):
				return executor_error(
					f"ExternalRuntimeBridge: {source} event[{idx}] is not an object: {label}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_BAD_EVENT",
				)
			if not str(ev.get("type", "") or "").strip():
				return executor_error(
					f"ExternalRuntimeBridge: {source} event[{idx}] missing type: {label}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_EVENT_TYPE_MISSING",
				)
			out.append(dict(ev))
		return out

	def invoke(
		self,
		runtime_id: str,
		operation: str,
		payload: dict[str, Any] | None = None,
		context: dict[str, Any] | None = None,
	) -> list[dict[str, Any]]:
		rid = str(runtime_id or "").strip()
		op = str(operation or "").strip()
		if not rid:
			return executor_error(
				"ExternalRuntimeBridge: runtime_id missing",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_ID_MISSING",
			)
		if not op:
			return executor_error(
				"ExternalRuntimeBridge: operation missing",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_OPERATION_MISSING",
			)
		adapter = self.adapters.get(rid)
		if adapter is None:
			return executor_error(
				f"ExternalRuntimeBridge: adapter not found: {rid}",
				kind=ERROR_KIND_BUSINESS,
				code="EXTERNAL_RUNTIME_ADAPTER_MISSING",
			)
		invoke = getattr(adapter, "invoke", None)
		if not callable(invoke):
			return executor_error(
				f"ExternalRuntimeBridge: adapter has no invoke(): {rid}",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_INVOKE_MISSING",
			)
		try:
			events = invoke(op, dict(payload or {}), dict(context or {}))
		except Exception as exc:
			return executor_error(
				f"ExternalRuntimeBridge: adapter exception: {rid}.{op} ({exc})",
				kind=ERROR_KIND_ENGINE,
				code="EXTERNAL_RUNTIME_EXCEPTION",
			)
		return self._validate_events(events, runtime_id=rid, operation=op, source="adapter")

	def poll_events(
		self,
		runtime_id: str,
		cursor: Any = None,
		context: dict[str, Any] | None = None,
	) -> list[dict[str, Any]]:
		rid = str(runtime_id or "").strip()
		if not rid:
			return executor_error(
				"ExternalRuntimeBridge: runtime_id missing",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_ID_MISSING",
			)
		adapter = self.adapters.get(rid)
		if adapter is None:
			return executor_error(
				f"ExternalRuntimeBridge: adapter not found: {rid}",
				kind=ERROR_KIND_BUSINESS,
				code="EXTERNAL_RUNTIME_ADAPTER_MISSING",
			)
		poll = getattr(adapter, "poll_events", None)
		if not callable(poll):
			return []
		try:
			events = poll(cursor, dict(context or {}))
		except Exception as exc:
			return executor_error(
				f"ExternalRuntimeBridge: poll exception: {rid} ({exc})",
				kind=ERROR_KIND_ENGINE,
				code="EXTERNAL_RUNTIME_POLL_EXCEPTION",
			)
		return self._validate_events(events, runtime_id=rid, operation="poll_events", source="poll")

	def save_checkpoint(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_checkpoint_lifecycle("save_checkpoint", context or {})

	def restore_checkpoint(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_checkpoint_lifecycle("restore_checkpoint", context or {})

	def _notify_checkpoint_lifecycle(self, method_name: str, context: dict[str, Any]) -> list[dict[str, Any]]:
		out: list[dict[str, Any]] = []
		for rid in sorted(str(k) for k in self.adapters.keys()):
			adapter = self.adapters.get(rid)
			method = getattr(adapter, method_name, None)
			if not callable(method):
				continue
			call_context = dict(context or {})
			call_context["runtime_id"] = rid
			try:
				events = method(call_context)
			except Exception as exc:
				return executor_error(
					f"ExternalRuntimeBridge: {method_name} exception: {rid} ({exc})",
					kind=ERROR_KIND_ENGINE,
					code="EXTERNAL_RUNTIME_CHECKPOINT_EXCEPTION",
				)
			validated = self._validate_events(events, runtime_id=rid, operation=method_name, source=method_name)
			if any(str(ev.get("type", "") or "") == "ExecutorError" for ev in validated):
				return validated
			out.extend(validated)
		return out
