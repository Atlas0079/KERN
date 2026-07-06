from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.memory_policy import build_memory_patch
from KERN.agent_workflow.observer import build_agent_perception
from KERN.executor.executor import WorldExecutor
from KERN.external_runtimes import SQLiteSocialPlatformRuntime
from KERN.models.components import ContainerComponent, ContainerSlot, MemoryComponent, ScreenComponent, TagComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState


def _world_with_phone(db_path: Path, *, phone_in_inventory: bool = True) -> tuple[WorldState, SQLiteSocialPlatformRuntime]:
	ws = WorldState()
	loc = Location(location_id="room", location_name="Room", description="")
	ws.register_location(loc)
	agent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	agent.add_component("MemoryComponent", MemoryComponent(short_term_max_entries=5))
	agent.add_component("ContainerComponent", ContainerComponent(slots={"inventory": ContainerSlot(config={"capacity_count": 4}, items=[])}))
	ws.register_entity(agent)
	loc.add_entity_id(agent.entity_id)
	phone = Entity(entity_id="phone_01", template_id="Phone", entity_name="Phone")
	phone.add_component("TagComponent", TagComponent(tags=["device", "phone"]))
	phone.add_component(
		"ScreenComponent",
		ScreenComponent(runtime_id="social", account_id="acc_agent", app="social_platform"),
	)
	ws.register_entity(phone)
	if phone_in_inventory:
		agent.get_component("ContainerComponent").slots["inventory"].items.append(phone.entity_id)
	else:
		loc.add_entity_id(phone.entity_id)
	rt = SQLiteSocialPlatformRuntime(db_path, runtime_id="social")
	rt.upsert_account("acc_agent", "Agent", interests={"kindergarten": 1.0, "outdoor": 1.0})
	rt.upsert_account("acc_teacher", "Teacher", interests={"kindergarten": 1.0})
	rt.invoke(
		"create_post",
		{
			"account_id": "acc_teacher",
			"post_id": "post_outdoor",
			"text": "Bring a water bottle for outdoor play tomorrow.",
			"tags": ["kindergarten", "outdoor"],
			"tick": 1,
		},
		{},
	)
	ws.services["external_runtime_bridge"] = __import__("KERN.external_runtime", fromlist=["ExternalRuntimeBridge"]).ExternalRuntimeBridge(
		{"social": rt}
	)
	return ws, rt


