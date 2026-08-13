from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, ClassVar

from KERN.executor.executor import WorldExecutor
from KERN.models.components import CreatureComponent
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState


@dataclass
class HeatComponent:
	__property_clamps__: ClassVar[dict[str, dict[str, Any]]] = {
		"temperature": {"min": -10, "max": "max_temperature"},
	}

	temperature: float = 0.0
	max_temperature: float = 25.0


class ModifyPropertyClampTests(unittest.TestCase):
	def setUp(self) -> None:
		self.ws = WorldState()
		self.executor = WorldExecutor()
		self.entity = Entity(entity_id="agent_01", template_id="Agent")
		self.entity.add_component(
			"CreatureComponent",
			CreatureComponent(
				max_hp=100,
				max_energy=80,
				max_nutrition=60,
				max_stress=40,
				current_hp=50,
				current_energy=20,
				current_nutrition=10,
				current_stress=5,
			),
		)
		self.entity.add_component("HeatComponent", HeatComponent())
		self.ws.register_entity(self.entity)
		self.context = {"self_id": "agent_01", "target_id": "agent_01"}

	def test_creature_current_value_is_clamped_to_max(self) -> None:
		events = self.executor.execute(
			self.ws,
			{
				"effect": "ModifyProperty",
				"target": "self",
				"component": "CreatureComponent",
				"property": "current_nutrition",
				"change": 999,
			},
			self.context,
		)

		comp = self.entity.get_component("CreatureComponent")
		self.assertEqual(comp.current_nutrition, 60.0)
		self.assertEqual(events[0]["payload"]["new_value"], 60.0)

	def test_creature_current_value_is_clamped_to_zero(self) -> None:
		events = self.executor.execute(
			self.ws,
			{
				"effect": "ModifyProperty",
				"target": "self",
				"component": "CreatureComponent",
				"property": "current_energy",
				"change": -999,
			},
			self.context,
		)

		comp = self.entity.get_component("CreatureComponent")
		self.assertEqual(comp.current_energy, 0.0)
		self.assertEqual(events[0]["payload"]["new_value"], 0.0)

	def test_component_clamp_declaration_is_reusable(self) -> None:
		events = self.executor.execute(
			self.ws,
			{
				"effect": "ModifyProperty",
				"target": "self",
				"component": "HeatComponent",
				"property": "temperature",
				"value": 50,
			},
			self.context,
		)

		comp = self.entity.get_component("HeatComponent")
		self.assertEqual(comp.temperature, 25.0)
		self.assertEqual(events[0]["payload"]["new_value"], 25.0)

	def test_unlisted_property_is_not_clamped(self) -> None:
		events = self.executor.execute(
			self.ws,
			{
				"effect": "ModifyProperty",
				"target": "self",
				"component": "CreatureComponent",
				"property": "max_energy",
				"change": -200,
			},
			self.context,
		)

		comp = self.entity.get_component("CreatureComponent")
		self.assertEqual(comp.max_energy, -120.0)
		self.assertEqual(events[0]["payload"]["new_value"], -120.0)


if __name__ == "__main__":
	unittest.main()
