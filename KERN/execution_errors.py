from __future__ import annotations

from typing import Any


BIND_ERROR_EVENT = "BindError"
EXECUTOR_ERROR_EVENT = "ExecutorError"


def executor_error(message: str) -> list[dict[str, Any]]:
	return [{"type": EXECUTOR_ERROR_EVENT, "message": str(message or "")}]


def is_execution_error_event(ev: Any) -> bool:
	return isinstance(ev, dict) and str(ev.get("type", "") or "") in {BIND_ERROR_EVENT, EXECUTOR_ERROR_EVENT}
