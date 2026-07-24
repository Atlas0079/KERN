from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.effect_record import build_effect_records
from KERN.execution_errors import KernFailure
from KERN.failure_report import FailureReportWriter
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.agent_workflow.runtime import _decision_to_outcome
from KERN.agent_workflow.runtime import _commands_to_operations
from KERN.agent_workflow.llm_action_provider import LLMActionProvider
from KERN.llm.openai_compat_client import LLMRequestError
from KERN.models.components import TagComponent
from KERN.models.components.memory import MemoryComponent
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState
from KERN.sim.trigger_system import TriggerSystem
from KERN.sim.world_settlement import WorldSettlement
from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view


class FailureAndEffectRecordTests(unittest.TestCase):
	class _FailingLLM:
		class _Client:
			base_url = "https://example.test"
			api_prefix = "/v1"

		client = _Client()
		planner_model = "planner"
		grounder_model = "grounder"
		request_extra = {"seed": 1}

		def planner_text(self, **_kwargs):
			raise LLMRequestError("planner unavailable")

		def grounder_text(self, **_kwargs):
			return "[]"

	def test_action_rejection_is_a_value_and_does_not_write_world_logs(self) -> None:
		ws = WorldState()
		ws.services["interaction_engine"] = InteractionEngine(recipe_db={})

		outcome = _decision_to_outcome(
			ws,
			"agent",
			"test",
			{
				"type": "apply_commands",
				"commands": [{"verb": "FlyToMoon", "target_id": "moon", "parameters": {}}],
			},
		)

		self.assertEqual(outcome["type"], "rejected")
		self.assertEqual(outcome["rejection"]["code"], "TARGET_MISSING")
		self.assertEqual(ws.event_log, [])
		self.assertEqual(ws.interaction_log, [])

	def test_llm_failure_keeps_raw_failure_evidence(self) -> None:
		provider = LLMActionProvider(llm=self._FailingLLM())
		view = {
			"full_ws_view": {
				"tick": 1,
				"entities": [{"id": "agent", "location_id": "room", "name": "Agent", "tags": []}],
				"locations": [{"id": "room", "name": "Room", "entities": ["agent"], "environment": {}}],
				"paths": [],
				"event_delta": [],
				"interaction_delta": [],
			}
		}
		with self.assertRaises(KernFailure) as caught:
			provider.decide(view, {}, "agent", "tick", {})
		self.assertEqual(caught.exception.code, "LLM_PLANNER_REQUEST_FAILED")
		self.assertEqual(caught.exception.origin, "llm")
		self.assertEqual(caught.exception.context["failure_evidence"]["attempts"][0]["planner"]["request"]["model"], "planner")

	def test_bound_dynamic_input_is_recorded_after_success(self) -> None:
		ws = WorldState()
		events = WorldExecutor().execute_bundle(
			ws,
			{"effects": [{"effect": "EmitEvent", "event_type": "Probe", "payload": {"value": "param:value"}}]},
			{"parameters": {"value": 7}},
		)

		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["type"], "Probe")
		self.assertEqual(events[0]["effect"], "EmitEvent")
		self.assertEqual(events[0]["input"]["payload"]["value"], 7)
		self.assertTrue(events[0]["_effect_record"])

	def test_failed_bundle_rolls_back_and_does_not_publish_records(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=TriggerSystem(), max_reaction_depth=4)

		with self.assertRaises(KernFailure) as caught:
			settlement.execute_bundle(
				{"effects": [{"effect": "AddTag", "target": "self", "tag": "temporary"}, {"effect": "UnknownEffect"}]},
				{"self_id": "agent"},
			)

		self.assertEqual(caught.exception.code, "UNKNOWN_EFFECT_TYPE")
		self.assertEqual(ws.get_entity_by_id("agent").get_component("TagComponent").tags, [])
		self.assertEqual(ws.event_log, [])

	def test_failure_report_is_single_and_keeps_raw_context(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			writer = FailureReportWriter(Path(temp_dir), "run-1")
			exc = KernFailure(
				"BROKEN_EFFECT",
				"handler failed",
				origin="executor",
				phase="effect_execution",
				context={"request_secret": "developer-visible-value"},
			)
			first = writer.write_failure(exc, tick=3, context={"raw_prompt": "keep this"})
			second = writer.write_failure(KernFailure("SECOND", "ignored"))

			self.assertEqual(first, second)
			payload = json.loads((Path(temp_dir) / "failure.json").read_text(encoding="utf-8"))
			self.assertEqual(payload["failure"]["code"], "BROKEN_EFFECT")
			self.assertEqual(payload["failure"]["context"]["request_secret"], "developer-visible-value")
			self.assertEqual(payload["runtime_context"]["raw_prompt"], "keep this")

	def test_reaction_consumes_only_successful_effect_record(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		trigger = TriggerSystem(
			rules=[
				{
					"id": "mark_probe",
					"on_event": "Probe",
					"condition": {"type": "event_field_eq", "field": "value", "value": 7},
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reacted"}]},
				}
			]
		)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=trigger, max_reaction_depth=4)

		settlement.execute_bundle(
			{"effects": [{"effect": "EmitEvent", "event_type": "Probe", "payload": {"value": 7}}]},
			{"self_id": "agent"},
		)

		self.assertEqual(ws.get_entity_by_id("agent").get_component("TagComponent").tags, ["reacted"])
		self.assertEqual(ws.interaction_log, [])

	def test_reaction_can_match_effect_identity_and_normalized_input(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		trigger = TriggerSystem(
			rules=[
				{
					"id": "mark_property_effect",
					"on_effect": "AddTag",
					"condition": {"type": "event_field_eq", "field": "tag", "value": "from_effect"},
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reacted"}]},
				}
			]
		)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=trigger, max_reaction_depth=4)

		settlement.execute_bundle(
			{"effects": [{"effect": "AddTag", "target": "self", "tag": "from_effect"}]},
			{"self_id": "agent"},
		)

		self.assertEqual(ws.get_entity_by_id("agent").get_component("TagComponent").tags, ["from_effect", "reacted"])

	def test_recipe_success_interaction_is_written_by_an_effect(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		engine = InteractionEngine(
			recipe_db={
				"mark": {
					"verb": "Mark",
					"condition": {},
					"narrative_success": "{actor}标记了{target}",
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "marked"}]},
				}
			}
		)
		ws.services["interaction_engine"] = engine
		operations, error = _commands_to_operations(ws, "agent", "test", [{"verb": "Mark", "target_id": "agent", "parameters": {}}])
		self.assertIsNone(error)
		self.assertEqual(operations[0]["bundle"]["effects"][0]["effect"], "RecordInteraction")

		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=TriggerSystem(), max_reaction_depth=4)
		settlement.execute_bundle(operations[0]["bundle"], operations[0]["context"])

		self.assertEqual(entity.get_component("TagComponent").tags, ["marked"])
		self.assertEqual(ws.interaction_log[0]["verb"], "Mark")
		self.assertEqual(ws.interaction_log[0]["narrative"], "Agent标记了Agent")
		self.assertTrue(any(record["event"].get("effect") == "RecordInteraction" for record in ws.event_log))

	def test_recipe_without_narrative_does_not_create_interaction(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		ws.services["interaction_engine"] = InteractionEngine(
			recipe_db={
				"mark": {
					"verb": "Mark",
					"condition": {},
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "marked"}]},
				}
			}
		)
		operations, error = _commands_to_operations(
			ws,
			"agent",
			"test",
			[{"verb": "Mark", "target_id": "agent", "parameters": {}}],
		)
		self.assertIsNone(error)
		self.assertFalse(any(item.get("effect") == "RecordInteraction" for item in operations[0]["bundle"]["effects"]))

	def test_reaction_narrative_creates_one_interaction_and_agent_view_hides_events(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		trigger = TriggerSystem(
			rules=[
				{
					"id": "mark_probe",
					"on_event": "Probe",
					"narrative_success": "{actor}响应了探针",
					"reaction_verb": "Respond",
					"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reacted"}]},
				}
			]
		)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=trigger, max_reaction_depth=4)
		settlement.execute_bundle(
			{"effects": [{"effect": "EmitEvent", "event_type": "Probe", "payload": {"value": 1}}]},
			{"self_id": "agent"},
		)

		self.assertEqual(len(ws.interaction_log), 1)
		self.assertEqual(ws.interaction_log[0]["interaction_type"], "reaction")
		self.assertEqual(ws.interaction_log[0]["narrative"], "Agent响应了探针")
		view = build_full_ws_view(ws, "agent", "test", {})
		self.assertNotIn("event_delta", view)
		self.assertEqual(len(view["interaction_delta"]), 1)

	def test_agent_view_does_not_expose_historical_event_memory(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component(
			"MemoryComponent",
			MemoryComponent(
				short_term_queue=[
					{"type": "event", "content": "machine event", "source": {"kind": "event_log", "seq": 1}},
					{"type": "interaction", "content": "visible interaction", "source": {"kind": "interaction_log", "seq": 2}},
				]
			),
		)
		ws.register_entity(entity)

		view = build_full_ws_view(ws, "agent", "test", {})
		memory = view["entities"][0]["memory"]
		self.assertEqual([item["content"] for item in memory["short_term_queue"]], ["visible interaction"])

	def test_interaction_details_are_transactional(self) -> None:
		ws = WorldState()
		entity = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		entity.add_component("TagComponent", TagComponent())
		ws.register_entity(entity)
		settlement = WorldSettlement(ws=ws, executor=WorldExecutor(), trigger_system=TriggerSystem(), max_reaction_depth=4)
		settlement.execute_bundle(
			{
				"effects": [
					{"effect": "RecordInteraction", "actor_id": "agent", "verb": "Inspect", "target_id": "agent", "status": "success"},
					{"effect": "UpdateInteractionDetails", "actor_id": "agent", "details_text": "raw details"},
				],
			},
			{"self_id": "agent"},
		)
		self.assertEqual(ws.interaction_log[-1]["details_text"], "raw details")

		with self.assertRaises(KernFailure):
			settlement.execute_bundle(
				{
					"effects": [
						{"effect": "UpdateInteractionDetails", "actor_id": "agent", "details_text": "will rollback"},
						{"effect": "UnknownEffect"},
					],
				},
				{"self_id": "agent"},
			)
		self.assertEqual(ws.interaction_log[-1]["details_text"], "raw details")


if __name__ == "__main__":
	 unittest.main()
