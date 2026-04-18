from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlayerControlComponent:
	"""
	Player Controller (Placeholder implementation).

	Intent:
	- Make "who controls this entity" a pluggable component, not hardcoded in Manager.
	- In the future, you can write commands from frontend (Godot/Input devices) to a queue, then this component converts queue to action.
	"""

	enabled: bool = True
	provider_id: str = "player"

