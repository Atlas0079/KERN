from __future__ import annotations

import unittest

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.data.builder import build_world_state
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.models.components import AgentControlComponent, TagComponent
from KERN.models.entity import Entity
from KERN.models.environment import EnvironmentScope
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.query import evaluate_predicate
from KERN.runtime import KernRuntime
from KERN.sim.trigger_system import TriggerSystem


def _world_data() -> dict:
	return {
		"world_state": {"current_tick": 0},
		"environment_scopes": [
			{
				"scope_id": "region",
				"scope_type": "region",
				"location_ids": ["camp", "cabin"],
				"priority": 0,
				"fields": {"weather": "rain", "light_level": 2},
				"conditions": ["foggy"],
				"condition_expire_at_tick": {"foggy": 10},
			},
			{
				"scope_id": "cabin_override",
				"scope_type": "location",
				"location_ids": ["cabin"],
				"priority": 10,
				"fields": {"light_level": 0},
			},
		],
		"locations": [
			{"location_id": "camp", "location_name": "Camp", "description": "", "entities": []},
			{"location_id": "cabin", "location_name": "Cabin", "description": "", "entities": []},
		],
		"paths": [],
	}


class EnvironmentScopeTests(unittest.TestCase):
	def test_builder_loads_environment_scopes_and_priority_overrides(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state

		self.assertEqual(ws.get_environment_field("camp", "weather"), "rain")
		self.assertEqual(ws.get_environment_field("camp", "light_level"), 2)
		self.assertEqual(ws.get_environment_field("cabin", "weather"), "rain")
		self.assertEqual(ws.get_environment_field("cabin", "light_level"), 0)

	def test_environment_field_match_condition_reads_location_environment(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state
		agent = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		agent.add_component("TagComponent", TagComponent(tags=["agent"]))
		ws.register_entity(agent)
		ws.get_location_by_id("camp").add_entity_id("agent")

		self.assertTrue(
			evaluate_predicate(
				ws,
				{"type": "environment_field_match", "location_ref": "self.location_id", "key": "weather", "value": "rain"},
				{"self_id": "agent"},
			)
		)

	def test_set_environment_field_effect_updates_scope(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state
		executor = WorldExecutor()

		events = executor.execute(
			ws,
			{"effect": "SetEnvironmentField", "scope_id": "region", "key": "weather", "value": "clear"},
			{},
		)

		self.assertEqual(ws.get_environment_field("camp", "weather"), "clear")
		self.assertEqual(events[0]["type"], "EnvironmentFieldSet")
		self.assertEqual(events[0]["payload"]["old_value"], "rain")
		self.assertEqual(events[0]["payload"]["value"], "clear")

	def test_environment_condition_effects_and_predicate(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state
		executor = WorldExecutor()

		added = executor.execute(
			ws,
			{"effect": "AddEnvironmentCondition", "scope_id": "region", "condition_id": "muddy_ground", "duration_ticks": 5},
			{},
		)

		self.assertTrue(evaluate_predicate(ws, {"type": "environment_has_condition", "scope_id": "region", "condition_id": "muddy_ground"}, {}))
		self.assertEqual(added[0]["payload"]["expire_at_tick"], 5)

		removed = executor.execute(
			ws,
			{"effect": "RemoveEnvironmentCondition", "scope_id": "region", "condition_id": "muddy_ground"},
			{},
		)

		self.assertFalse(evaluate_predicate(ws, {"type": "environment_has_condition", "scope_id": "region", "condition_id": "muddy_ground"}, {}))
		self.assertEqual(removed[0]["type"], "EnvironmentConditionRemoved")

	def test_world_tick_reaction_expires_environment_condition(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state
		ws.game_time.total_ticks = 10
		trigger = TriggerSystem()

		trigger.rules = [
			{
				"id": "world_tick_environment_condition",
				"on_event": "WorldTickAdvanced",
				"bundle": {"effects": [{"effect": "EnvironmentConditionTick"}]},
			}
		]
		requests = trigger.build_reaction_effects(
			ws,
			{"type": "WorldTickAdvanced", "total_ticks": 10, "time": "0001-01-01 00:10"},
			{},
		)
		executor = WorldExecutor()
		events = []
		for request in requests:
			events.extend(executor.execute_bundle(ws, request.get("bundle", {}), request.get("context", {})))

		self.assertFalse(evaluate_predicate(ws, {"type": "environment_has_condition", "scope_id": "region", "condition_id": "foggy"}, {}))
		self.assertIn("EnvironmentConditionExpired", {str(event.get("type", "")) for event in events})

	def test_runtime_step_dispatches_world_tick_reactions(self) -> None:
		result = build_world_state(_world_data(), {}, {})
		ws = result.world_state
		ws.game_time.total_ticks = 9
		runtime = KernRuntime(
			world_state=ws,
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			reaction_rules=[
				{
					"id": "world_tick_environment_condition",
					"on_event": "WorldTickAdvanced",
					"bundle": {"effects": [{"effect": "EnvironmentConditionTick"}]},
				}
			],
			checkpoint_enabled=False,
		)
		runtime.is_running = True

		events = runtime.step()

		event_types = {str((record.get("event", {}) or {}).get("type", "")) for record in events}
		self.assertFalse(evaluate_predicate(ws, {"type": "environment_has_condition", "scope_id": "region", "condition_id": "foggy"}, {}))
		self.assertIn("WorldTickAdvanced", event_types)
		self.assertIn("EnvironmentConditionExpired", event_types)

	def test_observer_uses_environment_light_level(self) -> None:
		ws = WorldState()
		ws.register_location(Location(location_id="dark_room", location_name="Dark Room", description="", light_level=2))
		ws.register_environment_scope(
			EnvironmentScope(
				scope_id="darkness",
				location_ids=["dark_room"],
				fields={"light_level": 0, "weather": "indoor"},
			)
		)
		agent = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		agent.add_component("TagComponent", TagComponent(tags=["agent"]))
		agent.add_component("AgentControlComponent", AgentControlComponent())
		ws.register_entity(agent)
		ws.get_location_by_id("dark_room").add_entity_id("agent")

		view = build_full_ws_view(ws, "agent", reason="test", mode_context={})
		perception = build_agent_perception(view, "agent")

		self.assertEqual(perception["location"]["light_level"], 0)
		self.assertEqual(perception["location"]["environment"]["weather"], "indoor")
		self.assertTrue(perception["perception_blocked_by_darkness"])


if __name__ == "__main__":
	unittest.main()
