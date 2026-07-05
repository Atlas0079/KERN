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
		if events is None:
			return []
		if not isinstance(events, list):
			return executor_error(
				f"ExternalRuntimeBridge: adapter returned non-list events: {rid}.{op}",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_BAD_EVENTS",
			)
		out: list[dict[str, Any]] = []
		for idx, ev in enumerate(events):
			if not isinstance(ev, dict):
				return executor_error(
					f"ExternalRuntimeBridge: event[{idx}] is not an object: {rid}.{op}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_BAD_EVENT",
				)
			if not str(ev.get("type", "") or "").strip():
				return executor_error(
					f"ExternalRuntimeBridge: event[{idx}] missing type: {rid}.{op}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_EVENT_TYPE_MISSING",
				)
			out.append(dict(ev))
		return out

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
		if events is None:
			return []
		if not isinstance(events, list):
			return executor_error(
				f"ExternalRuntimeBridge: poll returned non-list events: {rid}",
				kind=ERROR_KIND_CONTRACT,
				code="EXTERNAL_RUNTIME_BAD_EVENTS",
			)
		out: list[dict[str, Any]] = []
		for idx, ev in enumerate(events):
			if not isinstance(ev, dict):
				return executor_error(
					f"ExternalRuntimeBridge: poll event[{idx}] is not an object: {rid}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_BAD_EVENT",
				)
			if not str(ev.get("type", "") or "").strip():
				return executor_error(
					f"ExternalRuntimeBridge: poll event[{idx}] missing type: {rid}",
					kind=ERROR_KIND_CONTRACT,
					code="EXTERNAL_RUNTIME_EVENT_TYPE_MISSING",
				)
			out.append(dict(ev))
		return out
