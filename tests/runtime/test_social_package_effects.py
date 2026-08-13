from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.data.builder import build_world_state
from KERN.execution_errors import KernFailure
from KERN.executor.executor import WorldExecutor
from KERN.external_runtime import ExternalRuntimeBridge
from KERN.package import load_packages_from_config


class SocialPackageEffectTests(unittest.TestCase):
	def _runtime_parts(self, temp_dir: str):
		project_root = Path(__file__).resolve().parents[2]
		loaded = load_packages_from_config(project_root, project_root / "runtime_config.social_propagation.empty.smoke.json")
		seed_path = Path(temp_dir) / "seed.json"
		seed_path.write_text(
			json.dumps(
				{
					"accounts": [
						{"account_id": "reader", "display_name": "Reader", "interests": {"risk": 1.0}},
						{"account_id": "author", "display_name": "Author", "interests": {"risk": 1.0}},
					],
					"posts": [{
						"account_id": "author",
						"post_id": "risk_post",
						"text": "Risk information",
						"ranking_topics": ["risk"],
						"display_hashtags": ["风险信息"],
						"condition_id": "background",
						"tick": 0,
					}],
					"follows": [{"follower_id": "reader", "followee_id": "author", "tick": 0}],
				},
				ensure_ascii=False,
			),
			encoding="utf-8",
		)
		provider = loaded.external_runtime_catalog.require("social_propagation:sqlite_platform")
		adapter = provider.factory(
			{
				"project_root": str(project_root),
				"runtime_id": "social_platform",
				"checkpoint_dir": str(Path(temp_dir) / "checkpoints"),
				"restore_path": "",
			},
			{"database_path": str(Path(temp_dir) / "platform.sqlite"), "seed_path": str(seed_path)},
		)
		adapter.start({})
		templates = {
			"Agent": {
				"name": "Agent",
				"components": {
					"ContainerComponent": {"slots": {"inventory": {"capacity_count": 4, "accepted_tags": []}}},
					"PerceptionComponent": {},
				}
			},
			"Phone": {
				"name": "Phone",
				"components": {
					"TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
					"social_propagation:ScreenComponent": {"runtime_id": "social_platform", "account_id": "reader"},
				},
			},
		}
		world = {
			"world_state": {"current_tick": 0},
			"locations": [{"location_id": "room", "location_name": "Room", "entities": [{"template_id": "Agent", "instance_id": "agent"}]}],
			"entities": [{"template_id": "Phone", "instance_id": "phone", "parent_container": "agent"}],
			"paths": [],
		}
		ws = build_world_state(world, templates, {}, component_catalog=loaded.component_catalog).world_state
		ws.services = {"external_runtime_bridge": ExternalRuntimeBridge({"social_platform": adapter})}
		executor = WorldExecutor(entity_templates=templates, effect_catalog=loaded.effect_catalog, component_catalog=loaded.component_catalog)
		return loaded, adapter, ws, executor

	@staticmethod
	def _effect(name: str, **values):
		return {"effect": f"social_propagation:{name}", "terminal": "target", **values}

	@staticmethod
	def _record_bundle(effect: dict):
		return {"effects": [effect], "record": {"mode": "auto", "target": "self"}}

	def test_package_registers_effects_recipes_and_executes_all_visible_interactions(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			loaded, adapter, ws, executor = self._runtime_parts(temp_dir)
			self.assertTrue({
				"social_propagation:RefreshFeed",
				"social_propagation:RepostVisiblePost",
				"social_propagation:LikeVisiblePost",
				"social_propagation:CommentOnVisiblePost",
				"social_propagation:ObserveMetrics",
			}.issubset(loaded.effect_catalog.effect_ids()))
			self.assertTrue({"social_browse_feed", "social_repost_visible_post", "social_like_visible_post", "social_comment_visible_post"}.issubset(loaded.data_bundle.recipes))

			context = {"self_id": "agent", "target_id": "phone"}
			executor.execute_bundle(ws, self._record_bundle(self._effect("RefreshFeed", limit=8)), context)
			screen = ws.get_entity_by_id("phone").get_component("social_propagation:ScreenComponent")
			perception = ws.get_entity_by_id("agent").get_component("PerceptionComponent")
			self.assertEqual([item["post_id"] for item in screen.feed_items], ["risk_post"])
			self.assertNotIn("score", screen.feed_items[0])
			self.assertNotIn("ranking_topics", screen.feed_items[0])
			self.assertNotIn("condition_id", screen.feed_items[0])
			self.assertEqual(screen.feed_items[0]["display_hashtags"], ["风险信息"])
			self.assertIn("exposure_id", screen.feed_items[0])
			self.assertEqual(screen.feed_items[0]["feed_session_id"], screen.feed_session_id)
			self.assertEqual(len(perception.record_inbox), 1)
			self.assertEqual(perception.record_inbox[0]["record_type"], "social_feed_view")
			self.assertIn("feed_session_id", perception.record_inbox[0]["content"])

			executor.execute_bundle(ws, self._record_bundle(self._effect("LikeVisiblePost", post_id="risk_post")), context)
			executor.execute_bundle(ws, self._record_bundle(self._effect("CommentOnVisiblePost", post_id="risk_post", text="值得关注")), context)
			executor.execute_bundle(ws, self._record_bundle(self._effect("RepostVisiblePost", post_id="risk_post", text="请扩散")), context)

			self.assertEqual(adapter.platform.metrics(), {
				"cumulative_feed_sessions": 1,
				"cumulative_exposures": 1,
				"cumulative_reposts": 1,
				"cumulative_likes": 1,
				"cumulative_comments": 1,
			})
			self.assertEqual(adapter.platform.comment_records("risk_post")[0]["text"], "值得关注")
			self.assertEqual(adapter.platform.like_records("reader")[0]["source_exposure_id"], screen.feed_items[0]["exposure_id"])
			self.assertTrue(screen.feed_items[0]["viewer_has_liked"])
			self.assertTrue(screen.feed_items[0]["viewer_has_reposted"])
			self.assertEqual([item["record_type"] for item in perception.record_inbox], ["social_feed_view", "social_action", "social_action", "social_action"])
			self.assertTrue(any("值得关注" in item["content"] for item in perception.record_inbox))
			self.assertTrue(any("请扩散" in item["content"] for item in perception.record_inbox))
			adapter.close({})

	def test_refresh_session_and_screen_roll_back_together(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			_loaded, adapter, ws, executor = self._runtime_parts(temp_dir)
			context = {"self_id": "agent", "target_id": "phone"}

			with self.assertRaises(KernFailure):
				executor.execute_bundle(
					ws,
					{"effects": [
						{**self._effect("RefreshFeed", limit=8)},
						{"effect": "ModifyProperty", "target": "self", "component": "MissingComponent", "property": "value", "value": 1},
					], "record": {"mode": "auto", "target": "self"}},
					context,
				)

			screen = ws.get_entity_by_id("phone").get_component("social_propagation:ScreenComponent")
			self.assertEqual(screen.view, "blank")
			self.assertEqual(screen.feed_session_id, 0)
			self.assertEqual(ws.get_entity_by_id("agent").get_component("PerceptionComponent").record_inbox, [])
			self.assertEqual(adapter.platform.metrics()["cumulative_feed_sessions"], 0)
			self.assertEqual(adapter.platform.metrics()["cumulative_exposures"], 0)
			adapter.close({})

	def test_external_and_screen_writes_roll_back_together(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			_loaded, adapter, ws, executor = self._runtime_parts(temp_dir)
			context = {"self_id": "agent", "target_id": "phone"}
			executor.execute_bundle(ws, {"effects": [self._effect("RefreshFeed", limit=8)]}, context)
			screen = ws.get_entity_by_id("phone").get_component("social_propagation:ScreenComponent")
			before_status = screen.status_text

			with self.assertRaises(KernFailure):
				executor.execute_bundle(
					ws,
					{"effects": [
						self._effect("CommentOnVisiblePost", post_id="risk_post", text="must roll back"),
						{"effect": "ModifyProperty", "target": "self", "component": "MissingComponent", "property": "value", "value": 1},
					]},
					context,
				)

			self.assertEqual(adapter.platform.metrics()["cumulative_comments"], 0)
			restored_screen = ws.get_entity_by_id("phone").get_component("social_propagation:ScreenComponent")
			self.assertEqual(restored_screen.status_text, before_status)
			adapter.close({})

	def test_interactions_reject_missing_or_stale_screen_posts(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			_loaded, adapter, ws, executor = self._runtime_parts(temp_dir)
			context = {"self_id": "agent", "target_id": "phone"}
			executor.execute_bundle(ws, {"effects": [self._effect("RefreshFeed", limit=8)]}, context)
			with self.assertRaisesRegex(KernFailure, "not visible"):
				executor.execute_bundle(ws, {"effects": [self._effect("LikeVisiblePost", post_id="not_on_page")]}, context)
			ws.game_time.total_ticks = 1
			with self.assertRaisesRegex(KernFailure, "stale"):
				executor.execute_bundle(ws, {"effects": [self._effect("CommentOnVisiblePost", post_id="risk_post", text="late")]}, context)
			self.assertEqual(adapter.platform.metrics()["cumulative_likes"], 0)
			self.assertEqual(adapter.platform.metrics()["cumulative_comments"], 0)
			adapter.close({})

	def test_adapter_restores_external_checkpoint_from_kern_restore_source(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			loaded, adapter, ws, executor = self._runtime_parts(temp_dir)
			context = {"self_id": "agent", "target_id": "phone"}
			executor.execute_bundle(ws, {"effects": [self._effect("RefreshFeed", limit=8)]}, context)
			executor.execute_bundle(ws, {"effects": [self._effect("LikeVisiblePost", post_id="risk_post")]}, context)
			source_root = Path(temp_dir) / "checkpoints"
			adapter.save_checkpoint({"run_id": "run_01", "tick": 0})
			adapter.close({})

			provider = loaded.external_runtime_catalog.require("social_propagation:sqlite_platform")
			restored = provider.factory(
				{
					"project_root": str(Path(__file__).resolve().parents[2]),
					"runtime_id": "social_platform",
					"checkpoint_dir": str(Path(temp_dir) / "restored_checkpoints"),
					"restore_path": str(source_root),
				},
				{
					"database_path": str(Path(temp_dir) / "restored.sqlite"),
					"seed_path": str(Path(temp_dir) / "seed.json"),
				},
			)
			restored.start({})
			restored.restore_checkpoint({"run_id": "run_01", "tick": 0})
			self.assertEqual(restored.platform.metrics()["cumulative_exposures"], 1)
			self.assertEqual(restored.platform.metrics()["cumulative_likes"], 1)
			restored.close({})


if __name__ == "__main__":
	unittest.main()
