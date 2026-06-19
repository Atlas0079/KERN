from __future__ import annotations

import unittest

from KERN.models.components import CreatureComponent


class CreatureComponentTests(unittest.TestCase):
	def test_stress_defaults_to_zero_when_explicitly_enabled(self) -> None:
		comp = CreatureComponent(max_stress=100)

		comp.ensure_initialized()

		self.assertEqual(comp.current_stress, 0.0)
		self.assertEqual(comp.current_hp, comp.max_hp)
		self.assertEqual(comp.current_energy, comp.max_energy)
		self.assertEqual(comp.current_nutrition, comp.max_nutrition)

	def test_stress_remains_absent_when_not_configured(self) -> None:
		comp = CreatureComponent()

		comp.ensure_initialized()

		self.assertIsNone(comp.max_stress)
		self.assertIsNone(comp.current_stress)


if __name__ == "__main__":
	unittest.main()
