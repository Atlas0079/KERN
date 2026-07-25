from __future__ import annotations

import unittest
from pathlib import Path

from KERN.agent_workflow.dialogue import Pass, Speak
from KERN.agent_workflow.registry import WorkflowRegistry
from KERN.execution_errors import KernFailure
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.interaction.conversation import ConversationEngine, ConversationRequest
from KERN.interaction.action_resolver import resolve_action_intent
from KERN.models.components import AgentControlComponent, MemoryComponent, PerceptionComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.sim.trigger_system import TriggerSystem
from KERN.sim.world_settlement import WorldSettlement
from KERN.runtime import KernRuntime


class _DialoguePolicy:
	def __init__(self, text: str = "", *, fail: bool = False, invalid: bool = False) -> None:
		self.text = str(text)
		self.fail = bool(fail)
		self.invalid = bool(invalid)
		self.frames = []

	def decide_utterance(self, frame):
		self.frames.append(frame)
		if self.fail:
			raise KernFailure("TEST_DIALOGUE_FAILURE", "dialogue failed", origin="test", phase="dialogue")
		if self.invalid:
			return "invalid"
		return Speak(self.text) if self.text else Pass()


def _agent(entity_id: str, provider_id: str) -> Entity:
	entity = Entity(entity_id=entity_id, template_id="Agent", entity_name=entity_id)
	entity.add_component("AgentControlComponent", AgentControlComponent(provider_id=provider_id))
	entity.add_component("PerceptionComponent", PerceptionComponent())
	entity.add_component("MemoryComponent", MemoryComponent())
	return entity


def _conversation_world(*, failing_b: bool = False):
	ws = WorldState()
	room = Location(location_id="room", location_name="Room", description="")
	remote = Location(location_id="remote", location_name="Remote", description="")
	ws.register_location(room)
	ws.register_location(remote)

	policies = {
		"a": _DialoguePolicy("A reply"),
		"b": _DialoguePolicy("B reply", fail=failing_b),
	}
	registry = WorkflowRegistry()
	for provider_id, policy in policies.items():
		registry.register(provider_id, policy)
	registry.freeze()

	# Registration order deliberately differs from the required speaker order.
	for entity_id, provider_id in (("speaker_b", "b"), ("initiator", ""), ("speaker_a", "a")):
		entity = _agent(entity_id, provider_id)
		ws.register_entity(entity)
		room.add_entity_id(entity_id)
	remote_observer = _agent("remote_observer", "")
	ws.register_entity(remote_observer)
	remote.add_entity_id(remote_observer.entity_id)

	engine = InteractionEngine(recipe_db={})
	ws.services = {
		"interaction_engine": engine,
		"workflow_registry": registry,
	}
	executor = WorldExecutor()
	settlement = WorldSettlement(ws=ws, executor=executor, trigger_system=TriggerSystem(rules=[]), max_reaction_depth=4)
	ws.services["execute"] = settlement.execute_bundle
	return ws, settlement, policies


