from __future__ import annotations

import json
import unittest
from pathlib import Path

from KERN.component_catalog import build_core_component_catalog
from KERN.effects import build_core_effect_catalog


class SocialRemovalContractTests(unittest.TestCase):
	def test_core_catalogs_do_not_expose_social_platform_definitions(self) -> None:
		effect_ids = set(build_core_effect_catalog().effect_ids())
		component_ids = set(build_core_component_catalog().component_ids())

		self.assertTrue(effect_ids.isdisjoint({
			"ObserveSocialFeed",
			"ObserveSocialPost",
			"CreateSocialPost",
			"InteractSocialPost",
			"FollowSocialAccount",
		}))
		self.assertNotIn("ScreenComponent", component_ids)

	def test_preserved_su7_research_data_keeps_agents_posts_and_relationships(self) -> None:
		data_root = Path(__file__).resolve().parents[1] / "research_data" / "su7_social_platform_legacy"
		preserved = {
			name: json.loads((data_root / name).read_text(encoding="utf-8"))
			for name in (
				"profiles.json",
				"social_seed.json",
				"World.json",
				"generated_agents.json",
				"scenario_meta.json",
			)
		}
		profiles = preserved["profiles.json"]
		seed = preserved["social_seed.json"]
		world = preserved["World.json"]

		self.assertEqual(len(profiles["profiles"]), 100)
		self.assertEqual(len(profiles["profile_accounts"]), 100)
		self.assertEqual(len(seed["accounts"]), 111)
		self.assertEqual(len(seed["posts"]), 14)
		self.assertEqual(len(seed["follows"]), 1900)
		self.assertEqual(len(world["entities"]), 100)
		self.assertEqual(len(world["locations"][0]["entities"]), 100)
		self.assertIn("SU7GeneratedAgent", preserved["generated_agents.json"])
		self.assertIn("generated_files", preserved["scenario_meta.json"])


if __name__ == "__main__":
	unittest.main()
