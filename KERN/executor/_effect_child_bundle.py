from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..execution_errors import is_execution_error_event


# This key is an executor-to-settlement transport detail.  WorldSettlement
# consumes it before events are recorded or passed to reactions.
EVENT_CONTEXT_KEY = "__kern_event_context__"


@dataclass
class ChildBundleResult:
	events: list[dict[str, Any]] = field(default_factory=list)
	failed: bool = False
	error_event: dict[str, Any] | None = None
	error_message: str = ""


def run_child_bundle(executor: Any, ws: Any, bundle: Any, context: dict[str, Any]) -> ChildBundleResult:
	"""
	Execute a referenced child bundle inside the current executor transaction.

	The caller returns successful child events as part of its own effect result, so
	they are published only after the containing bundle commits.
	"""
	events = _attach_child_context(executor.execute_bundle(ws, bundle, context), context)
	for ev in events:
		if is_execution_error_event(ev):
			message = str(ev.get("message", "") or ev.get("type", "") or "")
			return ChildBundleResult(events=events, failed=True, error_event=dict(ev), error_message=message)
	return ChildBundleResult(events=events, failed=False, error_event=None, error_message="")


def _attach_child_context(events: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
	"""Preserve each child event's context until WorldSettlement publishes it.

	Nested child bundles may already have a more specific context.  Keep that
	inner context instead of replacing it with the enclosing bundle's context.
	"""
	wrapped: list[dict[str, Any]] = []
	for event in list(events or []):
		if not isinstance(event, dict):
			continue
		clean = dict(event)
		if not isinstance(clean.get(EVENT_CONTEXT_KEY), dict):
			clean[EVENT_CONTEXT_KEY] = dict(context or {})
		wrapped.append(clean)
	return wrapped


def child_bundle_error_message(result: ChildBundleResult, owner: str, detail: str = "") -> str:
	suffix = f" ({detail})" if str(detail or "").strip() else ""
	return f"{owner}: child bundle failed{suffix}"
