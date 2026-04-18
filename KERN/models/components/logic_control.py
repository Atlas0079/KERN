from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LogicControlComponent:
	"""
	Pure Logic Controller (Placeholder implementation).

	Intent:
	- Control entity via rules/scripts/FSM, bypassing LLM.
	- E.g.: Patrolling NPC, automatic doors, environment systems, etc.
	"""

	enabled: bool = True
	provider_id: str = "logic"

