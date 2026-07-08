from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtime import ExternalRuntimeBridge
from KERN.external_runtimes import SQLiteSocialPlatformRuntime
from KERN.external_runtimes.social_seed import build_seed_posts, seed_social_platform_runtime
from KERN.runtime import KernRuntime


def _runtime_with_temp_social_db(db_path: Path) -> KernRuntime:
	project_root = Path(__file__).resolve().parents[1]
	return KernRuntime.from_config(
		project_root,
		"runtime_config.rumor_spread.smoke.json",
		validate=True,
		configure_logging=False,
		overrides={
			"CHECKPOINT_EVERY_TICK": "0",
			"USE_LLM": "0",
			"EXTERNAL_RUNTIMES_JSON": json.dumps(
				{
					"social": {
						"type": "sqlite_social_platform",
						"db_path": str(db_path),
						"reset_db": True,
						"seed_json": "Data/RumorSpread/social_seed.json",
					}
				}
			),
		},
	)


def _run_command(runtime: KernRuntime, actor_id: str, verb: str, parameters: dict, target_id: str) -> list[dict]:
	ws = runtime.world_state
	cmd = runtime.interaction_engine.process_command(
		ws,
		actor_id,
		{"verb": verb, "target_id": target_id, "parameters": dict(parameters or {})},
	)
	if cmd.get("status") != "success":
		raise AssertionError(f"{verb} command failed: {cmd}")
	return runtime.executor.execute_bundle(ws, cmd["bundle"], cmd["context"])


class RumorSpreadConfigRuntimeTests(unittest.TestCase):
	def test_config_declares_sqlite_social_runtime_and_seed_data(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")

			adapter = runtime.external_runtimes.get("social")
			self.assertIsInstance(adapter, SQLiteSocialPlatformRuntime)
			events = adapter.invoke("observe_feed", {"account_id": "acc_student_high_media", "limit": 5, "tick": 1}, {})

			self.assertEqual(events[0]["type"], "SocialFeedObserved")
			summaries = [str(item.get("summary", "")) for item in events[0]["items"]]
			self.assertTrue(any("饮水机" in text for text in summaries))

	def test_rumor_spread_scene_recipes_update_phone_screen(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			ws.services["external_runtime_bridge"] = ExternalRuntimeBridge(runtime.external_runtimes)
			agent_inventory = ws.get_entity_by_id("agent_student_high_media").get_component("ContainerComponent").slots["inventory"].items
			self.assertIn("phone_student_high_media", agent_inventory)

			feed_cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_student_high_media",
				{"verb": "BrowseSocialFeed", "target_id": "phone_student_high_media", "parameters": {"limit": 1}},
			)
			self.assertEqual(feed_cmd["status"], "success")
			feed_events = runtime.executor.execute_bundle(ws, feed_cmd["bundle"], feed_cmd["context"])
			self.assertEqual(feed_events[0]["type"], "SocialFeedObserved")

			screen = ws.get_entity_by_id("phone_student_high_media").get_component("ScreenComponent")
			self.assertEqual(screen.view, "feed")
			self.assertEqual(len(screen.feed_items), 1)
			self.assertTrue(screen.feed_items[0]["post_id"])

			open_cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_student_high_media",
				{"verb": "OpenSocialPost", "target_id": "phone_student_high_media", "parameters": {"slot": 0}},
			)
			self.assertEqual(open_cmd["status"], "success")
			open_events = runtime.executor.execute_bundle(ws, open_cmd["bundle"], open_cmd["context"])

			self.assertEqual(open_events[0]["type"], "SocialPostObserved")
			self.assertEqual(screen.view, "post")
			self.assertEqual(screen.current_post["post_id"], screen.selected_post_id)

	def test_rumor_spread_recipes_require_carried_phone_target(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			agent = ws.get_entity_by_id("agent_student_high_media")
			container = agent.get_component("ContainerComponent")
			self.assertTrue(container.remove_entity_by_id("phone_student_high_media"))
			ws.get_location_by_id("rumor_lab_room").add_entity_id("phone_student_high_media")

			cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_student_high_media",
				{"verb": "BrowseSocialFeed", "target_id": "phone_student_high_media", "parameters": {"limit": 1}},
			)

			self.assertEqual(cmd["status"], "failed")
			self.assertEqual(cmd["reason"], "NO_RECIPE")

	def test_rumor_spread_scene_exposes_core_propagation_actions(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			ws.services["external_runtime_bridge"] = ExternalRuntimeBridge(runtime.external_runtimes)

			actor_id = "agent_student_high_media"
			phone_id = "phone_student_high_media"
			feed_events = _run_command(runtime, actor_id, "BrowseSocialFeed", {"limit": 3}, phone_id)
			self.assertEqual(feed_events[0]["type"], "SocialFeedObserved")

			open_events = _run_command(runtime, actor_id, "OpenSocialPost", {"slot": 0}, phone_id)
			self.assertEqual(open_events[0]["type"], "SocialPostObserved")

			comment_events = _run_command(runtime, actor_id, "CommentSocialPost", {"slot": 0, "text": "Inspector test comment."}, phone_id)
			self.assertEqual(comment_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(comment_events[0]["action"], "comment")

			repost_events = _run_command(runtime, actor_id, "RepostSocialPost", {"slot": 0, "text": "Inspector test repost."}, phone_id)
			self.assertEqual(repost_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(repost_events[0]["action"], "repost")

			like_events = _run_command(runtime, actor_id, "LikeSocialPost", {"slot": 0}, phone_id)
			self.assertEqual(like_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(like_events[0]["action"], "like")

			create_events = _run_command(
				runtime,
				actor_id,
				"CreateSocialPost",
				{"text": "Inspector created rumor-spread post.", "tags": ["inspection", "smoke"]},
				phone_id,
			)
			self.assertEqual(create_events[0]["type"], "SocialPostCreated")
			self.assertIn("Inspector created", create_events[0]["text"])

	def test_seed_post_generator_expands_text_rows(self) -> None:
		posts = build_seed_posts(
			{
				"post_generators": [
					{
						"author_id": "acc_teacher",
						"post_id_prefix": "post_notice",
						"tags": ["school"],
						"texts": ["A", "B"],
					}
				]
			}
		)

		self.assertEqual([x["post_id"] for x in posts], ["post_notice_001", "post_notice_002"])
		self.assertEqual(posts[0]["tags"], ["school"])

	def test_seed_can_be_applied_twice_without_duplicate_post_failure(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			rt = SQLiteSocialPlatformRuntime(Path(td) / "social.sqlite3", runtime_id="social")
			seed = {
				"accounts": [
					{"account_id": "acc_teacher", "display_name": "Teacher"},
				],
				"posts": [
					{
						"account_id": "acc_teacher",
						"post_id": "post_001",
						"text": "Remember the water bottle.",
						"tags": ["notice"],
					}
				],
			}

			seed_social_platform_runtime(rt, seed)
			seed_social_platform_runtime(rt, seed)
			events = rt.invoke("observe_feed", {"account_id": "acc_teacher", "limit": 5}, {})

			self.assertEqual([x["post_id"] for x in events[0]["items"]], ["post_001"])


if __name__ == "__main__":
	unittest.main()
