from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SQLiteSocialPlatform:
	"""Standalone SQLite model of a feed-based social platform.

	This class has no dependency on KERN.  It owns social data and exposes a
	deterministic API that can be used directly by a script, HTTP adapter, or a
	KERN external-runtime adapter.
	"""

	def __init__(self, database_path: str | Path, *, checkpoint_dir: str | Path | None = None) -> None:
		self.database_path = Path(database_path).resolve()
		self.checkpoint_dir = Path(checkpoint_dir).resolve() if checkpoint_dir else self.database_path.parent / "checkpoints"
		self.database_path.parent.mkdir(parents=True, exist_ok=True)
		self._initialize_schema()

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.database_path)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA foreign_keys = ON")
		return connection

	@contextmanager
	def _db(self):
		connection = self._connect()
		try:
			yield connection
			connection.commit()
		except Exception:
			connection.rollback()
			raise
		finally:
			connection.close()

	def _initialize_schema(self) -> None:
		with self._db() as conn:
			conn.executescript(
				"""
				CREATE TABLE IF NOT EXISTS accounts (
					account_id TEXT PRIMARY KEY,
					display_name TEXT NOT NULL,
					bio TEXT NOT NULL
				);
				CREATE TABLE IF NOT EXISTS account_interests (
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					tag TEXT NOT NULL,
					weight REAL NOT NULL,
					PRIMARY KEY (account_id, tag)
				);
				CREATE TABLE IF NOT EXISTS posts (
					post_id TEXT PRIMARY KEY,
					author_id TEXT NOT NULL REFERENCES accounts(account_id),
					text TEXT NOT NULL,
					created_tick INTEGER NOT NULL,
					repost_count INTEGER NOT NULL DEFAULT 0
				);
				CREATE TABLE IF NOT EXISTS post_tags (
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					tag TEXT NOT NULL,
					PRIMARY KEY (post_id, tag)
				);
				CREATE TABLE IF NOT EXISTS follows (
					follower_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					followee_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					created_tick INTEGER NOT NULL,
					PRIMARY KEY (follower_id, followee_id)
				);
				CREATE TABLE IF NOT EXISTS exposures (
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					tick INTEGER NOT NULL,
					source TEXT NOT NULL,
					score REAL NOT NULL,
					position INTEGER NOT NULL,
					PRIMARY KEY (account_id, post_id, tick)
				);
				CREATE TABLE IF NOT EXISTS reposts (
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					created_tick INTEGER NOT NULL,
					PRIMARY KEY (account_id, post_id)
				);
				CREATE INDEX IF NOT EXISTS idx_posts_tick ON posts(created_tick, post_id);
				CREATE INDEX IF NOT EXISTS idx_exposures_account_post ON exposures(account_id, post_id);
				"""
			)

	def seed_from_file(self, path: str | Path) -> None:
		raw = json.loads(Path(path).read_text(encoding="utf-8"))
		self.seed(raw)

	def seed(self, seed: dict[str, Any]) -> None:
		if not isinstance(seed, dict):
			raise ValueError("social platform seed must be an object")
		accounts = self._require_list(seed, "accounts")
		posts = self._require_list(seed, "posts")
		follows = self._require_list(seed, "follows")
		account_rows = [self._account_row(item, index) for index, item in enumerate(accounts)]
		post_rows = [self._post_row(item, index) for index, item in enumerate(posts)]
		follow_rows = [self._follow_row(item, index) for index, item in enumerate(follows)]
		account_ids = {row["account_id"] for row in account_rows}
		if len(account_ids) != len(account_rows):
			raise ValueError("social platform seed has duplicate account_id")
		post_ids = {row["post_id"] for row in post_rows}
		if len(post_ids) != len(post_rows):
			raise ValueError("social platform seed has duplicate post_id")
		if any(row["author_id"] not in account_ids for row in post_rows):
			raise ValueError("social platform seed post author does not exist")
		if any(row["follower_id"] not in account_ids or row["followee_id"] not in account_ids for row in follow_rows):
			raise ValueError("social platform seed follow endpoint does not exist")
		if len({(row["follower_id"], row["followee_id"]) for row in follow_rows}) != len(follow_rows):
			raise ValueError("social platform seed has duplicate follow")

		with self._db() as conn:
			if any(int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in ("accounts", "posts", "follows", "exposures", "reposts")):
				raise ValueError("social platform can only be seeded when empty")
			for row in account_rows:
				conn.execute("INSERT INTO accounts(account_id, display_name, bio) VALUES(?, ?, ?)", (row["account_id"], row["display_name"], row["bio"]))
				for tag, weight in row["interests"].items():
					conn.execute("INSERT INTO account_interests(account_id, tag, weight) VALUES(?, ?, ?)", (row["account_id"], tag, weight))
			for row in post_rows:
				conn.execute("INSERT INTO posts(post_id, author_id, text, created_tick) VALUES(?, ?, ?, ?)", (row["post_id"], row["author_id"], row["text"], row["tick"]))
				for tag in row["tags"]:
					conn.execute("INSERT INTO post_tags(post_id, tag) VALUES(?, ?)", (row["post_id"], tag))
			for row in follow_rows:
				conn.execute("INSERT INTO follows(follower_id, followee_id, created_tick) VALUES(?, ?, ?)", (row["follower_id"], row["followee_id"], row["tick"]))

	def recommend_feed(self, account_id: str, *, tick: int, limit: int) -> list[dict[str, Any]]:
		account = self._clean(account_id, "account_id")
		if int(limit) < 1:
			raise ValueError("feed limit must be positive")
		with self._db() as conn:
			self._require_account(conn, account)
			interests = {str(row["tag"]): float(row["weight"]) for row in conn.execute("SELECT tag, weight FROM account_interests WHERE account_id=?", (account,))}
			followed = {str(row["followee_id"]) for row in conn.execute("SELECT followee_id FROM follows WHERE follower_id=?", (account,))}
			seen = {str(row["post_id"]) for row in conn.execute("SELECT post_id FROM exposures WHERE account_id=?", (account,))}
			rows = conn.execute("SELECT * FROM posts WHERE created_tick <= ? AND author_id != ? ORDER BY post_id", (int(tick), account)).fetchall()
			items: list[dict[str, Any]] = []
			for row in rows:
				post_id = str(row["post_id"])
				tags = [str(tag_row["tag"]) for tag_row in conn.execute("SELECT tag FROM post_tags WHERE post_id=? ORDER BY tag", (post_id,))]
				interest_score = sum(interests.get(tag, 0.0) for tag in tags)
				follow_score = 1.0 if str(row["author_id"]) in followed else 0.0
				freshness = 1.0 / (1.0 + max(0, int(tick) - int(row["created_tick"])))
				score = 2.0 * interest_score + 1.5 * follow_score + freshness + 0.5 * int(row["repost_count"])
				items.append({
					"post_id": post_id,
					"author_id": str(row["author_id"]),
					"text": str(row["text"]),
					"tags": tags,
					"score": score,
					"source": "followed_author" if follow_score else "interest_match" if interest_score else "hot",
					"previously_exposed": post_id in seen,
				})
			items.sort(key=lambda item: (-float(item["score"]), str(item["post_id"])))
			return items[: int(limit)]

	def record_exposure(self, account_id: str, post_id: str, *, tick: int, source: str, score: float, position: int) -> None:
		account = self._clean(account_id, "account_id")
		post = self._clean(post_id, "post_id")
		if int(position) < 0:
			raise ValueError("exposure position must be non-negative")
		with self._db() as conn:
			self._require_account(conn, account)
			self._require_post(conn, post)
			conn.execute(
				"INSERT OR IGNORE INTO exposures(account_id, post_id, tick, source, score, position) VALUES(?, ?, ?, ?, ?, ?)",
				(account, post, int(tick), self._clean(source, "source"), float(score), int(position)),
			)

	def repost(self, account_id: str, post_id: str, *, tick: int) -> dict[str, Any]:
		account = self._clean(account_id, "account_id")
		post = self._clean(post_id, "post_id")
		with self._db() as conn:
			self._require_account(conn, account)
			self._require_post(conn, post)
			if conn.execute("SELECT 1 FROM exposures WHERE account_id=? AND post_id=?", (account, post)).fetchone() is None:
				raise ValueError("post was not exposed to account")
			try:
				conn.execute("INSERT INTO reposts(account_id, post_id, created_tick) VALUES(?, ?, ?)", (account, post, int(tick)))
			except sqlite3.IntegrityError as exc:
				raise ValueError("account has already reposted this post") from exc
			conn.execute("UPDATE posts SET repost_count=repost_count + 1 WHERE post_id=?", (post,))
			return {"account_id": account, "post_id": post, "tick": int(tick)}

	def metrics(self) -> dict[str, int]:
		with self._db() as conn:
			return {
				"cumulative_reposts": int(conn.execute("SELECT COUNT(*) FROM reposts").fetchone()[0]),
				"cumulative_exposures": int(conn.execute("SELECT COUNT(*) FROM exposures").fetchone()[0]),
			}

	def counts(self) -> dict[str, int]:
		with self._db() as conn:
			return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in ("accounts", "posts", "follows", "exposures", "reposts")}

	def save_checkpoint(self, run_id: str, *, tick: int) -> Path:
		checkpoint = self._checkpoint_path(run_id, tick)
		checkpoint.parent.mkdir(parents=True, exist_ok=True)
		source = self._connect()
		destination = sqlite3.connect(checkpoint)
		try:
			source.backup(destination)
		finally:
			destination.close()
			source.close()
		return checkpoint

	def restore_checkpoint(self, run_id: str, *, tick: int) -> None:
		checkpoint = self._checkpoint_path(run_id, tick)
		if not checkpoint.is_file():
			raise FileNotFoundError(f"social platform checkpoint not found: {checkpoint}")
		shutil.copy2(checkpoint, self.database_path)

	def close(self) -> None:
		return None

	def _checkpoint_path(self, run_id: str, tick: int) -> Path:
		return self.checkpoint_dir / self._clean(run_id, "run_id") / f"tick_{int(tick):06d}.sqlite"

	@staticmethod
	def _clean(value: Any, label: str) -> str:
		text = str(value or "").strip()
		if not text:
			raise ValueError(f"{label} must not be blank")
		return text

	@staticmethod
	def _require_list(seed: dict[str, Any], key: str) -> list[Any]:
		value = seed.get(key)
		if not isinstance(value, list):
			raise ValueError(f"social platform seed field {key} must be an array")
		return value

	def _account_row(self, raw: Any, index: int) -> dict[str, Any]:
		if not isinstance(raw, dict):
			raise ValueError(f"accounts[{index}] must be an object")
		interests = raw.get("interests", {})
		if not isinstance(interests, dict):
			raise ValueError(f"accounts[{index}].interests must be an object")
		return {
			"account_id": self._clean(raw.get("account_id"), f"accounts[{index}].account_id"),
			"display_name": self._clean(raw.get("display_name"), f"accounts[{index}].display_name"),
			"bio": str(raw.get("bio", "") or ""),
			"interests": {self._clean(tag, f"accounts[{index}].interests tag"): float(weight) for tag, weight in interests.items()},
		}

	def _post_row(self, raw: Any, index: int) -> dict[str, Any]:
		if not isinstance(raw, dict):
			raise ValueError(f"posts[{index}] must be an object")
		tags = raw.get("tags")
		if not isinstance(tags, list):
			raise ValueError(f"posts[{index}].tags must be an array")
		return {
			"author_id": self._clean(raw.get("account_id"), f"posts[{index}].account_id"),
			"post_id": self._clean(raw.get("post_id"), f"posts[{index}].post_id"),
			"text": self._clean(raw.get("text"), f"posts[{index}].text"),
			"tags": [self._clean(tag, f"posts[{index}].tags") for tag in tags],
			"tick": int(raw.get("tick")),
		}

	def _follow_row(self, raw: Any, index: int) -> dict[str, Any]:
		if not isinstance(raw, dict):
			raise ValueError(f"follows[{index}] must be an object")
		return {
			"follower_id": self._clean(raw.get("follower_id"), f"follows[{index}].follower_id"),
			"followee_id": self._clean(raw.get("followee_id"), f"follows[{index}].followee_id"),
			"tick": int(raw.get("tick")),
		}

	@staticmethod
	def _require_account(conn: sqlite3.Connection, account_id: str) -> None:
		if conn.execute("SELECT 1 FROM accounts WHERE account_id=?", (account_id,)).fetchone() is None:
			raise ValueError(f"account does not exist: {account_id}")

	@staticmethod
	def _require_post(conn: sqlite3.Connection, post_id: str) -> None:
		if conn.execute("SELECT 1 FROM posts WHERE post_id=?", (post_id,)).fetchone() is None:
			raise ValueError(f"post does not exist: {post_id}")
