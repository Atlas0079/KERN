from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CreatureComponent:
	"""
	Minimal implementation: Only keep fields you currently use/will be modified by effects.
	"""

	max_hp: float = 100.0
	max_energy: float = 100.0
	max_nutrition: float = 100.0

	current_hp: float | None = None
	current_energy: float | None = None
	current_nutrition: float | None = None

	def ensure_initialized(self) -> None:
		if self.current_hp is None:
			self.current_hp = float(self.max_hp)
		if self.current_energy is None:
			self.current_energy = float(self.max_energy)
		if self.current_nutrition is None:
			self.current_nutrition = float(self.max_nutrition)

