from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Path:
	"""
	Represents a connection between two locations (Graph Edge).
	"""

	path_id: str
	from_location_id: str
	to_location_id: str
	distance: float = 1.0
	
	# Optional: Travel requirements (e.g. "climb", "swim")
	travel_type: str = "walk" 
	
	# Optional: Connection status
	is_blocked: bool = False
