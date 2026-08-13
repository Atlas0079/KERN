from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from KERN.package_definitions import package_component


@package_component("social_propagation:ScreenComponent")
@dataclass
class ScreenComponent:
	"""Short-lived operable view displayed by a social-platform terminal.

	The component contains only the page currently available to an Agent. The
	external social runtime remains the authority for accounts, posts, feeds,
	exposures, and interactions.
	"""

	runtime_id: str
	account_id: str
	app: str = "social_platform"
	view: str = "blank"
	title: str = ""
	feed_items: list[dict[str, Any]] = field(default_factory=list)
	current_post: dict[str, Any] | None = None
	selected_post_id: str = ""
	feed_session_id: int = 0
	cursor: int = 0
	updated_tick: int = -1
	status_text: str = ""
	last_event_type: str = ""
	last_error: str = ""
