from __future__ import annotations

import json
import unittest
from pathlib import Path

from KERN.data.builder import build_world_state
from KERN.external_runtimes.social_platform import SQLiteSocialPlatform
from KERN.package import load_packages_from_config
from tools.generate_sea_level_social_experiment import (
	_sha256,
	generate_activation_schedule,
	generate_network,
	load_study_config,
	project_interests,
)
from tools.generate_sea_level_background_posts import (
	POST_COUNT,
	build_background_catalog,
	build_source_cards,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "Packages" / "SeaLevelSocialExperiment"


def _read(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def _synthetic_profiles(count: int) -> list[dict]:
	profiles = []
	for index in range(1, count + 1):
		profiles.append(
			{
				"profile_id": f"profile_{index:03d}",
				"personality": {
					"openness": (index % 10) / 10,
					"conscientiousness": 0.6,
					"extraversion": ((index * 3) % 10) / 10,
					"agreeableness": 0.5,
					"neuroticism": 0.4,
				},
				"demographics": {"lifecycle_stage": "early_career" if index % 2 else "mid_career"},
				"interests": {
					"science_topics": [{"id": "climate_risk"}] if index % 3 else [],
					"practical": [{"id": "reading"}],
					"aspirational": [{"id": "career_learning"}],
				},
			}
		)
	return profiles


class SeaLevelSocialExperimentGenerationTests(unittest.TestCase):
	def test_generated_world_has_valid_one_to_one_identity_phone_and_account_bindings(self) -> None:
		loaded = load_packages_from_config(ROOT, ROOT / "runtime_config.sea_level.consequence.json")
		world = loaded.data_bundle.world
		self.assertEqual(len(world["locations"]), 300)
		self.assertEqual(len(world["entities"]), 300)
		built = build_world_state(
			world,
			loaded.data_bundle.entity_templates,
			loaded.data_bundle.recipes,
			component_catalog=loaded.component_catalog,
		).world_state
		self.assertEqual(len(built.entities), 600)
		profile_ids: set[str] = set()
		for index in range(1, 301):
			agent = built.get_entity_by_id(f"agent_{index:03d}")
			phone = built.get_entity_by_id(f"phone_{index:03d}")
			identity = agent.get_component("sea_level_social_experiment:SocialIdentityComponent")
			screen = phone.get_component("social_propagation:ScreenComponent")
			self.assertIn("我", identity.natural_language_background)
			self.assertEqual(set(identity.big_five), {"openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"})
			self.assertTrue(all(0 <= value <= 1 for value in identity.big_five.values()))
			self.assertEqual(screen.account_id, f"account_{index:03d}")
			self.assertIn(phone.entity_id, agent.get_component("ContainerComponent").get_all_item_ids())
			profile_ids.add(identity.profile_id)
		self.assertEqual(len(profile_ids), 300)

	def test_paired_platform_seeds_share_everything_except_experimental_treatment(self) -> None:
		consequence = _read(PACKAGE_ROOT / "Data" / "Platform" / "social_seed.sea_level_consequence_focus.json")
		solution = _read(PACKAGE_ROOT / "Data" / "Platform" / "social_seed.sea_level_solution_focus.json")
		self.assertEqual(consequence["accounts"], solution["accounts"])
		self.assertEqual(consequence["follows"], solution["follows"])
		self.assertEqual(consequence["posts"][:-1], solution["posts"][:-1])
		left, right = consequence["posts"][-1], solution["posts"][-1]
		self.assertEqual(left["post_id"], right["post_id"])
		self.assertEqual(left["ranking_topics"], ["climate_risk", "sea_level"])
		self.assertEqual(left["ranking_topics"], right["ranking_topics"])
		self.assertNotEqual(left["condition_id"], right["condition_id"])
		self.assertNotEqual(left["text"], right["text"])
		self.assertNotEqual(left["display_hashtags"], right["display_hashtags"])
		self.assertEqual(len(consequence["accounts"]), 341)
		self.assertEqual(len(consequence["posts"]), 201)
		self.assertEqual(sum(row["followee_id"] == "earth_voice" for row in consequence["follows"]), 24)

	def test_generated_seeds_are_accepted_by_social_platform_v3(self) -> None:
		import tempfile

		for condition in ("sea_level_consequence_focus", "sea_level_solution_focus"):
			with self.subTest(condition=condition), tempfile.TemporaryDirectory() as temp_dir:
				platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
				platform.seed_from_file(PACKAGE_ROOT / "Data" / "Platform" / f"social_seed.{condition}.json")
				self.assertEqual(platform.counts()["accounts"], 341)
				self.assertEqual(platform.counts()["posts"], 201)
				self.assertEqual(platform.counts()["follows"], 6095)
				platform.close()

	def test_background_post_source_cards_are_deterministic_and_mixed(self) -> None:
		profile_cards = [
			{
				"profile_id": f"social_profile_{index:03d}",
				"agent_id": f"agent_{index:03d}",
				"natural_language_background_excerpt": "我是一个普通用户，生活里有工作、家庭和兴趣。",
				"big_five": {"openness": 0.6, "conscientiousness": 0.6, "extraversion": 0.4, "agreeableness": 0.5, "neuroticism": 0.4},
			}
			for index in range(1, 301)
		]

		left = build_source_cards(seed="unit-test", profile_cards=profile_cards)
		right = build_source_cards(seed="unit-test", profile_cards=profile_cards)

		self.assertEqual(left, right)
		self.assertEqual(len(left["publishers"]), 40)
		self.assertEqual(len(left["source_cards"]), POST_COUNT)
		self.assertEqual(left["generation"]["bucket_counts"], {
			"interest_hobby": 70,
			"everyday_life": 55,
			"community_public": 35,
			"light_public_issue": 25,
			"loose_social": 15,
		})
		self.assertTrue(all(card["author_basis"]["kind"] == "profile_inspired_background_user" for card in left["source_cards"]))
		posts = [
			{
				"post_id": card["post_id"],
				"account_id": card["account_id"],
				"text": "这是一条用于测试的普通背景帖，围绕日常生活里的具体小事展开，语气平实，没有传播动员，也不讨论海平面。",
				"ranking_topics": card["ranking_topics"],
				"display_hashtags": card["display_hashtags"],
			}
			for card in left["source_cards"]
		]
		catalog = build_background_catalog(left["publishers"], posts, left)
		self.assertEqual(catalog["schema_version"], "social_background_posts.v1")
		self.assertEqual(len(catalog["posts"]), POST_COUNT)

	def test_activation_schedule_is_bounded_complete_and_fingerprinted(self) -> None:
		schedule = _read(PACKAGE_ROOT / "Data" / "Study" / "activation_schedule.json")
		fingerprint = schedule.pop("fingerprint")
		self.assertEqual(fingerprint, _sha256(schedule))
		self.assertEqual(schedule["tick_count"], 100)
		self.assertEqual(len(schedule["agents"]), 300)
		self.assertEqual(set(schedule["active_by_tick"]), {str(tick) for tick in range(1, 101)})
		self.assertLessEqual(max(map(len, schedule["active_by_tick"].values())), 60)
		self.assertAlmostEqual(schedule["summary"]["mean_active_fraction"], 0.12, delta=0.01)

	def test_interest_network_and_activation_algorithms_are_deterministic(self) -> None:
		config = load_study_config(PACKAGE_ROOT / "Study" / "study_config.v1.json")
		profiles = _synthetic_profiles(30)
		left_network = generate_network(profiles, config)
		right_network = generate_network(profiles, config)
		self.assertEqual(left_network, right_network)
		left_schedule = generate_activation_schedule(profiles, config)
		right_schedule = generate_activation_schedule(profiles, config)
		self.assertEqual(left_schedule, right_schedule)
		projection, provenance = project_interests(profiles[0], config["interest_mapping"]["weights"])
		self.assertEqual(projection["climate_risk"], 1.0)
		self.assertEqual(projection["sea_level"], 1.0)
		self.assertEqual(projection["reading"], 0.7)
		self.assertEqual(projection["career_learning"], 0.45)
		self.assertTrue(all(row["mapping_version"] == "social_interest_mapping.v1" for row in provenance))


if __name__ == "__main__":
	unittest.main()
