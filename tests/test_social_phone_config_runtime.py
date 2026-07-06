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
