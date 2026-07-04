from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnvironmentScope:
	scope_id: str
	scope_type: str = "region"
	location_ids: list[str] = field(default_factory=list)
	priority: int = 0
	fields: dict[str, Any] = field(default_factory=dict)
	conditions: list[str] = field(default_factory=list)
	condition_expire_at_tick: dict[str, int] = field(default_factory=dict)

	def covers_location(self, location_id: str) -> bool:
		lid = str(location_id or "").strip()
		if not lid:
			return False
		return lid in {str(x) for x in list(self.location_ids or []) if str(x)}

	def has_condition(self, condition_id: str) -> bool:
		cid = str(condition_id or "").strip()
		if not cid:
			return False
		return cid in {str(x) for x in list(self.conditions or []) if str(x)}
