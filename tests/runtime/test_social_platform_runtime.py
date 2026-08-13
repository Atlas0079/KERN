from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes.social_platform import SQLiteSocialPlatform


def _post(
	post_id: str,
	*,
	author: str = "author",
	tick: int = 0,
	condition_id: str = "background",
	ranking_topics: list[str] | None = None,
	display_hashtags: list[str] | None = None,
) -> dict:
	return {
		"account_id": author,
		"post_id": post_id,
		"text": f"Risk information {post_id}",
		"ranking_topics": list(ranking_topics or ["risk"]),
		"display_hashtags": list(display_hashtags or ["风险信息"]),
		"condition_id": condition_id,
		"tick": tick,
	}


def _seed() -> dict:
	return {
		"accounts": [
			{"account_id": "reader", "display_name": "Reader", "interests": {"risk": 1.0}},
			{"account_id": "author", "display_name": "Author", "interests": {"risk": 1.0}},
		],
		"posts": [_post("risk_post", condition_id="sea_level_consequence_focus")],
		"follows": [{"follower_id": "reader", "followee_id": "author", "tick": 0}],
	}


def _propagation_seed() -> dict:
	accounts = [
		{"account_id": account_id, "display_name": account_id, "interests": {"risk": 1.0}}
		for account_id in ("author", "a", "b", "c")
	]
	return {
		"accounts": accounts,
		"posts": [_post(f"post_{index:02d}") for index in range(10)],
		"follows": [
			{"follower_id": "a", "followee_id": "author", "tick": 0},
			{"follower_id": "b", "followee_id": "a", "tick": 0},
			{"follower_id": "c", "followee_id": "b", "tick": 0},
		],
	}


def _open(platform: SQLiteSocialPlatform, account_id: str, *, tick: int, transaction_id: str = "", limit: int = 8) -> dict:
	return platform.open_feed_session(account_id, tick=tick, limit=limit, transaction_id=transaction_id)


def _card(session: dict, post_id: str) -> dict:
	return next(item for item in session["feed_items"] if item["post_id"] == post_id)


def _empty_metrics() -> dict[str, int]:
	return {
		"cumulative_feed_sessions": 0,
		"cumulative_exposures": 0,
		"cumulative_reposts": 0,
		"cumulative_likes": 0,
		"cumulative_comments": 0,
	}


