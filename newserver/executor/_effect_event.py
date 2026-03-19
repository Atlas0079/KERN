from __future__ import annotations

from typing import Any


def execute_emit_event(_executor: Any, _ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	event_type = str(data.get("event_type", "") or "").strip()
	if not event_type:
		return [{"type": "ExecutorError", "message": "EmitEvent: event_type missing"}]
	payload = data.get("payload", {}) or {}
	if not isinstance(payload, dict):
		return [{"type": "ExecutorError", "message": "EmitEvent: payload must be object"}]
	event: dict[str, Any] = {"type": event_type}
	for k, v in payload.items():
		key = str(k)
		if key == "type":
			continue
		event[key] = v
	return [event]
