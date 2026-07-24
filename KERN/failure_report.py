from __future__ import annotations

import json
import traceback
from pathlib import Path
from threading import Lock
from typing import Any

from .execution_errors import KernFailure
from uuid import uuid4


def _jsonable(value: Any, seen: set[int] | None = None) -> Any:
	"""Convert arbitrary runtime evidence without dropping developer detail."""
	active = seen if seen is not None else set()
	if value is None or isinstance(value, (str, int, float, bool)):
		return value
	if isinstance(value, dict):
		identity = id(value)
		if identity in active:
			return "<cycle>"
		active.add(identity)
		try:
			return {str(key): _jsonable(item, active) for key, item in value.items()}
		finally:
			active.discard(identity)
	if isinstance(value, (list, tuple, set, frozenset)):
		identity = id(value)
		if identity in active:
			return "<cycle>"
		active.add(identity)
		try:
			return [_jsonable(item, active) for item in value]
		finally:
			active.discard(identity)
	return repr(value)


class FailureReportWriter:
	"""Write exactly one complete fatal-failure report per runtime."""

	def __init__(self, output_dir: str | Path, run_id: str) -> None:
		self.output_dir = Path(output_dir)
		self.run_id = str(run_id or "")
		self._lock = Lock()
		self.written_path: Path | None = None
		self.last_write_error = ""

	@property
	def report_path(self) -> Path:
		return self.output_dir / "failure.json"

	def write_failure(
		self,
		exc: BaseException,
		*,
		tick: int = 0,
		context: dict[str, Any] | None = None,
	) -> Path | None:
		with self._lock:
			if self.written_path is not None:
				return self.written_path
			try:
				self.output_dir.mkdir(parents=True, exist_ok=True)
				payload = self._build_payload(exc, tick=tick, context=context)
				tmp_path = self.report_path.with_suffix(".tmp")
				with tmp_path.open("w", encoding="utf-8") as stream:
					json.dump(payload, stream, ensure_ascii=False, indent=2, default=repr)
				tmp_path.replace(self.report_path)
				self.written_path = self.report_path
				self.last_write_error = ""
				return self.report_path
			except Exception as report_error:
				self.last_write_error = f"{type(report_error).__name__}: {report_error}"
				return None

	def _build_payload(self, exc: BaseException, *, tick: int, context: dict[str, Any] | None) -> dict[str, Any]:
		if isinstance(exc, KernFailure):
			failure = exc.to_dict()
			failure["traceback"] = exc.traceback_text()
		else:
			failure = {
				"code": "UNEXPECTED_EXCEPTION",
				"message": str(exc),
				"origin": "kernel",
				"phase": "runtime",
				"context": {},
				"exception_type": type(exc).__name__,
				"traceback": "".join(traceback.format_exception(exc)).strip(),
			}
		notes = list(getattr(exc, "__notes__", []) or [])
		if notes:
			failure["notes"] = [str(note) for note in notes]
		cause_chain: list[dict[str, Any]] = []
		seen: set[int] = set()
		cause = exc.__cause__ or exc.__context__
		while cause is not None and id(cause) not in seen:
			seen.add(id(cause))
			cause_chain.append(
				{
					"type": type(cause).__name__,
					"message": str(cause),
					"traceback": "".join(traceback.format_exception(cause)).strip(),
				}
			)
			cause = cause.__cause__ or cause.__context__
		if cause_chain:
			failure["cause_chain"] = cause_chain
		return {
			"schema_version": "kern_failure.v1",
			"run_id": self.run_id,
			"tick": int(tick or 0),
			"failure": _jsonable(failure),
			"runtime_context": _jsonable(dict(context or {})),
		}


class FailureEvidence:
	"""Keep the current decision evidence in memory until a fatal failure occurs."""

	enabled = True

	def __init__(self) -> None:
		self._contexts: dict[str, dict[str, Any]] = {}

	def retain_context(self, context: dict[str, Any] | None) -> str:
		context_id = uuid4().hex
		self._contexts[context_id] = dict(context or {})
		return context_id

	def get_context(self, context_id: str) -> dict[str, Any]:
		return dict(self._contexts.get(str(context_id or ""), {}) or {})

	def discard_context(self, context_id: str) -> None:
		self._contexts.pop(str(context_id or ""), None)

	def record_failure(
		self,
		context: dict[str, Any] | None,
		*,
		kind: str = "",
		stage: str = "",
		summary: str = "",
		details: dict[str, Any] | None = None,
		**_: Any,
	) -> None:
		if not isinstance(context, dict):
			return
		context.setdefault("failures", []).append(
			{
				"kind": str(kind or ""),
				"stage": str(stage or ""),
				"summary": str(summary or ""),
				"details": dict(details or {}),
			}
		)
