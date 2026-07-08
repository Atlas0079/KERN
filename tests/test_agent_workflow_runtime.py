from __future__ import annotations

import unittest
from typing import Any

from KERN.agent_workflow.runtime import run_workflow_cycle
from KERN.executor.executor import WorldExecutor
from KERN.models.components import MemoryComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState


class _MemoryPatchWorkflow:
	def __init__(self) -> None:
		self.saw_patched_memory = False

	def build_memory_patch_data(self, _ws_view: Any, _recipe_db: dict[str, Any], actor_id: str) -> dict[str, Any]:
		return {
			"notes": [
				{
					"tick": 1,
					"type": "event",
					"topic": "test",
					"importance": 0.5,
					"actor_id": actor_id,
					"content": "fresh memory visible during decide",
				}
			],
			"last_event_seq_seen": 1,
			"last_interaction_seq_seen": 0,
			"mid_term_summaries": [],
			"clear_mid_term_prep": False,
		}

	def decide(self, ws_view: dict[str, Any], _recipe_db: dict[str, Any], actor_id: str, _reason: str, _mode_context: dict[str, Any]) -> dict[str, Any]:
		full_view = dict(ws_view.get("full_ws_view", {}) or {})
		actor = next(x for x in full_view.get("entities", []) if x.get("id") == actor_id)
		short_term = list((actor.get("memory", {}) or {}).get("short_term_queue", []) or [])
		self.saw_patched_memory = any(x.get("content") == "fresh memory visible during decide" for x in short_term)
		return {"type": "noop", "meta": {"provider": "test"}}


class _CaptureProfileWorkflow:
	def __init__(self) -> None:
		self.profile_id = ""

	def build_memory_patch_data(self, _ws_view: Any, _recipe_db: dict[str, Any], _actor_id: str) -> None:
		return None

	def decide(self, ws_view: dict[str, Any], _recipe_db: dict[str, Any], _actor_id: str, _reason: str, _mode_context: dict[str, Any]) -> dict[str, Any]:
		full_view = dict(ws_view.get("full_ws_view", {}) or {})
		self.profile_id = str((full_view.get("workflow_view_profile", {}) or {}).get("profile_id", "") or "")
		return {"type": "noop", "meta": {"provider": "test"}}


class AgentWorkflowRuntimeTests(unittest.TestCase):
	def test_decide_sees_memory_patch_applied_at_start_of_cycle(self) -> None:
		ws = WorldState()
		loc = Location(location_id="room", location_name="Room", description="")
		ws.register_location(loc)
		agent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
		agent.add_component("MemoryComponent", MemoryComponent())
		ws.register_entity(agent)
		loc.add_entity_id(agent.entity_id)
		executor = WorldExecutor()
		ws.services["execute"] = lambda bundle, ctx: executor.execute_bundle(ws, bundle, ctx)

		workflow = _MemoryPatchWorkflow()
		outcome = run_workflow_cycle(ws, "agent_01", workflow, "test", {})

		self.assertEqual(outcome["type"], "noop")
		self.assertTrue(workflow.saw_patched_memory)

	def test_workflow_cycle_attaches_view_profile_from_services(self) -> None:
		ws = WorldState()
		loc = Location(location_id="room", location_name="Room", description="")
		ws.register_location(loc)
		agent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
		agent.add_component("MemoryComponent", MemoryComponent())
		ws.register_entity(agent)
		loc.add_entity_id(agent.entity_id)
		ws.services["workflow_view_profile"] = {"profile_id": "social_platform"}

		workflow = _CaptureProfileWorkflow()
		outcome = run_workflow_cycle(ws, "agent_01", workflow, "test", {})

		self.assertEqual(outcome["type"], "noop")
		self.assertEqual(workflow.profile_id, "social_platform")


if __name__ == "__main__":
	unittest.main()
