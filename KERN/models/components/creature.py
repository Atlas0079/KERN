from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Any


@dataclass
class CreatureComponent:
	"""
	Minimal implementation: Only keep fields you currently use/will be modified by effects.
	"""

	__property_clamps__: ClassVar[dict[str, dict[str, Any]]] = {
		"current_hp": {"min": 0.0, "max": "max_hp"},
		"current_energy": {"min": 0.0, "max": "max_energy"},
		"current_nutrition": {"min": 0.0, "max": "max_nutrition"},
		"current_stress": {"min": 0.0, "max": "max_stress"},
	}

	max_hp: float = 100.0
	max_energy: float = 100.0
	max_nutrition: float = 100.0
	max_stress: float | None = None

	current_hp: float | None = None
	current_energy: float | None = None
	current_nutrition: float | None = None
	current_stress: float | None = None

	def ensure_initialized(self) -> None:
		if self.current_hp is None:
			self.current_hp = float(self.max_hp)
		if self.current_energy is None:
			self.current_energy = float(self.max_energy)
		if self.current_nutrition is None:
			self.current_nutrition = float(self.max_nutrition)
		if self.current_stress is None and self.max_stress is not None:
			self.current_stress = 0.0
