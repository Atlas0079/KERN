from __future__ import annotations

import unittest

from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.sim.manager import WorldManager


def _world() -> WorldState:
	ws = WorldState()
	loc = Location(location_id="room", location_name="Room", description="")
	ws.register_location(loc)
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ws.register_entity(ent)
	loc.add_entity_id(ent.entity_id)
	return ws


class WorldManagerRuntimeTests(unittest.TestCase):
	def test_record_initial_state_uses_public_runtime_api(self) -> None:
		manager = WorldManager(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			checkpoint_enabled=False,
		)

		manager.record_initial_state()

		self.assertEqual(len(manager.snapshots), 1)
		self.assertEqual(manager.snapshots[0]["tick"], 0)
		self.assertEqual(manager.snapshots[0]["events"], [])

	def test_advance_ticks_steps_and_records_each_tick(self) -> None:
		manager = WorldManager(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			checkpoint_enabled=False,
		)

		result = manager.advance_ticks(2)

		self.assertEqual(result["ticks_requested"], 2)
		self.assertEqual(result["ticks_advanced"], 2)
		self.assertEqual(result["started_at_tick"], 0)
		self.assertEqual(result["ended_at_tick"], 2)
		self.assertFalse(result["stopped"])
		self.assertEqual(manager.world_state.game_time.total_ticks, 2)
		self.assertEqual([x["tick"] for x in manager.snapshots], [1, 2])
		self.assertGreaterEqual(result["event_count"], 2)


if __name__ == "__main__":
	unittest.main()
