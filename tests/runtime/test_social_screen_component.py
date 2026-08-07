from __future__ import annotations

import unittest
from pathlib import Path

from KERN.data.archive import archive_state_from_world_state
from KERN.data.builder import build_world_state
from KERN.package import load_packages_from_config


class SocialScreenComponentTests(unittest.TestCase):
	def test_selected_package_registers_screen_component_and_round_trips_state(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		loaded = load_packages_from_config(
			project_root,
			project_root / "runtime_config.social_propagation.empty.smoke.json",
		)
		catalog = loaded.component_catalog
		component_id = "social_propagation:ScreenComponent"
		raw = {
			"runtime_id": "social_platform",
			"account_id": "account_007",
			"app": "social_platform",
			"view": "feed",
			"title": "推荐",
			"feed_items": [
				{
					"slot": 0,
					"post_id": "post_001",
					"source_kind": "followed_repost",
					"source_account_id": "account_003",
				}
			],
			"current_post": None,
			"selected_post_id": "post_001",
			"cursor": 8,
			"updated_tick": 4,
			"status_text": "",
			"last_event_type": "SocialFeedRecommended",
			"last_error": "",
		}

		self.assertTrue(catalog.contains(component_id))
		component = catalog.build(component_id, raw)
		serialized = catalog.serialize(component_id, component)
		rebuilt = catalog.build(component_id, serialized)

		self.assertEqual(type(component).__name__, "ScreenComponent")
		self.assertEqual(serialized, raw)
		self.assertEqual(catalog.serialize(component_id, rebuilt), raw)

	def test_runtime_and_account_bindings_are_required(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		catalog = load_packages_from_config(
			project_root,
			project_root / "runtime_config.social_propagation.empty.smoke.json",
		).component_catalog

		with self.assertRaisesRegex(TypeError, "runtime_id.*account_id"):
			catalog.build("social_propagation:ScreenComponent", {})

	def test_phone_screen_survives_world_build_and_archive_round_trip(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		catalog = load_packages_from_config(
			project_root,
			project_root / "runtime_config.social_propagation.empty.smoke.json",
		).component_catalog
		templates = {
			"SocialPhone": {
				"name": "Social Phone",
				"components": {
					"TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
					"social_propagation:ScreenComponent": {
						"runtime_id": "social_platform",
						"account_id": "account_007",
					},
				},
			}
		}
		world = {
			"world_state": {"current_tick": 4},
			"locations": [
				{
					"location_id": "room",
					"location_name": "Room",
					"entities": [
						{
							"instance_id": "phone_007",
							"template_id": "SocialPhone",
							"component_overrides": {
								"social_propagation:ScreenComponent": {
									"view": "post",
									"current_post": {"post_id": "post_001", "text": "visible"},
									"selected_post_id": "post_001",
									"updated_tick": 4,
								}
							},
						}
					],
				}
			],
			"paths": [],
		}

		built = build_world_state(world, templates, {}, component_catalog=catalog).world_state
		archived = archive_state_from_world_state(built, component_catalog=catalog)
		rebuilt = build_world_state(archived, templates, {}, component_catalog=catalog).world_state
		screen = rebuilt.get_entity_by_id("phone_007").get_component("social_propagation:ScreenComponent")

		self.assertEqual(screen.runtime_id, "social_platform")
		self.assertEqual(screen.account_id, "account_007")
		self.assertEqual(screen.view, "post")
		self.assertEqual(screen.current_post["post_id"], "post_001")
		self.assertEqual(screen.updated_tick, 4)


if __name__ == "__main__":
	unittest.main()
