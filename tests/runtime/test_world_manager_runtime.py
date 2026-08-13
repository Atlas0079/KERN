from __future__ import annotations

import unittest

from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.executor.executor import WorldExecutor
from KERN.execution_errors import KernFailure
from KERN.interaction.engine import InteractionEngine
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.models.components import AgentControlComponent, AgentWakePolicyComponent, CreatureComponent
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
		project_root = Path(__file__).resolve().parents[2]
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
		self.assertEqual(runtime.snapshots[0]["schema_version"], "runtime_snapshot.v2")

	def test_snapshot_uses_catalog_component_state_only(self) -> None:
		ws = _world()
		ws.get_entity_by_id("agent_01").add_component("CreatureComponent", CreatureComponent(max_nutrition=80, current_nutrition=40, current_energy=60))
		runtime = KernRuntime(
			world_state=ws,
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			checkpoint_enabled=False,
		)

		runtime.record_initial_state()
		entity = runtime.snapshots[0]["entities"]["agent_01"]

		self.assertNotIn("components", entity)
		self.assertEqual(entity["component_state"]["CreatureComponent"]["current_nutrition"], 40.0)

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

		with self.assertRaises(KernFailure) as caught:
			runtime.advance_ticks(1)

		self.assertEqual(caught.exception.code, "UNKNOWN_EFFECT_TYPE")
		self.assertTrue(runtime.is_terminal)
		self.assertEqual(runtime.last_stop_info["reason"], "failure")
		self.assertTrue(runtime.failure_report_writer is not None)

	def test_workflow_exception_is_terminal(self) -> None:
		class _BrokenWorkflow:
			def begin_turn(self, _ws, _start):
				return self

			def next_step(self, _ws, _frame):
				raise OSError("provider unavailable")

		ws = _world()
		agent = ws.get_entity_by_id("agent_01")
		agent.add_component("AgentControlComponent", AgentControlComponent())
		agent.add_component(
			"AgentWakePolicyComponent",
			AgentWakePolicyComponent(ruleset=[{"type": "NoActiveTask", "priority": 1}]),
		)
		runtime = KernRuntime(
			world_state=ws,
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			workflow_registry=None,
			action_provider=_BrokenWorkflow(),
			checkpoint_enabled=False,
		)

		with self.assertRaises(KernFailure) as caught:
			runtime.advance_ticks(1)

		self.assertEqual(caught.exception.code, "WORKFLOW_PROVIDER_EXCEPTION")
		self.assertTrue(runtime.is_terminal)
		self.assertEqual(runtime.last_stop_info["reason"], "failure")


if __name__ == "__main__":
	unittest.main()
