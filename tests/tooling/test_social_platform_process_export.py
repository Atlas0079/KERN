from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes.social_platform import SQLiteSocialPlatform
from tools.export_social_platform_process import export


def _seed() -> dict:
	return {
		"accounts": [
			{"account_id": "reader", "display_name": "Reader", "bio": "", "interests": {"risk": 1.0}},
			{"account_id": "author", "display_name": "Author", "bio": "", "interests": {"risk": 1.0}},
		],
		"posts": [
			{
				"account_id": "author",
				"post_id": "post_001",
				"text": "Risk information",
				"ranking_topics": ["risk"],
				"display_hashtags": ["风险"],
				"condition_id": "condition_a",
				"tick": 0,
			}
		],
		"follows": [{"follower_id": "reader", "followee_id": "author", "tick": 0}],
	}


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open("r", encoding="utf-8", newline="") as stream:
		return list(csv.DictReader(stream))


class SocialPlatformProcessExportTests(unittest.TestCase):
	def test_export_writes_raw_tables_and_process_derivatives(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			platform = SQLiteSocialPlatform(root / "platform.sqlite")
			platform.seed(_seed())
			session = platform.open_feed_session("reader", tick=1, limit=8)
			exposure_id = session["feed_items"][0]["exposure_id"]
			platform.like("reader", "post_001", source_exposure_id=exposure_id, tick=1)
			platform.comment("reader", "post_001", source_exposure_id=exposure_id, text="comment", tick=1)
			platform.repost("reader", "post_001", source_exposure_id=exposure_id, text="share", tick=1)
			platform.close()

			manifest = export(root / "platform.sqlite", root / "export")

			self.assertEqual(manifest["table_counts"]["exposures"], 1)
			self.assertTrue((root / "export" / "tables" / "posts.csv").is_file())
			summary = _read_csv(root / "export" / "summary_by_tick.csv")
			self.assertEqual(summary[0]["tick"], "1")
			self.assertEqual(summary[0]["exposures"], "1")
			self.assertEqual(summary[0]["likes"], "1")
			self.assertEqual(summary[0]["comments"], "1")
			self.assertEqual(summary[0]["reposts"], "1")
			reposts = _read_csv(root / "export" / "repost_process.csv")
			self.assertEqual(reposts[0]["cascade_depth"], "1")


if __name__ == "__main__":
	unittest.main()
