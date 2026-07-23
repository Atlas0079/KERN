from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .execution_errors import ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE, executor_error


class ExternalRuntimeLifecycleError(RuntimeError):
	"""A lifecycle callback failed after the runtime crossed an external boundary."""

	def __init__(self, *, phase: str, runtime_id: str, reason: str, transaction_id: str = "", receipts: list[dict[str, Any]] | None = None) -> None:
		self.phase = str(phase or "")
		self.runtime_id = str(runtime_id or "")
		self.reason = str(reason or "")
		self.transaction_id = str(transaction_id or "")
		self.receipts = [dict(item) for item in list(receipts or []) if isinstance(item, dict)]
		super().__init__(f"external runtime lifecycle failed: phase={self.phase} runtime_id={self.runtime_id} transaction_id={self.transaction_id} reason={self.reason}")


@runtime_checkable
class ExternalRuntimeAdapter(Protocol):
	"""
	Protocol implemented by an external application/runtime adapter.

	KERN owns the effect contract and execution boundary. External runtimes own
	their domain-specific operation semantics, such as messages, device calls,
	browser actions, or platform notifications.
	"""

	def invoke(self, operation: str, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		"""Run one external operation and return KERN event dictionaries."""
		...

	# Adapters that support compensation may additionally implement
	# invoke_with_receipt(...), returning ``(events, receipt)``.  The receipt is
	# opaque to KERN and is returned to the same adapter on bundle rollback.


@dataclass
class ExternalRuntimeBridge:
	"""
	Single runtime service for domain-specific external adapters.

	Concrete effect handlers should remain explicit. Those handlers use this
	bridge to route normalized payloads to the external runtime that owns the
	domain.
	"""

	adapters: dict[str, Any] = field(default_factory=dict)
	_bundle_receipts: dict[str, list[dict[str, Any]]] = field(default_factory=dict, init=False, repr=False)

	def begin_bundle(self, transaction_id: str) -> None:
		tid = str(transaction_id or "").strip()
		if not tid:
			raise ValueError("external bundle transaction_id missing")
		self._bundle_receipts[tid] = []

	def bundle_receipts(self, transaction_id: str) -> list[dict[str, Any]]:
		return [dict(item) for item in list(self._bundle_receipts.get(str(transaction_id or ""), []) or [])]

	def close_bundle(self, transaction_id: str) -> None:
		self._bundle_receipts.pop(str(transaction_id or ""), None)

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
			invoke_with_receipt = getattr(adapter, "invoke_with_receipt", None)
			receipt: dict[str, Any] | None = None
			if callable(invoke_with_receipt):
				result = invoke_with_receipt(op, dict(payload or {}), dict(context or {}))
				if not isinstance(result, tuple) or len(result) != 2:
					return executor_error("ExternalRuntimeBridge: invoke_with_receipt must return (events, receipt)", kind=ERROR_KIND_CONTRACT, code="EXTERNAL_RUNTIME_BAD_RECEIPT_RESULT")
				events, receipt_raw = result
				if receipt_raw is not None and not isinstance(receipt_raw, dict):
					return executor_error("ExternalRuntimeBridge: receipt must be an object", kind=ERROR_KIND_CONTRACT, code="EXTERNAL_RUNTIME_BAD_RECEIPT")
				receipt = dict(receipt_raw) if isinstance(receipt_raw, dict) else None
			else:
				events = invoke(op, dict(payload or {}), dict(context or {}))
		except Exception as exc:
			return executor_error(
				f"ExternalRuntimeBridge: adapter exception: {rid}.{op} ({exc})",
				kind=ERROR_KIND_ENGINE,
				code="EXTERNAL_RUNTIME_EXCEPTION",
			)
		validated = self._validate_events(events, runtime_id=rid, operation=op, source="adapter")
		transaction_id = str((context or {}).get("external_transaction_id", "") or "").strip()
		if transaction_id and receipt is not None and not any(str(event.get("type", "") or "") == "ExecutorError" for event in validated):
			self._bundle_receipts.setdefault(transaction_id, []).append({"runtime_id": rid, "receipt": receipt})
		return validated

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

	def restore_checkpoint(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_lifecycle("checkpoint_restore", context or {})

	def save_checkpoint(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_lifecycle("checkpoint_save", context or {})

	def commit_bundle(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_lifecycle("bundle_commit", context or {})

	def rollback_bundle(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return self._notify_lifecycle("bundle_rollback", context or {})

	def _notify_lifecycle(self, phase: str, context: dict[str, Any]) -> list[dict[str, Any]]:
		method_names = {
			"checkpoint_save": "save_checkpoint",
			"checkpoint_restore": "restore_checkpoint",
			"bundle_commit": "commit_bundle",
			"bundle_rollback": "rollback_bundle",
		}
		method_name = method_names.get(str(phase or ""))
		if not method_name:
			raise ValueError(f"unknown external runtime lifecycle phase: {phase}")
		transaction_id = str((context or {}).get("transaction_id", "") or "")
		receipts = [dict(item) for item in list((context or {}).get("receipts", []) or []) if isinstance(item, dict)]
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
				raise ExternalRuntimeLifecycleError(phase=phase, runtime_id=rid, reason=str(exc), transaction_id=transaction_id, receipts=receipts) from exc
			validated = self._validate_events(events, runtime_id=rid, operation=method_name, source=method_name)
			if any(str(ev.get("type", "") or "") == "ExecutorError" for ev in validated):
				reason = str((validated[0] if validated else {}).get("message", "adapter returned lifecycle error") or "adapter returned lifecycle error")
				raise ExternalRuntimeLifecycleError(phase=phase, runtime_id=rid, reason=reason, transaction_id=transaction_id, receipts=receipts)
			out.extend(validated)
		return out
