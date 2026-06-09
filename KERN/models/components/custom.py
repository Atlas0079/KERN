from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CustomComponent:
	"""
	Holds scenario-defined component data that has no dedicated Python model yet.
	"""

	data: dict[str, Any] = field(default_factory=dict)

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		# Custom components do not progress any state by default.
		return

