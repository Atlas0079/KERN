from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UnknownComponent:
	"""
	Used to hold raw dictionaries for unmigrated components (e.g., Equipment/Condition/Perception/LLMControl).
	"""

	data: dict[str, Any] = field(default_factory=dict)

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		# Unmigrated components do not progress any state by default
		return

