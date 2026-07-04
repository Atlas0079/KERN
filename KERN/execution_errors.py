from __future__ import annotations

from typing import Any


BIND_ERROR_EVENT = "BindError"
EXECUTOR_ERROR_EVENT = "ExecutorError"

ERROR_KIND_BUSINESS = "business"
ERROR_KIND_CONTRACT = "contract"
ERROR_KIND_ENGINE = "engine"


def executor_error(message: str, *, kind: str = ERROR_KIND_BUSINESS, code: str = "", effect: str = "") -> list[dict[str, Any]]:
	clean_kind = str(kind or ERROR_KIND_BUSINESS).strip().lower()
	if clean_kind not in {ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE}:
		clean_kind = ERROR_KIND_BUSINESS
	event: dict[str, Any] = {
		"type": EXECUTOR_ERROR_EVENT,
		"kind": clean_kind,
		"message": str(message or ""),
		"recoverable": clean_kind == ERROR_KIND_BUSINESS,
	}
	if code:
		event["code"] = str(code)
	if effect:
		event["effect"] = str(effect)
	return [event]


def is_execution_error_event(ev: Any) -> bool:
	return isinstance(ev, dict) and str(ev.get("type", "") or "") in {BIND_ERROR_EVENT, EXECUTOR_ERROR_EVENT}


def execution_error_kind(ev: Any) -> str:
	if not is_execution_error_event(ev):
		return ""
	if isinstance(ev, dict) and str(ev.get("type", "") or "") == BIND_ERROR_EVENT:
		return ERROR_KIND_CONTRACT
	kind = str((ev or {}).get("kind", "") or "").strip().lower()
	if kind in {ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE}:
		return kind
	return ERROR_KIND_BUSINESS