class SQLiteSocialPlatformTests(unittest.TestCase):
	def test_recommendation_is_read_only_and_post_contract_separates_topics_from_hashtags(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())

			feed = platform.recommend_feed("reader", tick=0, limit=5)

			self.assertEqual([item["post_id"] for item in feed], ["risk_post"])
			self.assertEqual(feed[0]["display_hashtags"], ["风险信息"])
			self.assertNotIn("ranking_topics", feed[0])
			self.assertNotIn("condition_id", feed[0])
			self.assertEqual(platform.metrics(), _empty_metrics())

	def test_old_tags_post_contract_is_rejected(self) -> None:
		seed = _seed()
		seed["posts"] = [{"account_id": "author", "post_id": "old", "text": "old", "tags": ["risk"], "tick": 0}]
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			with self.assertRaisesRegex(ValueError, "ranking_topics"):
				platform.seed(seed)

	def test_open_feed_session_records_page_and_exposures_atomically(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())

			session = _open(platform, "reader", tick=0)
			stored = platform.feed_session_for("reader", 0)

			self.assertEqual(session, stored)
			self.assertEqual(session["feed_session_id"], 1)
			self.assertEqual(_card(session, "risk_post")["feed_session_id"], 1)
			self.assertEqual(platform.metrics()["cumulative_feed_sessions"], 1)
			self.assertEqual(platform.metrics()["cumulative_exposures"], 1)
			self.assertEqual(platform.exposure_records("reader")[0]["feed_session_id"], 1)

	def test_empty_page_still_records_feed_session(self) -> None:
		seed = _seed()
		seed["posts"] = []
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(seed)

			session = _open(platform, "reader", tick=0)

			self.assertEqual(session["feed_items"], [])
			self.assertEqual(len(platform.feed_session_records("reader")), 1)
			self.assertEqual(platform.metrics()["cumulative_exposures"], 0)

	def test_interactions_reference_the_exact_source_exposure(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			card = _card(_open(platform, "reader", tick=0), "risk_post")

			liked = platform.like("reader", "risk_post", source_exposure_id=card["exposure_id"], tick=0)
			commented = platform.comment("reader", "risk_post", source_exposure_id=card["exposure_id"], text="I care", tick=0)
			reposted = platform.repost("reader", "risk_post", source_exposure_id=card["exposure_id"], text="share", tick=0)

			self.assertEqual(liked["source_exposure_id"], card["exposure_id"])
			self.assertEqual(commented["source_exposure_id"], card["exposure_id"])
			self.assertEqual(reposted["source_exposure_id"], card["exposure_id"])
			self.assertEqual(platform.like_records("reader")[0]["source_exposure_id"], card["exposure_id"])
			self.assertEqual(platform.repost_records("reader")[0]["source_exposure_id"], card["exposure_id"])
			self.assertEqual(platform.comment_records("risk_post")[0]["source_exposure_id"], card["exposure_id"])

	def test_interaction_rejects_an_exposure_from_another_tick(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			card = _card(_open(platform, "reader", tick=0), "risk_post")

			with self.assertRaisesRegex(ValueError, "does not match"):
				platform.like("reader", "risk_post", source_exposure_id=card["exposure_id"], tick=1)

	def test_viewer_state_is_present_on_later_pages(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			first = _card(_open(platform, "reader", tick=0), "risk_post")
			platform.like("reader", "risk_post", source_exposure_id=first["exposure_id"], tick=0)
			platform.repost("reader", "risk_post", source_exposure_id=first["exposure_id"], tick=0)

			second = _card(_open(platform, "reader", tick=1), "risk_post")

			self.assertTrue(second["viewer_has_liked"])
			self.assertTrue(second["viewer_has_reposted"])
			self.assertEqual(second["like_count"], 1)
			self.assertEqual(second["repost_count"], 1)

	def test_followed_repost_appears_only_on_the_next_tick_and_can_propagate(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_propagation_seed())
			a_card = _card(_open(platform, "a", tick=0), "post_00")
			platform.repost("a", "post_00", source_exposure_id=a_card["exposure_id"], tick=0)

			same_tick = platform.recommend_feed("b", tick=0, limit=8)
			next_tick = platform.recommend_feed("b", tick=1, limit=8)
			card_from_a = next(item for item in next_tick if item["post_id"] == "post_00")

			self.assertNotEqual(next(item for item in same_tick if item["post_id"] == "post_00")["feed_item_kind"], "repost")
			self.assertEqual(card_from_a["feed_item_kind"], "repost")
			self.assertEqual(card_from_a["reposted_by_account_id"], "a")
			self.assertEqual(card_from_a["source_account_id"], "a")
			b_card = _card(_open(platform, "b", tick=1), "post_00")
			platform.repost("b", "post_00", source_exposure_id=b_card["exposure_id"], tick=1)
			self.assertEqual(next(item for item in platform.recommend_feed("c", tick=2, limit=8) if item["post_id"] == "post_00")["reposted_by_account_id"], "b")

	def test_feed_limits_sections_and_deduplicates_posts(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			seed = _propagation_seed()
			for index in range(4):
				reposter = f"reposter_{index}"
				seed["accounts"].append({"account_id": reposter, "display_name": reposter, "interests": {"risk": 1.0}})
				seed["follows"].append({"follower_id": "b", "followee_id": reposter, "tick": 0})
			platform.seed(seed)
			for index in range(4):
				reposter = f"reposter_{index}"
				post_id = f"post_{index:02d}"
				card = _card(_open(platform, reposter, tick=0), post_id)
				platform.repost(reposter, post_id, source_exposure_id=card["exposure_id"], tick=0)

			feed = platform.recommend_feed("b", tick=1, limit=20)

			self.assertLessEqual(len(feed), 8)
			self.assertLessEqual(sum(item["section"] == "reposts" for item in feed), 3)
			self.assertEqual(len({item["post_id"] for item in feed}), len(feed))
			self.assertEqual([item["position"] for item in feed], list(range(len(feed))))

	def test_hybrid_recommender_mixes_reposts_interest_hot_and_exploration_deterministically(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			seed = {
				"accounts": [
					{"account_id": "reader", "display_name": "Reader", "interests": {"risk": 1.0}},
					{"account_id": "friend", "display_name": "Friend", "interests": {"risk": 1.0}},
					{"account_id": "interest_author", "display_name": "Interest", "interests": {"risk": 1.0}},
					{"account_id": "hot_author", "display_name": "Hot", "interests": {"culture": 1.0}},
					*[
						{"account_id": f"explore_author_{index}", "display_name": f"Explore {index}", "interests": {"daily": 1.0}}
						for index in range(4)
					],
					*[
						{"account_id": f"booster_{index}", "display_name": f"Booster {index}", "interests": {"culture": 1.0}}
						for index in range(4)
					],
				],
				"posts": [
					_post("interest_0", author="interest_author", ranking_topics=["risk"]),
					_post("interest_1", author="interest_author", ranking_topics=["risk"]),
					_post("repost_target", author="interest_author", ranking_topics=["risk"]),
					_post("hot_post", author="hot_author", ranking_topics=["culture"], display_hashtags=["文化"]),
					*[
						_post(f"explore_{index}", author=f"explore_author_{index}", ranking_topics=["daily"], display_hashtags=["日常"])
						for index in range(4)
					],
				],
				"follows": [{"follower_id": "reader", "followee_id": "friend", "tick": 0}],
			}
			platform.seed(seed)
			friend_card = _card(_open(platform, "friend", tick=0), "repost_target")
			platform.repost("friend", "repost_target", source_exposure_id=friend_card["exposure_id"], tick=0)
			for index in range(4):
				hot_card = _card(_open(platform, f"booster_{index}", tick=0), "hot_post")
				platform.like(f"booster_{index}", "hot_post", source_exposure_id=hot_card["exposure_id"], tick=0)
				if index < 2:
					platform.comment(f"booster_{index}", "hot_post", source_exposure_id=hot_card["exposure_id"], text="worth reading", tick=0)
					platform.repost(f"booster_{index}", "hot_post", source_exposure_id=hot_card["exposure_id"], tick=0)

			first = platform.recommend_feed("reader", tick=1, limit=8)
			second = platform.recommend_feed("reader", tick=1, limit=8)
			post_ids = [item["post_id"] for item in first]

			self.assertEqual(post_ids, [item["post_id"] for item in second])
			self.assertEqual(len(post_ids), len(set(post_ids)))
			self.assertTrue(any(item["feed_item_kind"] == "repost" and item["post_id"] == "repost_target" for item in first))
			self.assertTrue(any(post_id.startswith("interest_") for post_id in post_ids))
			self.assertIn("hot_post", post_ids)
			self.assertTrue(any(post_id.startswith("explore_") for post_id in post_ids))
			self.assertFalse(any(key.startswith("_") for item in first for key in item))

	def test_platform_can_use_a_custom_recommender_strategy(self) -> None:
		class FirstOriginalRecommender:
			def select_page(self, context: object, *, original_cards: list[dict], repost_cards: list[dict]) -> list[dict]:
				return original_cards[:1]

		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite", recommender=FirstOriginalRecommender())
			seed = _seed()
			seed["posts"].append(_post("second_post"))
			platform.seed(seed)

			feed = platform.recommend_feed("reader", tick=0, limit=8)

			self.assertEqual([item["post_id"] for item in feed], ["risk_post"])

	def test_previously_exposed_post_scores_zero_and_sessions_preserve_repeated_exposures(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			_open(platform, "reader", tick=0)

			same_tick = platform.recommend_feed("reader", tick=0, limit=5)[0]
			later = platform.recommend_feed("reader", tick=1, limit=5)[0]
			_open(platform, "reader", tick=1)

			self.assertFalse(same_tick["previously_exposed"])
			self.assertTrue(later["previously_exposed"])
			self.assertEqual(later["score"], 0.0)
			self.assertEqual(len(platform.exposure_records("reader")), 2)

	def test_transaction_rollback_removes_session_exposures_and_interactions(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			platform.begin_transaction("tx")
			session = _open(platform, "reader", tick=0, transaction_id="tx")
			card = _card(session, "risk_post")
			platform.like("reader", "risk_post", source_exposure_id=card["exposure_id"], tick=0, transaction_id="tx")
			platform.comment("reader", "risk_post", source_exposure_id=card["exposure_id"], text="rollback", tick=0, transaction_id="tx")
			platform.repost("reader", "risk_post", source_exposure_id=card["exposure_id"], tick=0, transaction_id="tx")

			platform.rollback_transaction("tx")

			self.assertEqual(platform.metrics(), _empty_metrics())

	def test_transaction_id_and_checkpoint_boundaries_are_strict(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite")
			platform.seed(_seed())
			platform.begin_transaction("tx_01")
			with self.assertRaisesRegex(ValueError, "transaction_id does not match"):
				_open(platform, "reader", tick=0, transaction_id="tx_wrong")
			with self.assertRaisesRegex(RuntimeError, "active transaction"):
				platform.save_checkpoint("run_01", tick=0)
			platform.rollback_transaction("tx_01")

	def test_checkpoint_restores_platform_state(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			platform = SQLiteSocialPlatform(Path(temp_dir) / "platform.sqlite", checkpoint_dir=Path(temp_dir) / "snapshots")
			platform.seed(_seed())
			_open(platform, "reader", tick=0)
			platform.save_checkpoint("run_01", tick=0)
			_open(platform, "reader", tick=1)

			platform.restore_checkpoint("run_01", tick=0)

			self.assertEqual(platform.metrics()["cumulative_feed_sessions"], 1)

	def test_old_database_schema_is_rejected_instead_of_migrated(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			database_path = Path(temp_dir) / "old.sqlite"
			connection = sqlite3.connect(database_path)
			try:
				connection.execute("CREATE TABLE accounts(account_id TEXT PRIMARY KEY)")
				connection.commit()
			finally:
				connection.close()
			with self.assertRaisesRegex(ValueError, "delete and regenerate"):
				SQLiteSocialPlatform(database_path)

	def test_previous_versioned_database_is_rejected_before_schema_creation(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			database_path = Path(temp_dir) / "v2.sqlite"
			connection = sqlite3.connect(database_path)
			try:
				connection.execute("CREATE TABLE platform_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
				connection.execute("INSERT INTO platform_meta(key, value) VALUES('schema_version', 'social_platform.v2')")
				connection.commit()
			finally:
				connection.close()

			with self.assertRaisesRegex(ValueError, "delete and regenerate"):
				SQLiteSocialPlatform(database_path)

			connection = sqlite3.connect(database_path)
			try:
				tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
			finally:
				connection.close()
			self.assertEqual(tables, {"platform_meta"})


if __name__ == "__main__":
	unittest.main()
