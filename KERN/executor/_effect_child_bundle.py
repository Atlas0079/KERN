from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..execution_errors import is_execution_error_event


@dataclass
class ChildBundleResult:
	events: list[dict[str, Any]] = field(default_factory=list)
	failed: bool = False
	error_event: dict[str, Any] | None = None
	error_message: str = ""


def run_child_bundle(ws: Any, bundle: Any, context: dict[str, Any], owner: str) -> ChildBundleResult:
	"""
	Execute a nested bundle through the manager service.

	The returned events are for container-effect decision making only. The active
	world-settlement session defers their publication until the containing bundle
	commits, so they must not be returned by the container effect as its own
	events.
	"""
	execute = (getattr(ws, "services", {}) or {}).get("execute")
	if not callable(execute):
		message = f"{owner}: execute service missing"
		return ChildBundleResult(
			events=[],
			failed=True,
			error_event={"type": "ExecutorError", "message": message},
			error_message=message,
		)
	events = [dict(ev) for ev in list(execute(bundle, context) or []) if isinstance(ev, dict)]
	for ev in events:
		if is_execution_error_event(ev):
			message = str(ev.get("message", "") or ev.get("type", "") or "")
			return ChildBundleResult(events=events, failed=True, error_event=dict(ev), error_message=message)
	return ChildBundleResult(events=events, failed=False, error_event=None, error_message="")


def child_bundle_error_message(result: ChildBundleResult, owner: str, detail: str = "") -> str:
	if "execute service missing" in str(result.error_message or ""):
		return str(result.error_message)
	suffix = f" ({detail})" if str(detail or "").strip() else ""
	return f"{owner}: child bundle failed{suffix}"
