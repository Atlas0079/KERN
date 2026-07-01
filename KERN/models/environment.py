from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnvironmentScope:
	scope_id: str
	scope_type: str = "region"
	location_ids: list[str] = field(default_factory=list)
	priority: int = 0
	variables: dict[str, Any] = field(default_factory=dict)
	statuses: list[str] = field(default_factory=list)
	expire_at_tick: dict[str, int] = field(default_factory=dict)

	def covers_location(self, location_id: str) -> bool:
		lid = str(location_id or "").strip()
		if not lid:
			return False
		return lid in {str(x) for x in list(self.location_ids or []) if str(x)}

	def has_status(self, status_id: str) -> bool:
		sid = str(status_id or "").strip()
		if not sid:
			return False
		return sid in {str(x) for x in list(self.statuses or []) if str(x)}
