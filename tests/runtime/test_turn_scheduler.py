from __future__ import annotations

import unittest
from typing import Any

from KERN.sim.turn_scheduler import TurnScheduler
from KERN.sim.active_phase import ParallelBatchActivePhaseStrategy
from KERN.agent_workflow.contracts import EndTurn, SubmitAction
from KERN.execution_errors import KernFailure
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.models.components import AgentControlComponent, AgentWakePolicyComponent, MemoryComponent, PerceptionComponent, TagComponent, TaskHostComponent, WorkerComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.sim.trigger_system import TriggerSystem
from KERN.sim.world_settlement import WorldSettlement
from KERN.runtime import KernRuntime


class _SequenceWorkflow:
	def __init__(self, decisions: list[dict[str, Any]]) -> None:
		self.decisions = list(decisions)
		self.mode_contexts: list[dict[str, Any]] = []

	def begin_turn(self, _ws, _start):
		workflow = self
		class _Session:
			pending: list[dict[str, Any]] = []
			def next_step(self, _ws, frame):
				workflow.mode_contexts.append(dict(frame.mode_context))
				if frame.previous_action is not None and frame.previous_action.status == "rejected":
					self.pending.clear()
				if self.pending:
					return SubmitAction(self.pending.pop(0))
				decision = workflow.decisions.pop(0)
				if decision["type"] == "end_turn":
					return EndTurn()
				self.pending = [dict(item) for item in decision["actions"]]
				return SubmitAction(self.pending.pop(0))
		return _Session()


def _world(workflow: Any, recipes: dict[str, Any], reactions: list[dict[str, Any]] | None = None) -> tuple[WorldState, WorldSettlement]:
	ws = WorldState()
	location = Location(location_id="room", location_name="Room", description="")
	ws.register_location(location)
	actor = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
	actor.add_component("AgentControlComponent", AgentControlComponent())
	actor.add_component("AgentWakePolicyComponent", AgentWakePolicyComponent(ruleset=[{"type": "NoActiveTask", "priority": 1}]))
	actor.add_component("MemoryComponent", MemoryComponent())
	actor.add_component("PerceptionComponent", PerceptionComponent())
	actor.add_component("TagComponent", TagComponent())
	actor.add_component("TaskHostComponent", TaskHostComponent())
	actor.add_component("WorkerComponent", WorkerComponent())
	ws.register_entity(actor)
	location.add_entity_id(actor.entity_id)
	ws.services = {
		"interaction_engine": InteractionEngine(recipe_db=recipes),
		"default_action_provider": workflow,
		"action_providers": {},
		"workflow_view_profile": {},
	}
	settlement = WorldSettlement(
		ws=ws,
		executor=WorldExecutor(),
		trigger_system=TriggerSystem(rules=list(reactions or [])),
		max_reaction_depth=8,
	)
	ws.services["execute"] = settlement.execute_bundle
	return ws, settlement


def _add_controlled_agent(ws: WorldState, actor_id: str) -> None:
	actor = Entity(entity_id=actor_id, template_id="Agent", entity_name=actor_id)
	actor.add_component("AgentControlComponent", AgentControlComponent())
	actor.add_component("AgentWakePolicyComponent", AgentWakePolicyComponent(ruleset=[{"type": "NoActiveTask", "priority": 1}]))
	actor.add_component("MemoryComponent", MemoryComponent())
	actor.add_component("PerceptionComponent", PerceptionComponent())
	actor.add_component("TagComponent", TagComponent())
	actor.add_component("TaskHostComponent", TaskHostComponent())
	actor.add_component("WorkerComponent", WorkerComponent())
	ws.register_entity(actor)
	ws.get_location_by_id("room").add_entity_id(actor.entity_id)


