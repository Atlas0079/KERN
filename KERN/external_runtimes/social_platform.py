from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = "social_platform.v3"
MAX_FEED_ITEMS = 8
MAX_REPOST_ITEMS = 3
ORIGINAL_SOURCE_KINDS = frozenset({"followed_author", "interest_match", "hot"})


class SQLiteSocialPlatform:
	"""Standalone deterministic model of a feed-based social platform."""

	def __init__(self, database_path: str | Path, *, checkpoint_dir: str | Path | None = None) -> None:
		self.database_path = Path(database_path).resolve()
		self.checkpoint_dir = Path(checkpoint_dir).resolve() if checkpoint_dir else self.database_path.parent / "checkpoints"
		self.database_path.parent.mkdir(parents=True, exist_ok=True)
		self._transaction_id = ""
		self._transaction_connection: sqlite3.Connection | None = None
		self._initialize_schema()

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.database_path)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA foreign_keys = ON")
		return connection

	@contextmanager
	def _read_db(self) -> Iterator[sqlite3.Connection]:
		connection = self._connect()
		try:
			yield connection
		finally:
			connection.close()

	@contextmanager
	def _write_db(self, transaction_id: str = "") -> Iterator[sqlite3.Connection]:
		requested = str(transaction_id or "").strip()
		if self._transaction_connection is not None:
			if requested != self._transaction_id:
				raise ValueError("transaction_id does not match active transaction")
			yield self._transaction_connection
			return
		if requested:
			raise ValueError("transaction_id has no active transaction")
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
		conn = self._connect()
		try:
			tables = {
				str(row["name"])
				for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
			}
			if tables and "platform_meta" not in tables:
				raise ValueError("unsupported social platform database schema; delete and regenerate the database")
			if tables:
				row = conn.execute("SELECT value FROM platform_meta WHERE key='schema_version'").fetchone()
				if row is None or str(row["value"]) != SCHEMA_VERSION:
					raise ValueError("unsupported social platform database schema; delete and regenerate the database")
			conn.executescript(
				"""
				CREATE TABLE IF NOT EXISTS platform_meta (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				CREATE TABLE IF NOT EXISTS accounts (
					account_id TEXT PRIMARY KEY,
					display_name TEXT NOT NULL,
					bio TEXT NOT NULL
				);
				CREATE TABLE IF NOT EXISTS account_interests (
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					topic TEXT NOT NULL,
					weight REAL NOT NULL,
					PRIMARY KEY (account_id, topic)
				);
				CREATE TABLE IF NOT EXISTS posts (
					post_id TEXT PRIMARY KEY,
					author_id TEXT NOT NULL REFERENCES accounts(account_id),
					text TEXT NOT NULL,
					condition_id TEXT NOT NULL,
					created_tick INTEGER NOT NULL
				);
				CREATE TABLE IF NOT EXISTS post_ranking_topics (
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					topic TEXT NOT NULL,
					PRIMARY KEY (post_id, topic)
				);
				CREATE TABLE IF NOT EXISTS post_display_hashtags (
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					position INTEGER NOT NULL,
					hashtag TEXT NOT NULL,
					PRIMARY KEY (post_id, position),
					UNIQUE (post_id, hashtag)
				);
				CREATE TABLE IF NOT EXISTS follows (
					follower_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					followee_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					created_tick INTEGER NOT NULL,
					PRIMARY KEY (follower_id, followee_id)
				);
				CREATE TABLE IF NOT EXISTS feed_sessions (
					feed_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					tick INTEGER NOT NULL,
					page_limit INTEGER NOT NULL,
					item_count INTEGER NOT NULL
				);
				CREATE TABLE IF NOT EXISTS exposures (
					exposure_id INTEGER PRIMARY KEY AUTOINCREMENT,
					feed_session_id INTEGER NOT NULL REFERENCES feed_sessions(feed_session_id) ON DELETE CASCADE,
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					source_kind TEXT NOT NULL,
					source_account_id TEXT NOT NULL REFERENCES accounts(account_id),
					feed_item_kind TEXT NOT NULL,
					reposted_by_account_id TEXT REFERENCES accounts(account_id),
					reposted_tick INTEGER,
					tick INTEGER NOT NULL,
					section TEXT NOT NULL,
					position INTEGER NOT NULL,
					score REAL NOT NULL,
					repost_count INTEGER NOT NULL,
					like_count INTEGER NOT NULL,
					comment_count INTEGER NOT NULL,
					viewer_has_liked INTEGER NOT NULL,
					viewer_has_reposted INTEGER NOT NULL,
					UNIQUE (feed_session_id, position),
					UNIQUE (feed_session_id, post_id)
				);
				CREATE TABLE IF NOT EXISTS reposts (
					repost_id INTEGER PRIMARY KEY AUTOINCREMENT,
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					source_exposure_id INTEGER NOT NULL REFERENCES exposures(exposure_id),
					created_tick INTEGER NOT NULL,
					text TEXT NOT NULL,
					UNIQUE (account_id, post_id)
				);
				CREATE TABLE IF NOT EXISTS likes (
					account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					source_exposure_id INTEGER NOT NULL REFERENCES exposures(exposure_id),
					created_tick INTEGER NOT NULL,
					PRIMARY KEY (account_id, post_id)
				);
				CREATE TABLE IF NOT EXISTS comments (
					comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
					post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
					author_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
					source_exposure_id INTEGER NOT NULL REFERENCES exposures(exposure_id),
					text TEXT NOT NULL,
					created_tick INTEGER NOT NULL
				);
				CREATE INDEX IF NOT EXISTS idx_posts_tick ON posts(created_tick, post_id);
				CREATE INDEX IF NOT EXISTS idx_sessions_account_tick ON feed_sessions(account_id, tick, feed_session_id);
				CREATE INDEX IF NOT EXISTS idx_exposures_account_post ON exposures(account_id, post_id, tick, exposure_id);
				CREATE INDEX IF NOT EXISTS idx_reposts_tick ON reposts(created_tick, post_id, account_id);
				CREATE INDEX IF NOT EXISTS idx_likes_tick ON likes(created_tick, post_id, account_id);
				CREATE INDEX IF NOT EXISTS idx_comments_tick ON comments(created_tick, post_id, comment_id);
				"""
			)
			conn.execute("INSERT OR IGNORE INTO platform_meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
			self._verify_schema(conn)
			conn.commit()
		except Exception:
			conn.rollback()
			raise
		finally:
			conn.close()

	@staticmethod
	def _verify_schema(conn: sqlite3.Connection) -> None:
		row = conn.execute("SELECT value FROM platform_meta WHERE key='schema_version'").fetchone()
		if row is None or str(row["value"]) != SCHEMA_VERSION:
			raise ValueError("unsupported social platform database schema; delete and regenerate the database")

	def begin_transaction(self, transaction_id: str) -> None:
		tid = self._clean(transaction_id, "transaction_id")
		if self._transaction_connection is not None:
			raise RuntimeError("social platform already has an active transaction")
		connection = self._connect()
		try:
			connection.execute("BEGIN IMMEDIATE")
		except Exception:
			connection.close()
			raise
		self._transaction_id = tid
		self._transaction_connection = connection

	def commit_transaction(self, transaction_id: str) -> None:
		connection = self._require_active_transaction(transaction_id)
		try:
			connection.commit()
		finally:
			connection.close()
			self._transaction_connection = None
			self._transaction_id = ""

	def rollback_transaction(self, transaction_id: str) -> None:
		connection = self._require_active_transaction(transaction_id)
		try:
			connection.rollback()
		finally:
			connection.close()
			self._transaction_connection = None
			self._transaction_id = ""

	def _require_active_transaction(self, transaction_id: str) -> sqlite3.Connection:
		if self._transaction_connection is None:
			raise RuntimeError("social platform has no active transaction")
		if self._clean(transaction_id, "transaction_id") != self._transaction_id:
			raise ValueError("transaction_id does not match active transaction")
		return self._transaction_connection

	def _ensure_no_active_transaction(self, operation: str) -> None:
		if self._transaction_connection is not None:
			raise RuntimeError(f"cannot {operation} while social platform has an active transaction")

	def seed_from_file(self, path: str | Path) -> None:
		self.seed(json.loads(Path(path).read_text(encoding="utf-8")))

	def seed(self, seed: dict[str, Any]) -> None:
		if not isinstance(seed, dict) or set(seed) != {"accounts", "posts", "follows"}:
			raise ValueError("social platform seed must contain exactly accounts, posts, and follows")
		account_rows = [self._account_row(item, index) for index, item in enumerate(self._require_list(seed, "accounts"))]
		post_rows = [self._post_row(item, index) for index, item in enumerate(self._require_list(seed, "posts"))]
		follow_rows = [self._follow_row(item, index) for index, item in enumerate(self._require_list(seed, "follows"))]
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
		if any(row["follower_id"] == row["followee_id"] for row in follow_rows):
			raise ValueError("social platform seed has self follow")
		if len({(row["follower_id"], row["followee_id"]) for row in follow_rows}) != len(follow_rows):
			raise ValueError("social platform seed has duplicate follow")

		with self._write_db() as conn:
			if any(int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in self._fact_tables()):
				raise ValueError("social platform can only be seeded when empty")
			for row in account_rows:
				conn.execute("INSERT INTO accounts(account_id, display_name, bio) VALUES(?, ?, ?)", (row["account_id"], row["display_name"], row["bio"]))
				for topic, weight in row["interests"].items():
					conn.execute("INSERT INTO account_interests(account_id, topic, weight) VALUES(?, ?, ?)", (row["account_id"], topic, weight))
			for row in post_rows:
				conn.execute(
					"INSERT INTO posts(post_id, author_id, text, condition_id, created_tick) VALUES(?, ?, ?, ?, ?)",
					(row["post_id"], row["author_id"], row["text"], row["condition_id"], row["tick"]),
				)
				for topic in row["ranking_topics"]:
					conn.execute("INSERT INTO post_ranking_topics(post_id, topic) VALUES(?, ?)", (row["post_id"], topic))
				for position, hashtag in enumerate(row["display_hashtags"]):
					conn.execute("INSERT INTO post_display_hashtags(post_id, position, hashtag) VALUES(?, ?, ?)", (row["post_id"], position, hashtag))
			for row in follow_rows:
				conn.execute("INSERT INTO follows(follower_id, followee_id, created_tick) VALUES(?, ?, ?)", (row["follower_id"], row["followee_id"], row["tick"]))

	def recommend_feed(self, account_id: str, *, tick: int, limit: int) -> list[dict[str, Any]]:
		account = self._clean(account_id, "account_id")
		page_limit = min(int(limit), MAX_FEED_ITEMS)
		if page_limit < 1:
			raise ValueError("feed limit must be positive")
		current_tick = int(tick)
		with self._read_db() as conn:
			self._require_account(conn, account)
			interests = {str(row["topic"]): float(row["weight"]) for row in conn.execute("SELECT topic, weight FROM account_interests WHERE account_id=?", (account,))}
			followed = {str(row["followee_id"]) for row in conn.execute("SELECT followee_id FROM follows WHERE follower_id=? AND created_tick<=?", (account, current_tick))}
			seen = {str(row["post_id"]) for row in conn.execute("SELECT DISTINCT post_id FROM exposures WHERE account_id=? AND tick<?", (account, current_tick))}
			repost_counts = self._counts_before(conn, "reposts", current_tick)
			like_counts = self._counts_before(conn, "likes", current_tick)
			comment_counts = self._counts_before(conn, "comments", current_tick)
			liked = {str(row["post_id"]) for row in conn.execute("SELECT post_id FROM likes WHERE account_id=?", (account,))}
			reposted = {str(row["post_id"]) for row in conn.execute("SELECT post_id FROM reposts WHERE account_id=?", (account,))}
			post_rows = conn.execute("SELECT * FROM posts WHERE created_tick<=? AND author_id!=? ORDER BY post_id", (current_tick, account)).fetchall()
			topics_by_post = {str(row["post_id"]): self._ranking_topics(conn, str(row["post_id"])) for row in post_rows}
			hashtags_by_post = {str(row["post_id"]): self._display_hashtags(conn, str(row["post_id"])) for row in post_rows}
			posts_by_id = {str(row["post_id"]): row for row in post_rows}
			original_cards = [
				self._original_card(row, topics_by_post[str(row["post_id"])], hashtags_by_post[str(row["post_id"])], interests, followed, seen, repost_counts, like_counts, comment_counts, liked, reposted, current_tick)
				for row in post_rows
			]
			repost_rows = conn.execute(
				"""
				SELECT r.repost_id, r.account_id, r.post_id, r.created_tick
				FROM reposts AS r JOIN follows AS f ON f.followee_id=r.account_id
				WHERE f.follower_id=? AND f.created_tick<=? AND r.created_tick<?
				ORDER BY r.post_id, r.account_id, r.repost_id
				""",
				(account, current_tick, current_tick),
			).fetchall()
			repost_cards = [
				self._repost_card(posts_by_id[str(row["post_id"])], row, topics_by_post[str(row["post_id"])], hashtags_by_post[str(row["post_id"])], interests, seen, repost_counts, like_counts, comment_counts, liked, reposted, current_tick)
				for row in repost_rows if str(row["post_id"]) in posts_by_id
			]

		selected_reposts: list[dict[str, Any]] = []
		for card in sorted(repost_cards, key=self._feed_sort_key):
			if card["post_id"] in {item["post_id"] for item in selected_reposts}:
				continue
			selected_reposts.append(card)
			if len(selected_reposts) >= min(MAX_REPOST_ITEMS, page_limit):
				break
		selected_ids = {item["post_id"] for item in selected_reposts}
		selected_originals = [card for card in sorted(original_cards, key=self._feed_sort_key) if card["post_id"] not in selected_ids][:(page_limit - len(selected_reposts))]
		page = [*selected_reposts, *selected_originals]
		for position, card in enumerate(page):
			card["position"] = position
			card.pop("_source_tick", None)
		return page

	def open_feed_session(self, account_id: str, *, tick: int, limit: int, transaction_id: str = "") -> dict[str, Any]:
		account = self._clean(account_id, "account_id")
		current_tick = int(tick)
		page_limit = min(int(limit), MAX_FEED_ITEMS)
		page = self.recommend_feed(account, tick=current_tick, limit=page_limit)
		with self._write_db(transaction_id) as conn:
			cursor = conn.execute(
				"INSERT INTO feed_sessions(account_id, tick, page_limit, item_count) VALUES(?, ?, ?, ?)",
				(account, current_tick, page_limit, len(page)),
			)
			session_id = int(cursor.lastrowid)
			items = [self._insert_exposure(conn, session_id, account, card, current_tick) for card in page]
		return {"feed_session_id": session_id, "account_id": account, "tick": current_tick, "page_limit": page_limit, "feed_items": items}

	def _insert_exposure(self, conn: sqlite3.Connection, session_id: int, account: str, card: dict[str, Any], tick: int) -> dict[str, Any]:
		post = self._clean(card.get("post_id"), "post_id")
		source_kind = self._clean(card.get("source_kind"), "source_kind")
		source_account = self._clean(card.get("source_account_id"), "source_account_id")
		section = self._clean(card.get("section"), "section")
		post_row = self._require_post(conn, post)
		self._require_account(conn, source_account)
		if source_kind == "followed_repost":
			if section != "reposts" or conn.execute("SELECT 1 FROM reposts WHERE account_id=? AND post_id=? AND created_tick<?", (source_account, post, tick)).fetchone() is None:
				raise ValueError("followed repost exposure source is invalid")
			if conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followee_id=? AND created_tick<=?", (account, source_account, tick)).fetchone() is None:
				raise ValueError("account does not follow repost source")
		elif source_kind in ORIGINAL_SOURCE_KINDS:
			if section != "recommended" or source_account != str(post_row["author_id"]):
				raise ValueError("original exposure source is invalid")
		else:
			raise ValueError(f"unsupported exposure source_kind: {source_kind}")
		cursor = conn.execute(
			"""
			INSERT INTO exposures(
				feed_session_id, account_id, post_id, source_kind, source_account_id,
				feed_item_kind, reposted_by_account_id, reposted_tick, tick, section,
				position, score, repost_count, like_count, comment_count,
				viewer_has_liked, viewer_has_reposted
			) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""",
			(
				session_id, account, post, source_kind, source_account,
				card["feed_item_kind"], card.get("reposted_by_account_id"), card.get("reposted_tick"), tick, section,
				int(card["position"]), float(card["score"]), int(card["repost_count"]), int(card["like_count"]), int(card["comment_count"]),
				int(bool(card["viewer_has_liked"])), int(bool(card["viewer_has_reposted"])),
			),
		)
		exposure = dict(card)
		exposure["feed_session_id"] = session_id
		exposure["exposure_id"] = int(cursor.lastrowid)
		exposure.pop("score", None)
		exposure.pop("previously_exposed", None)
		return exposure

	@staticmethod
	def _feed_sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
		return (-float(card["score"]), -int(card["_source_tick"]), str(card["post_id"]), str(card["source_account_id"]))

	def _original_card(self, post: sqlite3.Row, topics: list[str], hashtags: list[str], interests: dict[str, float], followed: set[str], seen: set[str], repost_counts: dict[str, int], like_counts: dict[str, int], comment_counts: dict[str, int], liked: set[str], reposted: set[str], tick: int) -> dict[str, Any]:
		post_id = str(post["post_id"])
		author_id = str(post["author_id"])
		interest_score = sum(interests.get(topic, 0.0) for topic in topics)
		is_followed = author_id in followed
		score = 2.0 * interest_score + 1.5 * float(is_followed) + 1.0 / (1.0 + max(0, tick - int(post["created_tick"]))) + 0.5 * repost_counts.get(post_id, 0)
		return self._card(post, hashtags, post_id, "original", author_id, None, None, "followed_author" if is_followed else "interest_match" if interest_score else "hot", author_id, "recommended", score, seen, repost_counts, like_counts, comment_counts, liked, reposted, int(post["created_tick"]))

	def _repost_card(self, post: sqlite3.Row, repost: sqlite3.Row, topics: list[str], hashtags: list[str], interests: dict[str, float], seen: set[str], repost_counts: dict[str, int], like_counts: dict[str, int], comment_counts: dict[str, int], liked: set[str], reposted: set[str], tick: int) -> dict[str, Any]:
		post_id = str(post["post_id"])
		reposted_tick = int(repost["created_tick"])
		score = 2.0 * sum(interests.get(topic, 0.0) for topic in topics) + 1.5 + 1.0 / (1.0 + max(0, tick - reposted_tick)) + 0.5 * repost_counts.get(post_id, 0)
		return self._card(post, hashtags, post_id, "repost", str(post["author_id"]), str(repost["account_id"]), reposted_tick, "followed_repost", str(repost["account_id"]), "reposts", score, seen, repost_counts, like_counts, comment_counts, liked, reposted, reposted_tick)

	@staticmethod
	def _card(post: sqlite3.Row, hashtags: list[str], post_id: str, item_kind: str, author_id: str, reposter_id: str | None, reposted_tick: int | None, source_kind: str, source_account: str, section: str, score: float, seen: set[str], repost_counts: dict[str, int], like_counts: dict[str, int], comment_counts: dict[str, int], liked: set[str], reposted: set[str], source_tick: int) -> dict[str, Any]:
		return {
			"feed_item_kind": item_kind,
			"post_id": post_id,
			"original_author_id": author_id,
			"created_tick": int(post["created_tick"]),
			"reposted_by_account_id": reposter_id,
			"reposted_tick": reposted_tick,
			"text": str(post["text"]),
			"display_hashtags": list(hashtags),
			"repost_count": repost_counts.get(post_id, 0),
			"like_count": like_counts.get(post_id, 0),
			"comment_count": comment_counts.get(post_id, 0),
			"viewer_has_liked": post_id in liked,
			"viewer_has_reposted": post_id in reposted,
			"source_kind": source_kind,
			"source_account_id": source_account,
			"section": section,
			"position": -1,
			"score": 0.0 if post_id in seen else float(score),
			"previously_exposed": post_id in seen,
			"_source_tick": source_tick,
		}

	def repost(self, account_id: str, post_id: str, *, source_exposure_id: int, tick: int, text: str = "", transaction_id: str = "") -> dict[str, Any]:
		account, post, current_tick = self._interaction_context(account_id, post_id, source_exposure_id, tick)
		with self._write_db(transaction_id) as conn:
			self._require_source_exposure(conn, source_exposure_id, account, post, current_tick)
			try:
				cursor = conn.execute("INSERT INTO reposts(account_id, post_id, source_exposure_id, created_tick, text) VALUES(?, ?, ?, ?, ?)", (account, post, int(source_exposure_id), current_tick, str(text)))
			except sqlite3.IntegrityError as exc:
				raise ValueError("account has already reposted this post") from exc
			return {"repost_id": int(cursor.lastrowid), "account_id": account, "post_id": post, "source_exposure_id": int(source_exposure_id), "tick": current_tick, "text": str(text)}

	def like(self, account_id: str, post_id: str, *, source_exposure_id: int, tick: int, transaction_id: str = "") -> dict[str, Any]:
		account, post, current_tick = self._interaction_context(account_id, post_id, source_exposure_id, tick)
		with self._write_db(transaction_id) as conn:
			self._require_source_exposure(conn, source_exposure_id, account, post, current_tick)
			try:
				conn.execute("INSERT INTO likes(account_id, post_id, source_exposure_id, created_tick) VALUES(?, ?, ?, ?)", (account, post, int(source_exposure_id), current_tick))
			except sqlite3.IntegrityError as exc:
				raise ValueError("account has already liked this post") from exc
			return {"account_id": account, "post_id": post, "source_exposure_id": int(source_exposure_id), "tick": current_tick}

	def comment(self, account_id: str, post_id: str, *, source_exposure_id: int, text: str, tick: int, transaction_id: str = "") -> dict[str, Any]:
		account, post, current_tick = self._interaction_context(account_id, post_id, source_exposure_id, tick)
		comment_text = self._clean(text, "comment text")
		with self._write_db(transaction_id) as conn:
			self._require_source_exposure(conn, source_exposure_id, account, post, current_tick)
			cursor = conn.execute("INSERT INTO comments(post_id, author_id, source_exposure_id, text, created_tick) VALUES(?, ?, ?, ?, ?)", (post, account, int(source_exposure_id), comment_text, current_tick))
			return {"comment_id": int(cursor.lastrowid), "author_id": account, "post_id": post, "source_exposure_id": int(source_exposure_id), "text": comment_text, "tick": current_tick}

	def feed_session_for(self, account_id: str, tick: int) -> dict[str, Any] | None:
		account = self._clean(account_id, "account_id")
		with self._read_db() as conn:
			self._require_account(conn, account)
			row = conn.execute("SELECT * FROM feed_sessions WHERE account_id=? AND tick=? ORDER BY feed_session_id DESC LIMIT 1", (account, int(tick))).fetchone()
			return None if row is None else self._feed_session_payload(conn, row)

	def feed_session_records(self, account_id: str = "") -> list[dict[str, Any]]:
		account = str(account_id or "").strip()
		with self._read_db() as conn:
			if account:
				self._require_account(conn, account)
				rows = conn.execute("SELECT * FROM feed_sessions WHERE account_id=? ORDER BY feed_session_id", (account,)).fetchall()
			else:
				rows = conn.execute("SELECT * FROM feed_sessions ORDER BY feed_session_id").fetchall()
			return [self._feed_session_payload(conn, row) for row in rows]

	def _feed_session_payload(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
		session_id = int(row["feed_session_id"])
		items = [self._exposure_card(conn, exposure) for exposure in conn.execute("SELECT * FROM exposures WHERE feed_session_id=? ORDER BY position", (session_id,))]
		return {"feed_session_id": session_id, "account_id": str(row["account_id"]), "tick": int(row["tick"]), "page_limit": int(row["page_limit"]), "feed_items": items}

	def _exposure_card(self, conn: sqlite3.Connection, exposure: sqlite3.Row) -> dict[str, Any]:
		post = self._require_post(conn, str(exposure["post_id"]))
		return {
			"feed_session_id": int(exposure["feed_session_id"]),
			"exposure_id": int(exposure["exposure_id"]),
			"feed_item_kind": str(exposure["feed_item_kind"]),
			"post_id": str(exposure["post_id"]),
			"original_author_id": str(post["author_id"]),
			"created_tick": int(post["created_tick"]),
			"reposted_by_account_id": exposure["reposted_by_account_id"],
			"reposted_tick": exposure["reposted_tick"],
			"text": str(post["text"]),
			"display_hashtags": self._display_hashtags(conn, str(exposure["post_id"])),
			"repost_count": int(exposure["repost_count"]),
			"like_count": int(exposure["like_count"]),
			"comment_count": int(exposure["comment_count"]),
			"viewer_has_liked": bool(exposure["viewer_has_liked"]),
			"viewer_has_reposted": bool(exposure["viewer_has_reposted"]),
			"source_kind": str(exposure["source_kind"]),
			"source_account_id": str(exposure["source_account_id"]),
			"section": str(exposure["section"]),
			"position": int(exposure["position"]),
		}

	def repost_records(self, account_id: str = "") -> list[dict[str, Any]]:
		return self._records("reposts", "repost_id", "account_id", account_id)

	def like_records(self, account_id: str = "") -> list[dict[str, Any]]:
		return self._records("likes", "created_tick, account_id, post_id", "account_id", account_id)

	def comment_records(self, post_id: str = "") -> list[dict[str, Any]]:
		return self._records("comments", "comment_id", "post_id", post_id)

	def exposure_records(self, account_id: str = "") -> list[dict[str, Any]]:
		return self._records("exposures", "exposure_id", "account_id", account_id)

	def _records(self, table: str, order_by: str, filter_column: str, filter_value: str) -> list[dict[str, Any]]:
		value = str(filter_value or "").strip()
		query = f"SELECT * FROM {table}"
		params: tuple[Any, ...] = ()
		if value:
			query += f" WHERE {filter_column}=?"
			params = (value,)
		query += f" ORDER BY {order_by}"
		with self._read_db() as conn:
			return [dict(row) for row in conn.execute(query, params)]

	def metrics(self) -> dict[str, int]:
		with self._read_db() as conn:
			return {
				"cumulative_feed_sessions": int(conn.execute("SELECT COUNT(*) FROM feed_sessions").fetchone()[0]),
				"cumulative_exposures": int(conn.execute("SELECT COUNT(*) FROM exposures").fetchone()[0]),
				"cumulative_reposts": int(conn.execute("SELECT COUNT(*) FROM reposts").fetchone()[0]),
				"cumulative_likes": int(conn.execute("SELECT COUNT(*) FROM likes").fetchone()[0]),
				"cumulative_comments": int(conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]),
			}

	def counts(self) -> dict[str, int]:
		with self._read_db() as conn:
			return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in self._fact_tables()}

	def save_checkpoint(self, run_id: str, *, tick: int) -> Path:
		self._ensure_no_active_transaction("save checkpoint")
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
		self._ensure_no_active_transaction("restore checkpoint")
		checkpoint = self._checkpoint_path(run_id, tick)
		if not checkpoint.is_file():
			raise FileNotFoundError(f"social platform checkpoint not found: {checkpoint}")
		shutil.copy2(checkpoint, self.database_path)
		with self._read_db() as conn:
			self._verify_schema(conn)

	def close(self) -> None:
		if self._transaction_connection is not None:
			self._transaction_connection.rollback()
			self._transaction_connection.close()
			self._transaction_connection = None
			self._transaction_id = ""

	def _checkpoint_path(self, run_id: str, tick: int) -> Path:
		return self.checkpoint_dir / self._clean(run_id, "run_id") / f"tick_{int(tick):06d}.sqlite"

	@staticmethod
	def _clean(value: Any, label: str) -> str:
		if not isinstance(value, str) or not value.strip() or value != value.strip():
			raise ValueError(f"{label} must be a non-blank trimmed string")
		return value

	@staticmethod
	def _require_list(seed: dict[str, Any], key: str) -> list[Any]:
		value = seed.get(key)
		if not isinstance(value, list):
			raise ValueError(f"social platform seed field {key} must be an array")
		return value

	def _account_row(self, raw: Any, index: int) -> dict[str, Any]:
		if not isinstance(raw, dict) or set(raw).difference({"account_id", "display_name", "bio", "interests"}):
			raise ValueError(f"accounts[{index}] has invalid fields")
		interests = raw.get("interests")
		if not isinstance(interests, dict):
			raise ValueError(f"accounts[{index}].interests must be an object")
		return {
			"account_id": self._clean(raw.get("account_id"), f"accounts[{index}].account_id"),
			"display_name": self._clean(raw.get("display_name"), f"accounts[{index}].display_name"),
			"bio": str(raw.get("bio", "")),
			"interests": {self._clean(topic, f"accounts[{index}].interests topic"): float(weight) for topic, weight in interests.items()},
		}

	def _post_row(self, raw: Any, index: int) -> dict[str, Any]:
		expected = {"account_id", "post_id", "text", "ranking_topics", "display_hashtags", "condition_id", "tick"}
		if not isinstance(raw, dict) or set(raw) != expected:
			raise ValueError(f"posts[{index}] must contain exactly {sorted(expected)}")
		topics = self._string_array(raw["ranking_topics"], f"posts[{index}].ranking_topics")
		hashtags = self._string_array(raw["display_hashtags"], f"posts[{index}].display_hashtags")
		return {
			"author_id": self._clean(raw["account_id"], f"posts[{index}].account_id"),
			"post_id": self._clean(raw["post_id"], f"posts[{index}].post_id"),
			"text": self._clean(raw["text"], f"posts[{index}].text"),
			"ranking_topics": topics,
			"display_hashtags": hashtags,
			"condition_id": self._clean(raw["condition_id"], f"posts[{index}].condition_id"),
			"tick": int(raw["tick"]),
		}

	def _follow_row(self, raw: Any, index: int) -> dict[str, Any]:
		expected = {"follower_id", "followee_id", "tick"}
		if not isinstance(raw, dict) or set(raw) != expected:
			raise ValueError(f"follows[{index}] must contain exactly {sorted(expected)}")
		return {"follower_id": self._clean(raw["follower_id"], f"follows[{index}].follower_id"), "followee_id": self._clean(raw["followee_id"], f"follows[{index}].followee_id"), "tick": int(raw["tick"])}

	def _string_array(self, raw: Any, label: str) -> list[str]:
		if not isinstance(raw, list) or not raw:
			raise ValueError(f"{label} must be a non-empty array")
		items = [self._clean(value, label) for value in raw]
		if len(set(items)) != len(items):
			raise ValueError(f"{label} must not contain duplicates")
		return items

	@staticmethod
	def _require_account(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row:
		row = conn.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
		if row is None:
			raise ValueError(f"account does not exist: {account_id}")
		return row

	@staticmethod
	def _require_post(conn: sqlite3.Connection, post_id: str) -> sqlite3.Row:
		row = conn.execute("SELECT * FROM posts WHERE post_id=?", (post_id,)).fetchone()
		if row is None:
			raise ValueError(f"post does not exist: {post_id}")
		return row

	@staticmethod
	def _require_source_exposure(conn: sqlite3.Connection, exposure_id: int, account_id: str, post_id: str, tick: int) -> sqlite3.Row:
		row = conn.execute("SELECT * FROM exposures WHERE exposure_id=? AND account_id=? AND post_id=? AND tick=?", (int(exposure_id), account_id, post_id, int(tick))).fetchone()
		if row is None:
			raise ValueError("source exposure does not match current account, post, and tick")
		return row

	def _interaction_context(self, account_id: str, post_id: str, exposure_id: int, tick: int) -> tuple[str, str, int]:
		if isinstance(exposure_id, bool) or not isinstance(exposure_id, int) or exposure_id <= 0:
			raise ValueError("source_exposure_id must be a positive integer")
		return self._clean(account_id, "account_id"), self._clean(post_id, "post_id"), int(tick)

	@staticmethod
	def _counts_before(conn: sqlite3.Connection, table: str, tick: int) -> dict[str, int]:
		return {str(row["post_id"]): int(row["count"]) for row in conn.execute(f"SELECT post_id, COUNT(*) AS count FROM {table} WHERE created_tick<? GROUP BY post_id", (int(tick),))}

	@staticmethod
	def _ranking_topics(conn: sqlite3.Connection, post_id: str) -> list[str]:
		return [str(row["topic"]) for row in conn.execute("SELECT topic FROM post_ranking_topics WHERE post_id=? ORDER BY topic", (post_id,))]

	@staticmethod
	def _display_hashtags(conn: sqlite3.Connection, post_id: str) -> list[str]:
		return [str(row["hashtag"]) for row in conn.execute("SELECT hashtag FROM post_display_hashtags WHERE post_id=? ORDER BY position", (post_id,))]

	@staticmethod
	def _fact_tables() -> tuple[str, ...]:
		return ("accounts", "posts", "follows", "feed_sessions", "exposures", "reposts", "likes", "comments")


__all__ = ["SQLiteSocialPlatform"]
