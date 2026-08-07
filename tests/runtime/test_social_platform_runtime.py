from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes.social_platform import SQLiteSocialPlatform


def _seed() -> dict:
	return {
		"accounts": [
			{"account_id": "reader", "display_name": "Reader", "interests": {"risk": 1.0}},
			{"account_id": "author", "display_name": "Author", "interests": {"risk": 1.0}},
		],
		"posts": [
			{"account_id": "author", "post_id": "risk_post", "text": "Risk information", "tags": ["risk"], "tick": 0}
		],
		"follows": [{"follower_id": "reader", "followee_id": "author", "tick": 0}],
	}


class SQLiteSocialPlatformTests(unittest.TestCase):
	def test_recommendation_exposure_and_repost_are_independent_of_kern(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite", checkpoint_dir=Path(temp_dir) / "snapshots")
			platform.seed(_seed())

			feed = platform.recommend_feed("reader", tick=0, limit=5)
			self.assertEqual([item["post_id"] for item in feed], ["risk_post"])
			with self.assertRaisesRegex(ValueError, "not exposed"):
				platform.repost("reader", "risk_post", tick=0)

			platform.record_exposure("reader", "risk_post", tick=0, source="followed_author", score=1.0, position=0)
			repost = platform.repost("reader", "risk_post", tick=0)
			self.assertEqual(repost["account_id"], "reader")
			self.assertEqual(platform.metrics()["cumulative_reposts"], 1)

	def test_checkpoint_restores_platform_state(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite", checkpoint_dir=Path(temp_dir) / "snapshots")
			platform.seed(_seed())
			platform.record_exposure("reader", "risk_post", tick=0, source="followed_author", score=1.0, position=0)
			platform.save_checkpoint("run_01", tick=0)
			platform.repost("reader", "risk_post", tick=1)

			platform.restore_checkpoint("run_01", tick=0)
			self.assertEqual(platform.metrics()["cumulative_reposts"], 0)

	def test_legacy_su7_seed_is_complete_for_the_runtime_contract(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed_from_file(project_root / "research_data" / "su7_social_platform_legacy" / "social_seed.json")

			self.assertEqual(platform.counts(), {"accounts": 111, "posts": 14, "follows": 1900, "exposures": 0, "reposts": 0})


if __name__ == "__main__":
	unittest.main()
