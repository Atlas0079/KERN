from __future__ import annotations

import unittest

from KERN.models.components import CreatureComponent


class CreatureComponentTests(unittest.TestCase):
	def test_stress_defaults_to_zero_when_initialized(self) -> None:
		comp = CreatureComponent(max_stress=100)

		comp.ensure_initialized()

		self.assertEqual(comp.current_stress, 0.0)
		self.assertEqual(comp.current_hp, comp.max_hp)
		self.assertEqual(comp.current_energy, comp.max_energy)
		self.assertEqual(comp.current_nutrition, comp.max_nutrition)


if __name__ == "__main__":
	unittest.main()
