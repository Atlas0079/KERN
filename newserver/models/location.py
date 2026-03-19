from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Location:
	location_id: str
	location_name: str = "Unnamed Location"
	description: str = ""

	# Only store entity IDs (Consistent with Godot pure ID mode)
	entities_in_location: list[str] = field(default_factory=list)

	def add_entity_id(self, entity_id: str) -> bool:
		if entity_id not in self.entities_in_location:
			self.entities_in_location.append(entity_id)
			return True
		return False

	def remove_entity_id(self, entity_id: str) -> bool:
		if entity_id in self.entities_in_location:
			self.entities_in_location.remove(entity_id)
			return True
		return False
