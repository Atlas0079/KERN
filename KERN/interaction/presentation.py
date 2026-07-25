from __future__ import annotations

from typing import Any


def interaction_is_failure(status: Any) -> bool:
	return str(status or "") in {"failed", "rejected"}


def interaction_content(record: dict[str, Any]) -> str:
	item = dict(record or {}) if isinstance(record, dict) else {}
	actor = str(item.get("actor_name", "") or item.get("actor_id", "") or "")
	target = str(item.get("target_name", "") or item.get("target_id", "") or "")
	verb = str(item.get("verb", "") or "")
	status = str(item.get("status", "") or "")
	reason = str(item.get("reason", "") or "").strip()
	speech = str(item.get("speech", "") or "").strip()
	if bool(item.get("is_dialogue", False)) or verb == "Say":
		return f"{actor}：{speech}" if speech else f"{actor}：{verb} {status}"
	narrative = str(item.get("narrative", "") or "").strip()
	if narrative:
		return narrative
	content = f"{actor}对{target}执行{verb}" if target else f"{actor}执行{verb}"
	if interaction_is_failure(status):
		return f"{content}失败：{reason or 'unknown'}"
	return f"{actor}对{target}执行了{verb}" if target else f"{actor}执行了{verb}"
