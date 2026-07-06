from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes import SQLiteSocialPlatformRuntime


def _runtime(db_path: Path) -> SQLiteSocialPlatformRuntime:
	rt = SQLiteSocialPlatformRuntime(db_path)
	rt.upsert_account("acc_doudou", "豆豆", interests={"kindergarten": 1.0, "outdoor": 0.7})
	rt.upsert_account("acc_teacher", "老师", interests={"kindergarten": 1.0})
	rt.upsert_account("acc_food", "食堂", interests={"food": 1.0})
	return rt


def _count(db_path: Path, table: str) -> int:
	conn = sqlite3.connect(db_path)
	try:
		return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
	finally:
		conn.close()


def _post_metric(db_path: Path, post_id: str, column: str) -> int:
	conn = sqlite3.connect(db_path)
	try:
		return int(conn.execute(f"SELECT {column} FROM posts WHERE post_id=?", (post_id,)).fetchone()[0] or 0)
	finally:
		conn.close()


class SQLiteSocialPlatformRuntimeTests(unittest.TestCase):
	def test_observe_feed_returns_cards_and_records_exposures(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			db_path = Path(td) / "social.sqlite3"
			rt = _runtime(db_path)
			rt.invoke(
				"create_post",
				{"account_id": "acc_teacher", "post_id": "post_outdoor", "text": "明天户外活动需要带水壶。", "tags": ["kindergarten", "outdoor"], "tick": 1},
				{},
			)
			rt.invoke(
				"create_post",
				{"account_id": "acc_food", "post_id": "post_lunch", "text": "今天午餐有南瓜汤。", "tags": ["food"], "tick": 1},
				{},
			)

			events = rt.invoke("observe_feed", {"account_id": "acc_doudou", "limit": 2, "tick": 10}, {"run_id": "run_01"})

			self.assertEqual(events[0]["type"], "SocialFeedObserved")
			self.assertEqual(events[0]["items"][0]["post_id"], "post_outdoor")
			self.assertIn("summary", events[0]["items"][0])
			self.assertFalse(events[0]["memory_hint"]["should_remember_by_default"])
			self.assertEqual(_count(db_path, "exposures"), 2)

	def test_observe_post_returns_body_and_top_comments(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			db_path = Path(td) / "social.sqlite3"
			rt = _runtime(db_path)
			rt.invoke(
				"create_post",
				{"account_id": "acc_teacher", "post_id": "post_notice", "text": "请大家明天带水壶和帽子。", "tags": ["kindergarten"], "tick": 1},
				{},
			)
			rt.invoke(
				"interact_post",
				{"account_id": "acc_doudou", "post_id": "post_notice", "action": "comment", "text": "我记住啦。", "tick": 2},
				{},
			)

			events = rt.invoke("observe_post", {"account_id": "acc_doudou", "post_id": "post_notice", "tick": 3}, {})

			self.assertEqual(events[0]["type"], "SocialPostObserved")
			self.assertEqual(events[0]["post"]["text"], "请大家明天带水壶和帽子。")
			self.assertEqual(events[0]["post"]["metrics"]["comments"], 1)
			self.assertEqual(events[0]["post"]["top_comments"][0]["text"], "我记住啦。")
			self.assertTrue(events[0]["memory_hint"]["should_remember_by_default"])
			self.assertEqual(_count(db_path, "view_history"), 1)

	def test_interact_post_updates_metrics(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			db_path = Path(td) / "social.sqlite3"
			rt = _runtime(db_path)
			rt.invoke(
				"create_post",
				{"account_id": "acc_teacher", "post_id": "post_001", "text": "今天有户外游戏。", "tags": ["outdoor"], "tick": 1},
				{},
			)

			like_events = rt.invoke("interact_post", {"account_id": "acc_doudou", "post_id": "post_001", "action": "like", "tick": 2}, {})
			comment_events = rt.invoke(
				"interact_post",
				{"account_id": "acc_doudou", "post_id": "post_001", "action": "comment", "text": "想参加。", "tick": 3},
				{},
			)
			repost_events = rt.invoke(
				"interact_post",
				{"account_id": "acc_doudou", "post_id": "post_001", "action": "repost", "text": "分享给朋友。", "tick": 4},
				{},
			)

			self.assertEqual(like_events[0]["type"], "SocialPostInteracted")
			self.assertFalse(like_events[0]["memory_hint"]["should_remember_by_default"])
			self.assertTrue(comment_events[0]["memory_hint"]["should_remember_by_default"])
			self.assertTrue(repost_events[0]["memory_hint"]["should_remember_by_default"])
			self.assertEqual(_post_metric(db_path, "post_001", "like_count"), 1)
			self.assertEqual(_post_metric(db_path, "post_001", "comment_count"), 1)
			self.assertEqual(_post_metric(db_path, "post_001", "repost_count"), 1)

	def test_follow_account_updates_relationship_and_feed(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			db_path = Path(td) / "social.sqlite3"
			rt = _runtime(db_path)
			rt.invoke("follow_account", {"account_id": "acc_doudou", "target_account_id": "acc_food", "tick": 1}, {})
			rt.invoke("create_post", {"account_id": "acc_food", "post_id": "post_food", "text": "点心时间到了。", "tags": ["food"], "tick": 2}, {})
			rt.invoke(
				"create_post",
				{"account_id": "acc_teacher", "post_id": "post_teacher", "text": "普通提醒。", "tags": ["misc"], "tick": 2},
				{},
			)

			events = rt.invoke("observe_feed", {"account_id": "acc_doudou", "limit": 1, "tick": 3}, {"run_id": "run_01"})

			self.assertEqual(events[0]["items"][0]["post_id"], "post_food")
			self.assertEqual(events[0]["items"][0]["why_visible"], "followed_author")

	def test_checkpoint_restore_reverts_sqlite_state(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			db_path = Path(td) / "social.sqlite3"
			rt = _runtime(db_path)
			rt.invoke("create_post", {"account_id": "acc_teacher", "post_id": "post_before", "text": "恢复前帖子。", "tags": ["kindergarten"], "tick": 1}, {})

			save_events = rt.save_checkpoint({"run_id": "run_restore", "tick": 5, "time_str": "T5", "phase": "save"})
			self.assertEqual(save_events[0]["type"], "SocialRuntimeCheckpointSaved")

			rt.invoke("create_post", {"account_id": "acc_teacher", "post_id": "post_after", "text": "恢复后应该消失。", "tags": ["outdoor"], "tick": 6}, {})
			rt.invoke("interact_post", {"account_id": "acc_doudou", "post_id": "post_before", "action": "like", "tick": 7}, {})
			self.assertEqual(_count(db_path, "posts"), 2)
			self.assertEqual(_post_metric(db_path, "post_before", "like_count"), 1)

			restore_events = rt.restore_checkpoint({"run_id": "run_restore", "tick": 5, "time_str": "T5", "phase": "restore"})

			self.assertEqual(restore_events[0]["type"], "SocialRuntimeCheckpointRestored")
			self.assertEqual(_count(db_path, "posts"), 1)
			self.assertEqual(_post_metric(db_path, "post_before", "like_count"), 0)
			conn = sqlite3.connect(db_path)
			try:
				missing = conn.execute("SELECT post_id FROM posts WHERE post_id='post_after'").fetchone()
			finally:
				conn.close()
			self.assertIsNone(missing)


if __name__ == "__main__":
	unittest.main()
