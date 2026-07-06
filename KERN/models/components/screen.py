from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScreenComponent:
	"""
	Current visible state for a phone/computer screen.

	This is a KERN-side operational view, not the external platform database.
	"""

	runtime_id: str = "weibo"
	account_id: str = ""
	app: str = ""
	view: str = "blank"
	title: str = ""
	feed_items: list[dict[str, Any]] = field(default_factory=list)
	current_post: dict[str, Any] | None = None
	selected_post_id: str = ""
	cursor: int = 0
	updated_tick: int = 0
	status_text: str = ""
	last_event_type: str = ""
	last_error: str = ""

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		return