class SocialPlatformEffectTests(unittest.TestCase):
	def test_observe_feed_updates_phone_screen_and_slot_opens_post(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, _rt = _world_with_phone(Path(td) / "social.sqlite3")
			executor = WorldExecutor()

			feed_events = executor.execute(
				ws,
				{"effect": "ObserveSocialFeed", "target": "phone_01", "limit": 1},
				{"self_id": "agent_01"},
			)

			self.assertEqual(feed_events[0]["type"], "SocialFeedObserved")
			screen = ws.get_entity_by_id("phone_01").get_component("ScreenComponent")
			self.assertEqual(screen.view, "feed")
			self.assertEqual(screen.feed_items[0]["post_id"], "post_outdoor")
			self.assertEqual(screen.selected_post_id, "post_outdoor")

			post_events = executor.execute(
				ws,
				{"effect": "ObserveSocialPost", "target": "phone_01", "slot": 0},
				{"self_id": "agent_01"},
			)

			self.assertEqual(post_events[0]["type"], "SocialPostObserved")
			self.assertEqual(post_events[0]["post"]["post_id"], "post_outdoor")
			self.assertEqual(screen.view, "post")
			self.assertEqual(screen.current_post["post_id"], "post_outdoor")

	def test_environment_phone_screen_is_not_agent_observable(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, _rt = _world_with_phone(Path(td) / "social.sqlite3", phone_in_inventory=False)
			executor = WorldExecutor()
			ws.game_time.total_ticks = 10
			executor.execute(
				ws,
				{"effect": "ObserveSocialFeed", "target": "phone_01", "limit": 1},
				{"self_id": "agent_01"},
			)

			planner_view = build_full_ws_view(ws, "agent_01", "test", {})
			planner_perception = build_agent_perception(planner_view, "agent_01")
			phone = next(x for x in planner_perception["entities"] if x["id"] == "phone_01")
			self.assertNotIn("screen", phone)
			self.assertNotIn("operable_screen_contexts", planner_perception)

			grounder_view = build_full_ws_view(ws, "agent_01", "test", {"grounder": True})
			grounder_perception = build_agent_perception(grounder_view, "agent_01")
			self.assertEqual(grounder_perception.get("operable_screen_contexts", []), [])

	def test_grounder_gets_fresh_screen_context_only_for_inventory_phone(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, _rt = _world_with_phone(Path(td) / "social.sqlite3", phone_in_inventory=True)
			executor = WorldExecutor()
			ws.game_time.total_ticks = 10
			executor.execute(
				ws,
				{"effect": "ObserveSocialFeed", "target": "phone_01", "limit": 1},
				{"self_id": "agent_01"},
			)

			planner_view = build_full_ws_view(ws, "agent_01", "test", {})
			planner_perception = build_agent_perception(planner_view, "agent_01")
			self.assertFalse(any(x["id"] == "phone_01" for x in planner_perception["entities"]))
			self.assertNotIn("operable_screen_contexts", planner_perception)

			grounder_view = build_full_ws_view(ws, "agent_01", "test", {"grounder": True})
			grounder_perception = build_agent_perception(grounder_view, "agent_01")
			ctx = grounder_perception["operable_screen_contexts"][0]
			self.assertEqual(ctx["entity_id"], "phone_01")
			self.assertEqual(ctx["feed_items"][0]["post_id"], "post_outdoor")
			self.assertIn("outdoor play", ctx["feed_items"][0]["summary"])

			ws.game_time.total_ticks = 13
			expired_view = build_full_ws_view(ws, "agent_01", "test", {"grounder": True})
			expired_perception = build_agent_perception(expired_view, "agent_01")
			self.assertEqual(expired_perception.get("operable_screen_contexts", []), [])

	def test_social_feed_exposure_can_enter_memory_with_low_importance(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, _rt = _world_with_phone(Path(td) / "social.sqlite3")
			executor = WorldExecutor()

			events = executor.execute(
				ws,
				{"effect": "ObserveSocialFeed", "target": "phone_01", "limit": 1},
				{"self_id": "agent_01"},
			)
			ws.record_event(events[0], {"self_id": "agent_01"})
			view = build_full_ws_view(ws, "agent_01", "test", {})

			patch = build_memory_patch(view, {}, "agent_01")

			self.assertIsNotNone(patch)
			note = patch["notes"][0]
			self.assertEqual(note["topic"], "external_platform_event")
			self.assertLess(note["importance"], 0.45)
			self.assertIn("outdoor play", note["content"])

	def test_low_importance_social_feed_memory_decays_out_of_short_term(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, _rt = _world_with_phone(Path(td) / "social.sqlite3")
			executor = WorldExecutor()

			events = executor.execute(
				ws,
				{"effect": "ObserveSocialFeed", "target": "phone_01", "limit": 1},
				{"self_id": "agent_01"},
			)
			ws.record_event(events[0], {"self_id": "agent_01"})
			view = build_full_ws_view(ws, "agent_01", "test", {})
			patch = build_memory_patch(view, {}, "agent_01")
			self.assertIsNotNone(patch)

			executor.execute(
				ws,
				{"effect": "ApplyMemoryPatch", "target": "agent_01", **patch},
				{"self_id": "agent_01"},
			)
			mem = ws.get_entity_by_id("agent_01").get_component("MemoryComponent")
			self.assertTrue(any("outdoor play" in x.get("content", "") for x in mem.short_term_queue))

			ws.game_time.total_ticks = 2
			mem.per_tick(ws, "agent_01", 1)

			self.assertFalse(any("outdoor play" in x.get("content", "") for x in mem.short_term_queue))


if __name__ == "__main__":
	unittest.main()
