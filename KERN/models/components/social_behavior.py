from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SocialBehaviorComponent:
	"""
	Frequency model for social-platform activity opportunities.

	This component decides when an agent may act on the social platform. It does
	not decide which social action the agent should take.
	"""

	base_activity_rate: float = 0.2
	active_hours: list[int] = field(default_factory=list)
	# Legacy scheduling fields kept for checkpoint/data compatibility.
	# Social-platform action cooldown is represented by StatusComponent.
	cooldown_ticks: int = 0
	last_social_opportunity_tick: int = -10**9
	event_reaction_sensitivity: float = 0.5
	expression_opportunity_rate: float = 0.2
	routine_browse_rate: float = 0.8
	# Reserved for a future activity-budget model; not used by the current gate.
	fatigue: float = 0.0

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		return None