class TurnSchedulerTests(unittest.TestCase):
	def test_native_turn_session_receives_post_settlement_feedback(self) -> None:
		class _NativeWorkflow:
			def __init__(self) -> None:
				self.feedback_statuses: list[str] = []

			def begin_turn(self, _ws, _start):
				workflow = self

				class _Session:
					step_index = 0

					def next_step(self, _ws, frame):
						if frame.previous_action is not None:
							workflow.feedback_statuses.append(frame.previous_action.status)
						self.step_index += 1
						if self.step_index == 1:
							return SubmitAction({"verb": "Start", "target_id": "agent", "parameters": {}})
						if self.step_index == 2:
							return SubmitAction({"verb": "Finish", "target_id": "agent", "parameters": {}})
						return EndTurn()

				return _Session()

		workflow = _NativeWorkflow()
		recipes = {
			"start": {"verb": "Start", "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "started"}]}},
			"finish": {
				"verb": "Finish",
				"condition": {"type": "has_tag", "target": "self", "tag": "reaction_complete"},
				"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "finished"}]},
			},
		}
		reactions = [{
			"id": "complete_start",
			"on_event": "TagAdded",
			"condition": {"type": "event_field_eq", "field": "payload.tag", "value": "started"},
			"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reaction_complete"}]},
		}]
		ws, settlement = _world(workflow, recipes, reactions)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		self.assertEqual(ws.get_entity_by_id("agent").get_all_tags(), ["started", "reaction_complete", "finished"])
		self.assertEqual(workflow.feedback_statuses, ["committed", "committed"])

	def test_native_turn_session_receives_rejection_and_continues_same_session(self) -> None:
		class _NativeWorkflow:
			def __init__(self) -> None:
				self.sessions_started = 0
				self.rejection_code = ""

			def begin_turn(self, _ws, _start):
				self.sessions_started += 1
				workflow = self

				class _Session:
					step_index = 0

					def next_step(self, _ws, frame):
						self.step_index += 1
						if self.step_index == 1:
							return SubmitAction({"verb": "Missing", "target_id": "gone", "parameters": {}})
						if self.step_index == 2:
							workflow.rejection_code = frame.previous_action.rejection_code
							return SubmitAction({"verb": "Recover", "target_id": "agent", "parameters": {}})
						return EndTurn()

				return _Session()

		workflow = _NativeWorkflow()
		ws, settlement = _world(
			workflow,
			{"recover": {"verb": "Recover", "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "recovered"}]}}},
		)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		self.assertEqual(workflow.sessions_started, 1)
		self.assertEqual(workflow.rejection_code, "TARGET_MISSING")
		self.assertEqual(ws.get_entity_by_id("agent").get_all_tags(), ["recovered"])

	def test_each_action_resolves_after_prior_reactions_settle(self) -> None:
		workflow = _SequenceWorkflow([
			{
				"type": "action_plan",
				"actions": [
					{"verb": "Start", "target_id": "agent", "parameters": {}},
					{"verb": "Finish", "target_id": "agent", "parameters": {}},
				],
			},
			{"type": "end_turn"},
		])
		recipes = {
			"start": {"verb": "Start", "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "started"}]}},
			"finish": {
				"verb": "Finish",
				"condition": {"type": "has_tag", "target": "self", "tag": "reaction_complete"},
				"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "finished"}]},
			},
		}
		reactions = [{
			"id": "complete_start",
			"on_event": "TagAdded",
			"condition": {"type": "event_field_eq", "field": "payload.tag", "value": "started"},
			"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "reaction_complete"}]},
		}]
		ws, settlement = _world(workflow, recipes, reactions)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		self.assertEqual(ws.get_entity_by_id("agent").get_all_tags(), ["started", "reaction_complete", "finished"])
		action_ids = {
			record["event"]["action_id"]
			for record in ws.event_log
			if record["event"].get("action_id")
		}
		self.assertEqual(action_ids, {"tick:0:turn:0:attempt:0", "tick:0:turn:0:attempt:1"})

	def test_rejection_discards_plan_tail_and_replans_in_same_turn(self) -> None:
		workflow = _SequenceWorkflow([
			{
				"type": "action_plan",
				"actions": [
					{"verb": "Keep", "target_id": "agent", "parameters": {}},
					{"verb": "Missing", "target_id": "gone", "parameters": {}},
					{"verb": "Discarded", "target_id": "agent", "parameters": {}},
				],
			},
			{"type": "action_plan", "actions": [{"verb": "Recover", "target_id": "agent", "parameters": {}}]},
			{"type": "end_turn"},
		])
		recipes = {
			name.lower(): {"verb": name, "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": name.lower()}]}}
			for name in ("Keep", "Discarded", "Recover")
		}
		ws, settlement = _world(workflow, recipes)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		tags = ws.get_entity_by_id("agent").get_all_tags()
		self.assertEqual(tags, ["keep", "recover"])
		rejections = [context["rejection"] for context in workflow.mode_contexts if context.get("rejection")]
		self.assertEqual(rejections[0]["code"], "TARGET_MISSING")
		self.assertEqual(ws.interaction_log[-1]["interaction_origin"], "action_rejection")
		self.assertEqual(ws.interaction_log[-1]["action_id"], "tick:0:turn:0:attempt:1")

	def test_replan_budget_failure_keeps_rejection_interaction(self) -> None:
		workflow = _SequenceWorkflow([
			{"type": "action_plan", "actions": [{"verb": "Missing", "target_id": "gone", "parameters": {}}]},
		])
		ws, settlement = _world(workflow, {})

		with self.assertRaises(KernFailure) as caught:
			TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=0).run_active_phase(ws, settlement)

		self.assertEqual(caught.exception.code, "TURN_REPLAN_BUDGET_EXCEEDED")
		self.assertEqual(len(ws.interaction_log), 1)
		self.assertEqual(ws.interaction_log[0]["status"], "rejected")

	def test_abort_action_stops_remaining_plan_and_decisions(self) -> None:
		workflow = _SequenceWorkflow([
			{
				"type": "action_plan",
				"actions": [
					{"verb": "Abort", "target_id": "agent", "parameters": {}},
					{"verb": "Discarded", "target_id": "agent", "parameters": {}},
				],
			},
		])
		recipes = {
			"abort": {
				"verb": "Abort",
				"bundle": {"effects": [{"effect": "AbortSimulation", "reason": "done", "detail": "", "severity": "info", "stop": True}]},
			},
			"discarded": {"verb": "Discarded", "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "discarded"}]}},
		}
		ws, settlement = _world(workflow, recipes)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		self.assertTrue(ws.runtime_state.abort_requested)
		self.assertNotIn("discarded", ws.get_entity_by_id("agent").get_all_tags())
		self.assertEqual(len(workflow.mode_contexts), 1)

	def test_starting_long_task_discards_remaining_plan_and_ends_turn(self) -> None:
		workflow = _SequenceWorkflow([
			{
				"type": "action_plan",
				"actions": [
					{"verb": "Work", "target_id": "agent", "parameters": {}},
					{"verb": "Discarded", "target_id": "agent", "parameters": {}},
				],
			},
		])
		recipes = {
			"work": {
				"verb": "Work",
				"process": {"assign_to": "self", "required_progress": 2},
				"bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "work_complete"}]},
			},
			"discarded": {"verb": "Discarded", "bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "discarded"}]}},
		}
		ws, settlement = _world(workflow, recipes)

		TurnScheduler(max_actions_per_turn=5, max_replans_per_turn=2).run_active_phase(ws, settlement)

		self.assertTrue(ws.get_entity_by_id("agent").get_component("WorkerComponent").current_task_id)
		self.assertNotIn("discarded", ws.get_entity_by_id("agent").get_all_tags())
		self.assertEqual(len(workflow.mode_contexts), 1)

	def test_runtime_finishes_all_passive_entity_ticks_before_first_turn(self) -> None:
		class _InspectWorkflow:
			def __init__(self) -> None:
				self.saw_bystander_tick = False

			def begin_turn(self, _ws, _start):
				workflow = self
				class _Session:
					def next_step(self, ws, _frame):
						bystander = ws.get_entity_by_id("bystander")
						workflow.saw_bystander_tick = "passive_tick_complete" in bystander.get_all_tags()
						return EndTurn()
				return _Session()

		workflow = _InspectWorkflow()
		ws, _settlement = _world(workflow, {})
		bystander = Entity(entity_id="bystander", template_id="Thing", entity_name="Bystander")
		bystander.add_component("TagComponent", TagComponent())
		ws.register_entity(bystander)
		ws.get_location_by_id("room").add_entity_id("bystander")
		runtime = KernRuntime(
			world_state=ws,
			interaction_engine=ws.services["interaction_engine"],
			executor=WorldExecutor(),
			action_provider=workflow,
			reaction_rules=[{
				"id": "mark_passive_tick",
				"on_event": "AdvanceTick",
				"bundle": {"effects": [{"effect": "AddTag", "target": "event_entity", "tag": "passive_tick_complete"}]},
			}],
			checkpoint_enabled=False,
		)
		runtime.is_running = True

		runtime.step()

		self.assertTrue(workflow.saw_bystander_tick)

	def test_parallel_batch_commits_ready_steps_in_turn_order(self) -> None:
		class _Workflow:
			def begin_turn(self, _ws, start):
				actor_id = start.actor_id

				class _Session:
					done = False

					def next_step(self, _ws, _frame):
						if self.done:
							return EndTurn()
						self.done = True
						return SubmitAction({"verb": "Mark", "target_id": actor_id, "parameters": {"tag": actor_id}})

				return _Session()

		workflow = _Workflow()
		ws, settlement = _world(
			workflow,
			{
				"mark": {
					"verb": "Mark",
					"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "param:tag"}]},
				}
			},
		)
		ws.entities.pop("agent")
		ws.get_location_by_id("room").remove_entity_id("agent")
		_add_controlled_agent(ws, "agent_b")
		_add_controlled_agent(ws, "agent_a")

		ParallelBatchActivePhaseStrategy(max_actions_per_turn=2, max_replans_per_turn=0, max_workers=2).run_active_phase(ws, settlement)

		action_events = [
			record["event"]
			for record in ws.event_log
			if record["event"].get("action_id") and record["event"].get("type") == "TagAdded"
		]
		self.assertEqual([event["context"]["target_id"] for event in action_events], ["agent_a", "agent_b"])
		self.assertEqual([event["action_id"] for event in action_events], ["tick:0:turn:0:attempt:0", "tick:0:turn:1:attempt:0"])

	def test_parallel_batch_wraps_prepared_worker_exception(self) -> None:
		class _Prepared:
			def run(self):
				raise OSError("provider unavailable")

			def complete(self, _result):
				return EndTurn()

		class _Workflow:
			def begin_turn(self, _ws, _start):
				class _Session:
					def next_step(self, _ws, _frame):
						return EndTurn()

					def prepare_parallel_next_step(self, _ws, _frame):
						return _Prepared()

				return _Session()

		ws, settlement = _world(_Workflow(), {})

		with self.assertRaises(KernFailure) as caught:
			ParallelBatchActivePhaseStrategy(max_actions_per_turn=1, max_replans_per_turn=0, max_workers=1).run_active_phase(ws, settlement)

		self.assertEqual(caught.exception.code, "WORKFLOW_PROVIDER_EXCEPTION")
		self.assertEqual(caught.exception.origin, "workflow")
		self.assertEqual(caught.exception.phase, "decision")
		self.assertEqual(caught.exception.context["actor_id"], "agent")
		self.assertEqual(caught.exception.context["turn_id"], "tick:0:turn:0")


if __name__ == "__main__":
	unittest.main()
