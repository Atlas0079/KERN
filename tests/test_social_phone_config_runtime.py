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
		"runtime_config.social_phone.smoke.json",
		validate=True,
		configure_logging=False,
		overrides={
			"CHECKPOINT_EVERY_TICK": "0",
			"EXTERNAL_RUNTIMES_JSON": json.dumps(
				{
					"social": {
						"type": "sqlite_social_platform",
						"db_path": str(db_path),
						"reset_db": True,
						"seed_json": "Data/SocialPhone/social_seed.json",
					}
				}
			),
		},
	)


def _run_command(runtime: KernRuntime, verb: str, parameters: dict, target_id: str = "phone_01") -> list[dict]:
	ws = runtime.world_state
	cmd = runtime.interaction_engine.process_command(
		ws,
		"agent_01",
		{"verb": verb, "target_id": target_id, "parameters": dict(parameters or {})},
	)
	if cmd.get("status") != "success":
		raise AssertionError(f"{verb} command failed: {cmd}")
	return runtime.executor.execute_bundle(ws, cmd["bundle"], cmd["context"])


class SocialPhoneConfigRuntimeTests(unittest.TestCase):
	def test_config_declares_sqlite_social_runtime_and_seed_data(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")

			adapter = runtime.external_runtimes.get("social")
			self.assertIsInstance(adapter, SQLiteSocialPlatformRuntime)
			events = adapter.invoke("observe_feed", {"account_id": "acc_agent", "limit": 2, "tick": 1}, {})

			self.assertEqual(events[0]["type"], "SocialFeedObserved")
			self.assertGreaterEqual(len(events[0]["items"]), 1)
			self.assertIn("water bottle", events[0]["items"][0]["summary"])

	def test_social_phone_scene_recipes_update_phone_screen(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			ws.services["external_runtime_bridge"] = ExternalRuntimeBridge(runtime.external_runtimes)
			agent_inventory = ws.get_entity_by_id("agent_01").get_component("ContainerComponent").slots["inventory"].items
			self.assertIn("phone_01", agent_inventory)

			feed_cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_01",
				{"verb": "BrowseSocialFeed", "target_id": "phone_01", "parameters": {"limit": 1}},
			)
			self.assertEqual(feed_cmd["status"], "success")
			feed_events = runtime.executor.execute_bundle(ws, feed_cmd["bundle"], feed_cmd["context"])
			self.assertEqual(feed_events[0]["type"], "SocialFeedObserved")

			screen = ws.get_entity_by_id("phone_01").get_component("ScreenComponent")
			self.assertEqual(screen.view, "feed")
			self.assertEqual(len(screen.feed_items), 1)
			self.assertTrue(screen.feed_items[0]["post_id"].startswith("post_teacher_notice"))

			open_cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_01",
				{"verb": "OpenSocialPost", "target_id": "phone_01", "parameters": {"slot": 0}},
			)
			self.assertEqual(open_cmd["status"], "success")
			open_events = runtime.executor.execute_bundle(ws, open_cmd["bundle"], open_cmd["context"])

			self.assertEqual(open_events[0]["type"], "SocialPostObserved")
			self.assertEqual(screen.view, "post")
			self.assertEqual(screen.current_post["post_id"], screen.selected_post_id)

	def test_social_phone_recipes_require_carried_phone_target(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			agent = ws.get_entity_by_id("agent_01")
			container = agent.get_component("ContainerComponent")
			self.assertTrue(container.remove_entity_by_id("phone_01"))
			ws.get_location_by_id("social_test_room").add_entity_id("phone_01")

			cmd = runtime.interaction_engine.process_command(
				ws,
				"agent_01",
				{"verb": "BrowseSocialFeed", "target_id": "phone_01", "parameters": {"limit": 1}},
			)

			self.assertEqual(cmd["status"], "failed")
			self.assertEqual(cmd["reason"], "NO_RECIPE")

	def test_social_phone_scene_exposes_all_social_runtime_actions(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = _runtime_with_temp_social_db(Path(td) / "social.sqlite3")
			ws = runtime.world_state
			ws.services["external_runtime_bridge"] = ExternalRuntimeBridge(runtime.external_runtimes)

			feed_events = _run_command(runtime, "BrowseSocialFeed", {"limit": 3})
			self.assertEqual(feed_events[0]["type"], "SocialFeedObserved")

			open_events = _run_command(runtime, "OpenSocialPost", {"slot": 0})
			self.assertEqual(open_events[0]["type"], "SocialPostObserved")
			current_author = open_events[0]["post"]["author_id"]

			like_events = _run_command(runtime, "LikeSocialPost", {"slot": 0})
			self.assertEqual(like_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(like_events[0]["action"], "like")

			unlike_events = _run_command(runtime, "UnlikeSocialPost", {"slot": 0})
			self.assertEqual(unlike_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(unlike_events[0]["action"], "unlike")

			comment_events = _run_command(runtime, "CommentSocialPost", {"slot": 0, "text": "Inspector test comment."})
			self.assertEqual(comment_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(comment_events[0]["action"], "comment")

			repost_events = _run_command(runtime, "RepostSocialPost", {"slot": 0, "text": "Inspector test repost."})
			self.assertEqual(repost_events[0]["type"], "SocialPostInteracted")
			self.assertEqual(repost_events[0]["action"], "repost")

			follow_events = _run_command(runtime, "FollowSocialAccount", {"target_account_id": current_author})
			self.assertEqual(follow_events[0]["type"], "SocialAccountFollowed")
			self.assertEqual(follow_events[0]["target_account_id"], current_author)

			create_events = _run_command(
				runtime,
				"CreateSocialPost",
				{"text": "Inspector created post.", "tags": ["inspection", "smoke"]},
			)
			self.assertEqual(create_events[0]["type"], "SocialPostCreated")
			self.assertIn("Inspector created post.", create_events[0]["text"])

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
