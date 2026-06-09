from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import InterruptResult


@dataclass
class NoActiveTaskRule:
	priority: int = 999

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		_ = ws
		_ = agent_id
		return InterruptResult(
			interrupt=True,
			reason="no_active_task",
			rule_type="NoActiveTask",
			priority=self.priority,
		)
