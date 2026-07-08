from __future__ import annotations

import unittest
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.memory_policy import build_memory_patch
from KERN.agent_workflow.observer import build_agent_perception
from KERN.models.components import ContainerComponent, ContainerSlot, MemoryComponent, ScreenComponent, TagComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.path import Path as WorldPath
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime


def _world_with_two_agents() -> WorldState:
	ws = WorldState()
	room = Location(location_id="room", location_name="Room", description="A shared test room.")
	other_room = Location(location_id="other", location_name="Other", description="")
	ws.register_location(room)
	ws.register_location(other_room)
	ws.register_path(WorldPath(path_id="path_room_other", from_location_id="room", to_location_id="other"))

	for agent_id in ("agent_01", "agent_02"):
		agent = Entity(entity_id=agent_id, template_id="Agent", entity_name=agent_id)
		agent.add_component("TagComponent", TagComponent(tags=["agent"]))
		agent.add_component("MemoryComponent", MemoryComponent())
		agent.add_component("ContainerComponent", ContainerComponent(slots={"inventory": ContainerSlot(config={"capacity_count": 2}, items=[])}))
		ws.register_entity(agent)
		room.add_entity_id(agent.entity_id)

	phone = Entity(entity_id="phone_01", template_id="Phone", entity_name="Phone")
	phone.add_component("TagComponent", TagComponent(tags=["phone"]))
	phone.add_component("ScreenComponent", ScreenComponent(runtime_id="social", account_id="acc_01", app="social_platform"))
	ws.register_entity(phone)
	ws.get_entity_by_id("agent_01").get_component("ContainerComponent").slots["inventory"].items.append("phone_01")
	return ws


class WorkflowViewProfileTests(unittest.TestCase):
	def test_social_platform_profile_hides_physical_context_but_keeps_phone_inventory(self) -> None:
		ws = _world_with_two_agents()
		view = build_full_ws_view(
			ws,
			"agent_01",
			"test",
			{"grounder": True, "workflow_view_profile": {"profile_id": "social_platform"}},
		)
		view["workflow_view_profile"] = {"profile_id": "social_platform"}

		perception = build_agent_perception(view, "agent_01")

		self.assertEqual(perception["entities"], [])
		self.assertEqual(perception["map_topology"], [])
		self.assertEqual(perception["reachable_locations"], [])
		self.assertFalse(perception["can_start_conversation_here"])
		self.assertEqual([x["id"] for x in perception["inventory"]], ["phone_01"])
		self.assertEqual(perception["operable_screen_contexts"][0]["entity_id"], "phone_01")

	def test_social_platform_profile_drops_other_actor_social_memory_in_same_location(self) -> None:
		ws = _world_with_two_agents()
		ws.record_event(
			{
				"type": "SocialFeedObserved",
				"items": [{"author_display_name": "Source", "summary": "Other agent saw this."}],
				"memory_hint": {"importance": 0.3},
			},
			{"actor_id": "agent_02"},
		)
		view = build_full_ws_view(
			ws,
			"agent_01",
			"test",
			{"workflow_view_profile": {"profile_id": "social_platform"}},
		)
		view["workflow_view_profile"] = {"profile_id": "social_platform"}

		patch = build_memory_patch(view, {}, "agent_01")

		self.assertIsNotNone(patch)
		self.assertEqual(patch["notes"], [])
		self.assertGreaterEqual(patch["last_event_seq_seen"], 1)

	def test_rumor_spread_config_enables_social_platform_profile(self) -> None:
		root = Path(__file__).resolve().parents[1]
		runtime = KernRuntime.from_config(
			root,
			"runtime_config.rumor_spread.smoke.json",
			validate=True,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)

		self.assertEqual(runtime.workflow_view_profile["profile_id"], "social_platform")
		self.assertFalse(runtime.workflow_view_profile["perception"]["include_visible_entities"])


if __name__ == "__main__":
	unittest.main()
