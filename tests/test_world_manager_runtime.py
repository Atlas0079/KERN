from __future__ import annotations

import unittest

from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime
from pathlib import Path


def _world() -> WorldState:
	ws = WorldState()
	loc = Location(location_id="room", location_name="Room", description="")
	ws.register_location(loc)
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ws.register_entity(ent)
	loc.add_entity_id(ent.entity_id)
	return ws


class KernRuntimeTests(unittest.TestCase):
	def test_from_config_builds_sdk_runtime(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		runtime = KernRuntime.from_config(
			project_root,
			"runtime_config.camping.package.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)

		self.assertEqual(runtime.config_path, project_root / "runtime_config.camping.package.smoke.json")
		self.assertEqual(runtime.configured_max_ticks, 60)
		self.assertIsNotNone(runtime.data_bundle)
		self.assertIn("camp_main", runtime.world_state.locations)

	def test_record_initial_state_uses_public_runtime_api(self) -> None:
		runtime = KernRuntime(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			checkpoint_enabled=False,
		)

		runtime.record_initial_state()

		self.assertEqual(len(runtime.snapshots), 1)
		self.assertEqual(runtime.snapshots[0]["tick"], 0)
		self.assertEqual(runtime.snapshots[0]["events"], [])

	def test_advance_ticks_steps_and_records_each_tick(self) -> None:
		runtime = KernRuntime(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			checkpoint_enabled=False,
		)

		result = runtime.advance_ticks(2)

		self.assertEqual(result["ticks_requested"], 2)
		self.assertEqual(result["ticks_advanced"], 2)
		self.assertEqual(result["started_at_tick"], 0)
		self.assertEqual(result["ended_at_tick"], 2)
		self.assertFalse(result["stopped"])
		self.assertEqual(runtime.world_state.game_time.total_ticks, 2)
		self.assertEqual([x["tick"] for x in runtime.snapshots], [1, 2])
		self.assertGreaterEqual(result["event_count"], 2)

	def test_reaction_failure_stops_runtime_with_structured_reason(self) -> None:
		runtime = KernRuntime(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			reaction_rules=[
				{"id": "broken_tick_rule", "on_event": "AdvanceTick", "bundle": {"effects": [{"effect": "UnknownEffect"}]}},
			],
			checkpoint_enabled=False,
		)

		result = runtime.advance_ticks(1)

		self.assertTrue(result["stopped"])
		self.assertEqual(runtime.last_stop_info["reason"], "reaction_failed")
		self.assertEqual(runtime.last_stop_info["reaction_rule_id"], "broken_tick_rule")
		self.assertEqual(runtime.last_stop_info["reaction_depth"], 1)


if __name__ == "__main__":
	unittest.main()
