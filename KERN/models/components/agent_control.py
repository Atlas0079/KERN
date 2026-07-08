from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentControlComponent:
	"""
	Agent control switch ("Is this entity allowed to be driven by Agent/LLM").

	Design Goals:
	- Explicit Authorization: Only entities with this component attached will enter the decision loop.
	- Extensible: Different control modes/providers (LLM/Script/Policy) can be attached here in the future.
	"""

	# Whether control is enabled (can be used to temporarily "freeze" an agent)
	enabled: bool = True

	# Optional control provider identifier (e.g., player, logic, scripted).
	# If it does not resolve in runtime action_providers, callers should fall
	# back to the runtime default provider.
	provider_id: str = ""

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		return
