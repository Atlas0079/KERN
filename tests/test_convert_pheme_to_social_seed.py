from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes import SQLiteSocialPlatformRuntime
from KERN.external_runtimes.social_seed import seed_social_platform_runtime
from tools.convert_pheme_to_social_seed import build_seed


def _write_tweet(path: Path, *, tweet_id: str, user_id: str, text: str, created_at: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	payload = {
		"id_str": tweet_id,
		"created_at": created_at,
		"text": text,
		"user": {
			"id_str": user_id,
			"name": f"User {user_id}",
			"screen_name": f"user_{user_id}",
			"description": "Synthetic test user.",
		},
	}
	path.write_text(json.dumps(payload), encoding="utf-8")


class ConvertPhemeToSocialSeedTests(unittest.TestCase):
	def test_build_seed_converts_pheme_source_tweets_to_runtime_seed(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			root = Path(td) / "pheme"
			_write_tweet(
				root / "event-a" / "rumours" / "thread-1" / "source-tweets" / "1.json",
				tweet_id="1",
				user_id="101",
				text="Rumor source text.",
				created_at="Mon Jan 01 00:00:00 +0000 2024",
			)
			_write_tweet(
				root / "event-a" / "non-rumours" / "thread-2" / "source-tweets" / "2.json",
				tweet_id="2",
				user_id="102",
				text="Background non-rumor text.",
				created_at="Mon Jan 01 00:06:00 +0000 2024",
			)

			seed = build_seed(root, rumor_count=1, noise_count=1, seed="test", tick_minutes=3, max_text_chars=280)

			self.assertEqual(len(seed["accounts"]), 2)
			self.assertEqual(len(seed["posts"]), 2)
			self.assertEqual(
				{x["account_id"] for x in seed["accounts"]},
				{"external_pheme_rumor_source", "external_pheme_background_source"},
			)
			posts_by_text = {post["text"]: post for post in seed["posts"]}
			self.assertIn("rumor", posts_by_text["Rumor source text."]["tags"])
			self.assertIn("non_rumor", posts_by_text["Background non-rumor text."]["tags"])
			self.assertIn("background", posts_by_text["Background non-rumor text."]["tags"])

			db_path = Path(td) / "social.sqlite3"
			runtime = SQLiteSocialPlatformRuntime(db_path)
			seed_social_platform_runtime(runtime, seed)
			feed = runtime.invoke(
				"observe_feed",
				{"account_id": seed["accounts"][0]["account_id"], "limit": 5, "tick": 10},
				{"run_id": "run_test"},
			)

			self.assertEqual(feed[0]["type"], "SocialFeedObserved")
			self.assertEqual(len(feed[0]["items"]), 2)


if __name__ == "__main__":
	unittest.main()
