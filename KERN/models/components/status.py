from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StatusComponent:
	statuses: list[str] = field(default_factory=list)
	expire_at_tick: dict[str, int] = field(default_factory=dict)

	def has_status(self, status_id: str) -> bool:
		return str(status_id) in self.statuses