class ConversationTests(unittest.TestCase):
	def test_negative_utterance_limit_is_rejected_by_the_binder(self) -> None:
		ws, settlement, _policies = _conversation_world()

		with self.assertRaisesRegex(KernFailure, "max_utterances_per_tick"):
			settlement.execute_bundle(
				{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": -1, "opening_text": "Opening"}]},
				{"self_id": "initiator", "actor_id": "initiator"},
			)

		self.assertEqual(ws.interaction_log, [])

	def test_ineligible_initiator_does_not_create_an_inconsistent_transcript(self) -> None:
		ws, _settlement, _policies = _conversation_world()
		observer = Entity(entity_id="observer", template_id="Observer", entity_name="observer")
		ws.register_entity(observer)
		ws.get_location_by_id("room").add_entity_id("observer")

		result = ConversationEngine().conduct(ws, ConversationRequest("conv", "observer", "room", "Opening", 4))

		self.assertEqual(result.skipped_reason, "initiator_ineligible")
		self.assertEqual(result.utterances, ())
		self.assertNotIn("observer", result.participants)

	def test_conversation_records_stable_ordered_utterances_as_interactions(self) -> None:
		ws, settlement, policies = _conversation_world()

		settlement.execute_bundle(
			{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": 4, "opening_text": "Opening"}]},
			{"self_id": "initiator", "actor_id": "initiator", "action_id": "action_1"},
		)

		self.assertEqual([item["actor_id"] for item in ws.interaction_log], ["initiator", "speaker_a", "speaker_b"])
		self.assertEqual([item["speech"] for item in ws.interaction_log], ["Opening", "A reply", "B reply"])
		self.assertEqual([item["utterance_index"] for item in ws.interaction_log], [0, 1, 2])
		conversation_ids = {item["conversation_id"] for item in ws.interaction_log}
		self.assertEqual(len(conversation_ids), 1)
		self.assertTrue(all(item["verb"] == "Say" and item["is_dialogue"] for item in ws.interaction_log))
		self.assertEqual([item["speaker_id"] for item in policies["b"].frames[0].transcript], ["initiator", "speaker_a"])

		for entity_id in ("initiator", "speaker_a", "speaker_b"):
			inbox = ws.get_entity_by_id(entity_id).get_component("PerceptionComponent").interaction_inbox
			self.assertEqual(len(inbox), 3)
		remote_inbox = ws.get_entity_by_id("remote_observer").get_component("PerceptionComponent").interaction_inbox
		self.assertEqual(remote_inbox, [])

		event_types = [record["event"]["type"] for record in ws.event_log]
		self.assertEqual(event_types.count("InteractionRecorded"), 3)
		self.assertEqual(event_types.count("ConversationCompleted"), 1)
		self.assertEqual(event_types.count("StartConversation"), 1)
		self.assertNotIn("ConversationStarted", event_types)
		self.assertNotIn("ConversationSpoken", event_types)
		self.assertNotIn("ConversationEnded", event_types)

	def test_pass_does_not_record_an_utterance_or_consume_budget(self) -> None:
		ws, settlement, policies = _conversation_world()
		policies["a"].text = ""

		settlement.execute_bundle(
			{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": 2, "opening_text": "Opening"}]},
			{"self_id": "initiator", "actor_id": "initiator"},
		)

		self.assertEqual([item["actor_id"] for item in ws.interaction_log], ["initiator", "speaker_b"])
		self.assertEqual(ws.runtime_state.dialogue_budget_used_per_location["room"], 2)

	def test_provider_failure_leaves_no_partial_conversation_state(self) -> None:
		ws, settlement, _policies = _conversation_world(failing_b=True)

		with self.assertRaisesRegex(KernFailure, "dialogue failed"):
			settlement.execute_bundle(
				{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": 4, "opening_text": "Opening"}]},
				{"self_id": "initiator", "actor_id": "initiator"},
			)

		self.assertEqual(ws.interaction_log, [])
		self.assertEqual(ws.runtime_state.dialogue_budget_used_per_location, {})
		for entity_id in ("initiator", "speaker_a", "speaker_b"):
			inbox = ws.get_entity_by_id(entity_id).get_component("PerceptionComponent").interaction_inbox
			self.assertEqual(inbox, [])

	def test_invalid_dialogue_step_is_a_terminal_contract_failure(self) -> None:
		ws, settlement, policies = _conversation_world()
		policies["a"].invalid = True

		with self.assertRaisesRegex(KernFailure, "must return Speak or Pass"):
			settlement.execute_bundle(
				{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": 4, "opening_text": "Opening"}]},
				{"self_id": "initiator", "actor_id": "initiator"},
			)

		self.assertEqual(ws.interaction_log, [])

	def test_child_interaction_failure_rolls_back_all_utterances(self) -> None:
		ws, settlement, _policies = _conversation_world()
		original = ws.record_interaction_attempt
		calls = 0

		def failing_record(**kwargs):
			nonlocal calls
			calls += 1
			if calls == 2:
				raise KernFailure("TEST_INTERACTION_FAILURE", "interaction write failed", origin="test", phase="interaction")
			return original(**kwargs)

		ws.record_interaction_attempt = failing_record
		with self.assertRaisesRegex(KernFailure, "interaction write failed"):
			settlement.execute_bundle(
				{"effects": [{"effect": "StartConversation", "max_utterances_per_tick": 4, "opening_text": "Opening"}]},
				{"self_id": "initiator", "actor_id": "initiator"},
			)

		self.assertEqual(ws.interaction_log, [])
		self.assertEqual(ws.runtime_state.dialogue_budget_used_per_location, {})

	def test_talk_recipe_does_not_compile_a_duplicate_narrative_interaction(self) -> None:
		runtime = KernRuntime.from_config(
			Path(__file__).resolve().parents[1],
			"runtime_config.camping.package.smoke.json",
			validate=True,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)
		runtime.world_state.services = {"interaction_engine": runtime.interaction_engine}

		resolved = resolve_action_intent(
			runtime.world_state,
			"camper_organizer",
			"test",
			{"verb": "Talk", "parameters": {"text": "Hello"}},
		)

		self.assertEqual(resolved["status"], "ready")
		self.assertEqual([item["effect"] for item in resolved["bundle"]["effects"]], ["StartConversation"])


if __name__ == "__main__":
	unittest.main()
