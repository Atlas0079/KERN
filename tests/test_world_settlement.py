from __future__ import annotations

import unittest

from KERN.executor.executor import WorldExecutor
from KERN.executor._effect_child_bundle import EVENT_CONTEXT_KEY
from KERN.models.entity import Entity
from KERN.models.components import TagComponent
from KERN.models.world_state import WorldState
from KERN.sim.trigger_system import TriggerSystem
from KERN.sim.world_settlement import WorldSettlement


class RecordingExecutor:
	def __init__(self) -> None:
		self.executed: list[str] = []

	def execute_bundle(self, _ws, bundle, _context):
		effect = bundle.effects[0]
		name = str(effect["effect"])
		self.executed.append(name)
		return [{"type": str(effect["event_type"])}]


class NestedRecordingExecutor(RecordingExecutor):
	def execute_bundle(self, ws, bundle, context):
		effect = bundle.effects[0]
		name = str(effect["effect"])
		self.executed.append(name)
		if name == "R1":
			ws.services["execute"]({"effects": [{"effect": "ChildBundle", "event_type": "Child"}]}, context)
			return [{"type": "FirstDone"}]
		return [{"type": str(effect["event_type"])}]


class WorldSettlementTests(unittest.TestCase):
	def test_query_child_events_keep_their_own_context_for_reactions(self) -> None:
		ws = WorldState()
		for entity_id in ("outer", "first", "second"):
			ws.register_entity(Entity(entity_id=entity_id, template_id="Thing", entity_name=entity_id))
		trigger = TriggerSystem(
			rules=[
				{
					"id": "mark_selected",
					"on_event": "TagAdded",
					"condition": {"type": "event_field_eq", "field": "tag", "value": "selected"},
					"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "reacted"}]},
				}
			]
		)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=trigger, max_reaction_depth=4)

		result = settlement.execute_bundle(
			{
				"effects": [
					{
						"effect": "ApplyToQuery",
						"query": {"from": "entities"},
						"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "selected"}]},
					}
				]
			},
			{"target_id": "outer"},
		)

		for entity_id in ("outer", "first", "second"):
			self.assertIn("reacted", ws.get_entity_by_id(entity_id).get_all_tags())
		applied_targets = {
			entry["target_id"]
			for entry in ws.interaction_log
			if entry.get("verb") == "ReactionApplied:mark_selected"
		}
		self.assertEqual(applied_targets, {"outer", "first", "second"})
		self.assertTrue(all(EVENT_CONTEXT_KEY not in event for event in result.events))
		self.assertTrue(all(EVENT_CONTEXT_KEY not in record["event"] for record in ws.event_log))

	def test_reaction_events_wait_until_current_event_reactions_finish(self) -> None:
		ws = WorldState()
		executor = RecordingExecutor()
		trigger = TriggerSystem(
			rules=[
				{"id": "first", "on_event": "Root", "bundle": {"effects": [{"effect": "R1", "event_type": "Child"}]}},
				{"id": "second", "on_event": "Root", "bundle": {"effects": [{"effect": "R2", "event_type": "SecondDone"}]}},
				{"id": "child", "on_event": "Child", "bundle": {"effects": [{"effect": "R3", "event_type": "ChildDone"}]}},
			]
		)
		settlement = WorldSettlement(ws=ws, executor=executor, trigger_system=trigger, max_reaction_depth=4)

		result = settlement.publish_event({"type": "Root"}, {})

		self.assertEqual(executor.executed, ["R1", "R2", "R3"])
		self.assertEqual([event["type"] for event in result.events], ["Root", "Child", "SecondDone", "ChildDone"])
		self.assertIsNone(result.fatal_error)

	def test_nested_bundle_events_wait_for_later_reactions_of_the_current_event(self) -> None:
		ws = WorldState()
		executor = NestedRecordingExecutor()
		trigger = TriggerSystem(
			rules=[
				{"id": "first", "on_event": "Root", "bundle": {"effects": [{"effect": "R1", "event_type": "unused"}]}},
				{"id": "second", "on_event": "Root", "bundle": {"effects": [{"effect": "R2", "event_type": "SecondDone"}]}},
				{"id": "child", "on_event": "Child", "bundle": {"effects": [{"effect": "R3", "event_type": "ChildDone"}]}},
			]
		)
		settlement = WorldSettlement(ws=ws, executor=executor, trigger_system=trigger, max_reaction_depth=4)
		ws.services["execute"] = settlement.execute_bundle

		settlement.publish_event({"type": "Root"}, {})

		self.assertEqual(executor.executed, ["R1", "ChildBundle", "R2", "R3"])

	def test_root_business_error_is_not_fatal(self) -> None:
		ws = WorldState()
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=TriggerSystem(), max_reaction_depth=4)

		result = settlement.execute_bundle(
			{"effects": [{"effect": "AddTag", "target": "self", "tag": "unreachable"}]},
			{},
		)

		self.assertEqual(result.events[0]["type"], "ExecutorError")
		self.assertEqual(result.events[0]["kind"], "business")
		self.assertIsNone(result.fatal_error)

	def test_failed_reaction_rolls_back_its_bundle_keeps_prior_commit_and_stops(self) -> None:
		ws = WorldState()
		actor = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		actor.add_component("TagComponent", TagComponent())
		ws.register_entity(actor)
		trigger = TriggerSystem(
			rules=[
				{
					"id": "committed",
					"on_event": "Root",
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "kept"}]},
				},
				{
					"id": "failed",
					"on_event": "Root",
					"bundle": {
						"effects": [
							{"effect": "AddTag", "target": "self", "tag": "rolled_back"},
							{"effect": "UnknownEffect"},
						]
					},
				},
				{
					"id": "must_not_run",
					"on_event": "Root",
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "too_late"}]},
				},
			]
		)
		fatals: list[dict] = []
		settlement = WorldSettlement(
			ws=ws,
			executor=WorldExecutor(),
			trigger_system=trigger,
			max_reaction_depth=4,
			on_fatal=fatals.append,
		)

		result = settlement.publish_event({"type": "Root"}, {"self_id": "agent"})

		tags = ws.get_entity_by_id("agent").get_component("TagComponent").tags
		self.assertEqual(tags, ["kept"])
		self.assertEqual([event["type"] for event in result.events], ["Root", "TagAdded", "ExecutorError", "ReactionFailed"])
		self.assertEqual(result.fatal_error["reaction_rule_id"], "failed")
		self.assertEqual(result.fatal_error["reaction_depth"], 1)
		self.assertEqual(fatals, [result.fatal_error])
		logged_rule_ids = [str(item.get("reaction_rule_id", "")) for item in ws.interaction_log]
		self.assertNotIn("must_not_run", logged_rule_ids)

	def test_failed_outer_bundle_does_not_publish_committed_child_events(self) -> None:
		ws = WorldState()
		actor = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		actor.add_component("TagComponent", TagComponent())
		ws.register_entity(actor)
		trigger = TriggerSystem(
			rules=[
				{
					"id": "must_not_react",
					"on_event": "TagAdded",
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reaction_ran"}]},
				}
			]
		)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=trigger, max_reaction_depth=4)

		result = settlement.execute_bundle(
			{
				"effects": [
					{
						"effect": "InvokeBundle",
						"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "child_committed"}]},
					},
					{"effect": "UnknownEffect"},
				]
			},
			{"self_id": "agent"},
		)

		tags = ws.get_entity_by_id("agent").get_component("TagComponent").tags
		self.assertEqual(tags, [])
		self.assertEqual([event["type"] for event in result.events], ["ExecutorError"])
		self.assertFalse(any(item.get("reaction_rule_id") == "must_not_react" for item in ws.interaction_log))

	def test_reaction_depth_counts_layers_from_one_and_overflow_is_fatal(self) -> None:
		ws = WorldState()
		executor = RecordingExecutor()
		trigger = TriggerSystem(
			rules=[
				{"id": "loop", "on_event": "Loop", "bundle": {"effects": [{"effect": "Again", "event_type": "Loop"}]}},
			]
		)
		settlement = WorldSettlement(ws=ws, executor=executor, trigger_system=trigger, max_reaction_depth=2)

		result = settlement.publish_event({"type": "Loop"}, {})

		self.assertEqual(executor.executed, ["Again", "Again"])
		self.assertEqual([event["type"] for event in result.events], ["Loop", "Loop", "Loop", "ReactionDepthExceeded"])
		self.assertEqual(result.fatal_error["reaction_depth"], 3)
		self.assertEqual(result.fatal_error["max_reaction_depth"], 2)
		triggered = [item for item in ws.interaction_log if item.get("reaction_phase") == "triggered"]
		self.assertEqual(len(triggered), 2)


if __name__ == "__main__":
	unittest.main()
