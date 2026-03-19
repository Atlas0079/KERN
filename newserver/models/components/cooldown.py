from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CooldownComponent:
	"""
	Manages cooldowns for various actions/skills.
	data structure: { "action_key": last_used_tick }
	"""

	cooldowns: dict[str, int] = field(default_factory=dict)

	def is_ready(self, key: str, current_tick: int, duration: int) -> bool:
		last = self.cooldowns.get(key, -99999)
		return (current_tick - last) >= duration

	def set_cooldown(self, key: str, current_tick: int) -> None:
		self.cooldowns[key] = int(current_tick)
