from __future__ import annotations

import unittest

from KERN.effect_bundle import effect_bundle_from_raw
from KERN.execution_errors import KernFailure
from KERN.executor.executor import WorldExecutor
from KERN.interaction.action_resolver import resolve_action_intent
from KERN.interaction.engine import InteractionEngine
from KERN.models.components import StatusComponent, TaskHostComponent, WorkerComponent
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState
from KERN.sim.trigger_system import TriggerSystem
from KERN.sim.world_settlement import WorldSettlement


def _has_status(ent: Entity, status_id: str) -> bool:
	comp = ent.get_component("StatusComponent")
	return isinstance(comp, StatusComponent) and comp.has_status(status_id)


class TaskLifecycleTests(unittest.TestCase):
	def setUp(self) -> None:
		self.ws = WorldState()
		self.executor = WorldExecutor()
		self.worker = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
		self.worker.add_component("WorkerComponent", WorkerComponent())
		self.station = Entity(entity_id="station_01", template_id="Station", entity_name="Station")
		self.station.add_component("StatusComponent", StatusComponent())
		self.station.add_component("TaskHostComponent", TaskHostComponent())
		self.ws.register_entity(self.worker)
		self.ws.register_entity(self.station)
		self.ws.services["execute"] = lambda bundle, ctx: self.executor.execute_bundle(self.ws, bundle, ctx)

	def _create_processing_task(self) -> str:
		events = self.executor.execute_bundle(
			self.ws,
			{
				"effects": [
					{
						"effect": "CreateTask",
						"assign_to": "self",
						"recipe": {
							"verb": "ProcessOre",
							"process": {
								"required_progress": 2,
								"start_bundle": {
									"effects": [
										{"effect": "AddStatus", "target": "target", "status_id": "is_in_use"}
									]
								},
								"cleanup_bundle": {
									"effects": [
										{"effect": "RemoveStatus", "target": "target", "status_id": "is_in_use"}
									]
								},
							},
							"bundle": {
								"effects": [
									{"effect": "AddStatus", "target": "target", "status_id": "processed"}
								]
							},
						},
					}
				]
			},
			{"self_id": "agent_01", "target_id": "station_01"},
		)
		self.assertFalse([ev for ev in events if ev.get("type") == "ExecutorError"])
		task_events = [ev for ev in events if ev.get("type") == "TaskCreated"]
		self.assertEqual(len(task_events), 1)
		return str(task_events[0]["payload"]["task_id"])

	def test_create_task_requires_target_task_host_component(self) -> None:
		self.station.components.pop("TaskHostComponent")

		with self.assertRaisesRegex(KernFailure, "CreateTask: target has no TaskHostComponent"):
			self._create_processing_task()

	def test_start_bundle_runs_when_task_is_assigned(self) -> None:
		task_id = self._create_processing_task()
		task = self.ws.get_task_by_id(task_id)
		self.assertIsNotNone(task)
		self.assertEqual(task.task_status, "InProgress")
		self.assertTrue(_has_status(self.station, "is_in_use"))

	def test_start_bundle_is_inside_executor_transaction_without_runtime_service(self) -> None:
		self.ws.services.clear()

		task_id = self._create_processing_task()

		self.assertIsNotNone(self.ws.get_task_by_id(task_id))
		self.assertTrue(_has_status(self.ws.get_entity_by_id("station_01"), "is_in_use"))

	def test_worker_tick_executes_task_children_without_runtime_service(self) -> None:
		self.ws.services.clear()
		task_id = self._create_processing_task()

		events = self.executor.execute(
			self.ws,
			{"effect": "WorkerTick", "ticks": 1},
			{"entity_id": "agent_01", "self_id": "agent_01", "task_id": task_id},
		)

		self.assertFalse([event for event in events if event.get("type") == "ExecutorError"])
		self.assertIn("TaskProgressed", [event["type"] for event in events])
		self.assertEqual(self.ws.get_task_by_id(task_id).progress, 1.0)

	def test_cleanup_bundle_runs_after_successful_finish(self) -> None:
		task_id = self._create_processing_task()
		events = self.executor.execute(
			self.ws,
			{"effect": "FinishTask"},
			{"self_id": "agent_01", "target_id": "station_01", "task_id": task_id},
		)
		self.assertEqual(events[0]["type"], "TaskFinished")
		self.assertFalse(_has_status(self.station, "is_in_use"))
		self.assertTrue(_has_status(self.station, "processed"))
		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, "")
		self.assertIsNone(self.ws.get_task_by_id(task_id))

	def test_cleanup_bundle_runs_after_cancel(self) -> None:
		task_id = self._create_processing_task()
		events = self.executor.execute(
			self.ws,
			{"effect": "CancelTask", "task_id": task_id, "reason": "test_cancel", "force": True},
			{"self_id": "agent_01", "task_id": task_id},
		)
		self.assertEqual(events[0]["type"], "TaskCancelled")
		self.assertFalse(_has_status(self.station, "is_in_use"))
		self.assertFalse(_has_status(self.station, "processed"))
		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, "")
		self.assertIsNone(self.ws.get_task_by_id(task_id))

	def test_interrupt_releases_and_resume_reacquires(self) -> None:
		task_id = self._create_processing_task()
		events = self.executor.execute(
			self.ws,
			{
				"effect": "InterruptTask",
				"task_id": task_id,
				"reason": "yield",
				"interrupt_source": "manual_yield",
				"is_voluntary": True,
			},
			{"self_id": "agent_01", "task_id": task_id},
		)
		self.assertEqual(events[0]["type"], "TaskInterrupted")
		self.assertFalse(_has_status(self.station, "is_in_use"))
		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, "")
		task = self.ws.get_task_by_id(task_id)
		self.assertIsNotNone(task)
		self.assertEqual(task.task_status, "Paused")

		events = self.executor.execute(
			self.ws,
			{"effect": "ResumeTask", "task_id": task_id},
			{"self_id": "agent_01", "task_id": task_id},
		)
		self.assertEqual(events[0]["type"], "TaskResumed")
		self.assertTrue(_has_status(self.station, "is_in_use"))
		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, task_id)

	def test_yield_current_task_records_an_agent_visible_interaction(self) -> None:
		task_id = self._create_processing_task()
		self.ws.services["interaction_engine"] = InteractionEngine(recipe_db={})
		resolved = resolve_action_intent(
			self.ws,
			"agent_01",
			"respond to interrupt",
			{"verb": "YieldCurrentTask", "parameters": {}},
		)
		settlement = WorldSettlement(
			ws=self.ws,
			executor=self.executor,
			trigger_system=TriggerSystem(),
			max_reaction_depth=4,
		)

		settlement.execute_bundle(resolved["bundle"], resolved["context"])

		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, "")
		self.assertEqual(self.ws.get_task_by_id(task_id).task_status, "Paused")
		self.assertEqual(len(self.ws.interaction_log), 1)
		self.assertEqual(self.ws.interaction_log[0]["verb"], "YieldCurrentTask")
		self.assertEqual(self.ws.interaction_log[0]["task_id"], task_id)

	def test_interrupt_current_task_marks_status_and_cleans_up(self) -> None:
		task_id = self._create_processing_task()
		events = self.executor.execute(
			self.ws,
			{
				"effect": "InterruptCurrentTask",
				"target": "self",
				"status": "Failed",
				"reason": "fainted_by_stress",
			},
			{"self_id": "agent_01"},
		)
		self.assertEqual(events[0]["type"], "CurrentTaskInterrupted")
		self.assertEqual(events[0]["payload"]["task_id"], task_id)
		self.assertEqual(events[0]["payload"]["new_status"], "Failed")
		self.assertFalse(_has_status(self.station, "is_in_use"))
		self.assertEqual(self.worker.get_component("WorkerComponent").current_task_id, "")
		self.assertIsNone(self.ws.get_task_by_id(task_id))


if __name__ == "__main__":
	unittest.main()
