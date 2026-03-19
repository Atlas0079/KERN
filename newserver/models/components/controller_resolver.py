from __future__ import annotations

from typing import Any

from .agent_control import AgentControlComponent
from .logic_control import LogicControlComponent
from .player_control import PlayerControlComponent


def resolve_enabled_controller_component(entity: Any):
	"""
	Resolve "enabled controller component" from entity.

	Returns:
	- (component_name, component_instance) or (None, None)

	Explanation:
	- Only new control component names are accepted.
	"""

	if entity is None or not hasattr(entity, "get_component"):
		return (None, None)

	# Priority: Player > Agent > Pure Logic
	candidates = [
		("PlayerControlComponent", PlayerControlComponent),
		("AgentControlComponent", AgentControlComponent),
		("LogicControlComponent", LogicControlComponent),
	]

	for name, cls in candidates:
		comp = entity.get_component(name)
		if isinstance(comp, cls) and bool(getattr(comp, "enabled", True)):
			return (name, comp)

	return (None, None)

