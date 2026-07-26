from __future__ import annotations

import unittest
from types import SimpleNamespace

from KERN.agent_workflow.context_builder import DecisionContextBuilder
from KERN.agent_workflow.contracts import EndTurn, TurnStart
from KERN.executor.executor import WorldExecutor
from KERN.models.components import MemoryComponent, PerceptionComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState


class AgentWorkflowRuntimeTests(unittest.TestCase):
	def test_frame_applies_pending_memory_before_workflow_reads_perception(self) -> None:
		ws = WorldState()
		location = Location(location_id="room", location_name="Room", description="")
		ws.register_location(location)
		agent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
		agent.add_component("MemoryComponent", MemoryComponent())
		agent.add_component("PerceptionComponent", PerceptionComponent(interaction_inbox=[{"interaction_id": "interaction_1", "tick": 1, "actor_id": "agent_01", "verb": "Remember", "narrative": "fresh memory visible during decide"}]))
		ws.register_entity(agent)
		location.add_entity_id(agent.entity_id)
		executor = WorldExecutor()
		ws.services["execute"] = lambda bundle, ctx: executor.execute_bundle(ws, bundle, ctx)
		ws.services["interaction_engine"] = SimpleNamespace(recipe_db={})

		frame = DecisionContextBuilder().build(ws, "agent_01", "test", {}, previous_action=None, actions_committed=0, replans=0)
		self.assertTrue(any(item.get("content") == "fresh memory visible during decide" for item in frame.perception["short_term_memory_items"]))

	def test_native_workflow_contract_uses_turn_session(self) -> None:
		class _Workflow:
			def begin_turn(self, _start: TurnStart):
				class _Session:
					def next_step(self, _frame):
						return EndTurn(meta={"provider": "test"})
				return _Session()

		workflow = _Workflow()
		self.assertIsInstance(workflow.begin_turn(TurnStart("turn", 1, 0, "agent", "test", "normal")).next_step(None), EndTurn)


if __name__ == "__main__":
	unittest.main()
