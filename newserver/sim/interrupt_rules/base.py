from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass
class InterruptResult:
	interrupt: bool
	reason: str = ""
	rule_type: str = ""
	priority: int = 999999
	data: dict[str, Any] = field(default_factory=dict)


class InterruptRule(Protocol):
	priority: int

	def should_interrupt(self, ws: Any, agent_id: str) -> InterruptResult:
		...
