from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorldStateEntityComponent:
	"""
	Marks an entity as a world/system state carrier rather than an ordinary
	in-world object for agent passive perception.
	"""

	debug_visible: bool = True
	visible_to_agents: bool = False
	note: str = ""
