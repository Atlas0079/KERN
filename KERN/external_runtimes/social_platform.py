from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..execution_errors import ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE, executor_error


SCHEMA_VERSION = "social_platform.v1"


DATA_TABLES = [
	"runtime_meta",
	"accounts",
	"account_interests",
	"posts",
	"post_tags",
	"comments",
	"likes",
	"reposts",
	"follows",
	"feed_sessions",
	"exposures",
	"view_history",
	"action_traces",
]


@dataclass
class SQLiteSocialPlatformRuntime:
	"""
	SQLite-backed social platform runtime for LLM agents.

	The runtime owns platform state. KERN interacts with it only through
	operation events and checkpoint lifecycle calls.
	"""

	db_path: str | Path
	runtime_id: str = "weibo"

	def __post_init__(self) -> None:
		self.db_path = str(self.db_path)
		Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
		self._init_schema()

	def _connect(self) -> sqlite3.Connection:
		conn = sqlite3.connect(self.db_path)
		conn.row_factory = sqlite3.Row
		conn.execute("PRAGMA foreign_keys = ON")
		return conn

	@contextmanager
	def _db(self) -> Iterator[sqlite3.Connection]:
		conn = self._connect()
		try:
			yield conn
			conn.commit()
		except Exception:
			conn.rollback()
			raise
		finally:
			conn.close()

	def _init_schema(self) -> None:
		with self._db() as conn:
			conn.executescript(
				"""
				CREATE TABLE IF NOT EXISTS runtime_meta (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				CREATE TABLE IF NOT EXISTS accounts (
					account_id TEXT PRIMARY KEY,
					display_name TEXT NOT NULL,
					bio TEXT NOT NULL DEFAULT '',
					created_tick INTEGER NOT NULL DEFAULT 0,
					follower_count INTEGER NOT NULL DEFAULT 0,
					following_count INTEGER NOT NULL DEFAULT 0,
					status TEXT NOT NULL DEFAULT 'active'
				);
				CREATE TABLE IF NOT EXISTS account_interests (
					account_id TEXT NOT NULL,
					tag TEXT NOT NULL,
					weight REAL NOT NULL DEFAULT 1.0,
					PRIMARY KEY (account_id, tag),
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS posts (
					post_id TEXT PRIMARY KEY,
					author_id TEXT NOT NULL,
					text TEXT NOT NULL,
					created_tick INTEGER NOT NULL DEFAULT 0,
					like_count INTEGER NOT NULL DEFAULT 0,
					comment_count INTEGER NOT NULL DEFAULT 0,
					repost_count INTEGER NOT NULL DEFAULT 0,
					status TEXT NOT NULL DEFAULT 'active',
					FOREIGN KEY (author_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS post_tags (
					post_id TEXT NOT NULL,
					tag TEXT NOT NULL,
					PRIMARY KEY (post_id, tag),
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS comments (
					comment_id TEXT PRIMARY KEY,
					post_id TEXT NOT NULL,
					author_id TEXT NOT NULL,
					text TEXT NOT NULL,
					created_tick INTEGER NOT NULL DEFAULT 0,
					like_count INTEGER NOT NULL DEFAULT 0,
					status TEXT NOT NULL DEFAULT 'active',
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE,
					FOREIGN KEY (author_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS likes (
					account_id TEXT NOT NULL,
					post_id TEXT NOT NULL,
					created_tick INTEGER NOT NULL DEFAULT 0,
					PRIMARY KEY (account_id, post_id),
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS reposts (
					repost_id TEXT PRIMARY KEY,
					account_id TEXT NOT NULL,
					post_id TEXT NOT NULL,
					text TEXT NOT NULL DEFAULT '',
					created_tick INTEGER NOT NULL DEFAULT 0,
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS follows (
					follower_id TEXT NOT NULL,
					followee_id TEXT NOT NULL,
					created_tick INTEGER NOT NULL DEFAULT 0,
					PRIMARY KEY (follower_id, followee_id),
					FOREIGN KEY (follower_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
					FOREIGN KEY (followee_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS feed_sessions (
					account_id TEXT PRIMARY KEY,
					cursor INTEGER NOT NULL DEFAULT 0,
					last_refresh_tick INTEGER NOT NULL DEFAULT 0,
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS exposures (
					exposure_id TEXT PRIMARY KEY,
					account_id TEXT NOT NULL,
					post_id TEXT NOT NULL,
					tick INTEGER NOT NULL DEFAULT 0,
					source TEXT NOT NULL DEFAULT '',
					score REAL NOT NULL DEFAULT 0,
					position INTEGER NOT NULL DEFAULT 0,
					seen_count INTEGER NOT NULL DEFAULT 1,
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS view_history (
					account_id TEXT NOT NULL,
					post_id TEXT NOT NULL,
					tick INTEGER NOT NULL DEFAULT 0,
					view_type TEXT NOT NULL DEFAULT 'post',
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
					FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS action_traces (
					trace_id TEXT PRIMARY KEY,
					account_id TEXT NOT NULL,
					operation TEXT NOT NULL,
					target_type TEXT NOT NULL DEFAULT '',
					target_id TEXT NOT NULL DEFAULT '',
					tick INTEGER NOT NULL DEFAULT 0,
					payload_json TEXT NOT NULL DEFAULT '{}',
					FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS checkpoint_snapshots (
					run_id TEXT NOT NULL,
					tick INTEGER NOT NULL,
					time_str TEXT NOT NULL DEFAULT '',
					snapshot_json TEXT NOT NULL,
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					PRIMARY KEY (run_id, tick)
				);
				CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
				CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_tick);
				CREATE INDEX IF NOT EXISTS idx_post_tags_tag ON post_tags(tag);
				CREATE INDEX IF NOT EXISTS idx_exposures_account_post ON exposures(account_id, post_id);
				"""
			)
			conn.execute(
				"INSERT INTO runtime_meta(key, value) VALUES('schema_version', ?) "
				"ON CONFLICT(key) DO UPDATE SET value=excluded.value",
				(SCHEMA_VERSION,),
			)

	def upsert_account(
		self,
		account_id: str,
		display_name: str,
		*,
		bio: str = "",
		interests: dict[str, float] | None = None,
		created_tick: int = 0,
	) -> None:
		aid = str(account_id or "").strip()
		name = str(display_name or "").strip()
		if not aid or not name:
			raise ValueError("account_id and display_name are required")
		with self._db() as conn:
			conn.execute(
				"""
				INSERT INTO accounts(account_id, display_name, bio, created_tick)
				VALUES(?, ?, ?, ?)
				ON CONFLICT(account_id) DO UPDATE SET
					display_name=excluded.display_name,
					bio=excluded.bio,
					status='active'
				""",
				(aid, name, str(bio or ""), int(created_tick or 0)),
			)
			if interests is not None:
				conn.execute("DELETE FROM account_interests WHERE account_id=?", (aid,))
				for tag, weight in dict(interests or {}).items():
					clean_tag = str(tag or "").strip()
					if clean_tag:
						conn.execute(
							"INSERT INTO account_interests(account_id, tag, weight) VALUES(?, ?, ?)",
							(aid, clean_tag, float(weight or 0.0)),
						)

	def invoke(self, operation: str, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		op = str(operation or "").strip()
		data = dict(payload or {})
		ctx = dict(context or {})
		try:
			if op == "observe_feed":
				return self._observe_feed(data, ctx)
			if op == "observe_post":
				return self._observe_post(data, ctx)
			if op == "create_post":
				return self._create_post(data, ctx)
			if op == "interact_post":
				return self._interact_post(data, ctx)
			if op == "follow_account":
				return self._follow_account(data, ctx)
		except Exception as exc:
			return executor_error(
				f"SQLiteSocialPlatformRuntime.{op}: {exc}",
				kind=ERROR_KIND_ENGINE,
				code="SOCIAL_PLATFORM_RUNTIME_EXCEPTION",
			)
		return executor_error(
			f"SQLiteSocialPlatformRuntime: unknown operation: {op}",
			kind=ERROR_KIND_CONTRACT,
			code="SOCIAL_PLATFORM_UNKNOWN_OPERATION",
		)

	def save_checkpoint(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		ctx = dict(context or {})
		run_id = str(ctx.get("run_id", "") or "").strip()
		if not run_id:
			return executor_error("Social platform checkpoint save: run_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_CHECKPOINT_RUN_ID_MISSING")
		tick = self._tick({}, ctx)
		time_str = str(ctx.get("time_str", "") or "")
		snapshot = self._snapshot_state()
		with self._db() as conn:
			conn.execute(
				"""
				INSERT INTO checkpoint_snapshots(run_id, tick, time_str, snapshot_json)
				VALUES(?, ?, ?, ?)
				ON CONFLICT(run_id, tick) DO UPDATE SET
					time_str=excluded.time_str,
					snapshot_json=excluded.snapshot_json,
					created_at=CURRENT_TIMESTAMP
				""",
				(run_id, tick, time_str, json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
			)
		return [{"type": "SocialRuntimeCheckpointSaved", "run_id": run_id, "tick": tick}]

	def restore_checkpoint(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		ctx = dict(context or {})
		run_id = str(ctx.get("run_id", "") or "").strip()
		if not run_id:
			return executor_error("Social platform checkpoint restore: run_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_CHECKPOINT_RUN_ID_MISSING")
		tick = self._tick({}, ctx)
		with self._db() as conn:
			row = conn.execute(
				"""
				SELECT snapshot_json FROM checkpoint_snapshots
				WHERE run_id=? AND tick=?
				""",
				(run_id, tick),
			).fetchone()
		if row is None:
			return executor_error(
				f"Social platform checkpoint restore: snapshot not found for {run_id}@{tick}",
				kind=ERROR_KIND_BUSINESS,
				code="SOCIAL_CHECKPOINT_NOT_FOUND",
			)
		snapshot = json.loads(str(row["snapshot_json"] or "{}"))
		self._restore_state(snapshot)
		return [{"type": "SocialRuntimeCheckpointRestored", "run_id": run_id, "tick": tick}]

	def _tick(self, payload: dict[str, Any], context: dict[str, Any]) -> int:
		for source in (payload, context):
			for key in ("tick", "current_tick"):
				if key in source:
					try:
						return int(source.get(key, 0) or 0)
					except Exception:
						return 0
		return 0

	def _account_id(self, payload: dict[str, Any], context: dict[str, Any]) -> str:
		return str(payload.get("account_id", context.get("account_id", "")) or "").strip()

	def _require_account(self, conn: sqlite3.Connection, account_id: str) -> sqlite3.Row | list[dict[str, Any]]:
		row = conn.execute("SELECT * FROM accounts WHERE account_id=? AND status='active'", (account_id,)).fetchone()
		if row is None:
			return executor_error(f"Social platform account missing: {account_id}", kind=ERROR_KIND_BUSINESS, code="SOCIAL_ACCOUNT_MISSING")
		return row

	def _require_post(self, conn: sqlite3.Connection, post_id: str) -> sqlite3.Row | list[dict[str, Any]]:
		row = conn.execute("SELECT * FROM posts WHERE post_id=? AND status='active'", (post_id,)).fetchone()
		if row is None:
			return executor_error(f"Social platform post missing: {post_id}", kind=ERROR_KIND_BUSINESS, code="SOCIAL_POST_MISSING")
		return row

	def _next_id(self, conn: sqlite3.Connection, prefix: str, table: str, column: str) -> str:
		count = int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] or 0) + 1
		return f"{prefix}_{count:06d}"

	def _tags_for_post(self, conn: sqlite3.Connection, post_id: str) -> list[str]:
		rows = conn.execute("SELECT tag FROM post_tags WHERE post_id=? ORDER BY tag", (post_id,)).fetchall()
		return [str(r["tag"]) for r in rows]

	def _account_name(self, conn: sqlite3.Connection, account_id: str) -> str:
		row = conn.execute("SELECT display_name FROM accounts WHERE account_id=?", (account_id,)).fetchone()
		return str(row["display_name"]) if row is not None else str(account_id)

	def _post_card(self, conn: sqlite3.Connection, row: sqlite3.Row, *, why_visible: str = "") -> dict[str, Any]:
		post_id = str(row["post_id"])
		text = str(row["text"] or "")
		author_id = str(row["author_id"])
		return {
			"post_id": post_id,
			"author_id": author_id,
			"author_display_name": self._account_name(conn, author_id),
			"summary": text[:80],
			"tags": self._tags_for_post(conn, post_id),
			"social_context": f"{int(row['like_count'] or 0)} likes, {int(row['comment_count'] or 0)} comments, {int(row['repost_count'] or 0)} reposts",
			"why_visible": why_visible,
		}

	def _trace(self, conn: sqlite3.Connection, account_id: str, operation: str, target_type: str, target_id: str, tick: int, payload: dict[str, Any]) -> None:
		trace_id = self._next_id(conn, "trace", "action_traces", "trace_id")
		conn.execute(
			"""
			INSERT INTO action_traces(trace_id, account_id, operation, target_type, target_id, tick, payload_json)
			VALUES(?, ?, ?, ?, ?, ?, ?)
			""",
			(trace_id, account_id, operation, target_type, target_id, tick, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
		)

	def _create_post(self, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		account_id = self._account_id(payload, context)
		text = str(payload.get("text", "") or "").strip()
		if not account_id:
			return executor_error("create_post: account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_ACCOUNT_ID_MISSING")
		if not text:
			return executor_error("create_post: text missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_POST_TEXT_MISSING")
		tick = self._tick(payload, context)
		tags = [str(x).strip() for x in list(payload.get("tags", []) or []) if str(x).strip()]
		with self._db() as conn:
			account = self._require_account(conn, account_id)
			if isinstance(account, list):
				return account
			post_id = str(payload.get("post_id", "") or "").strip() or self._next_id(conn, "post", "posts", "post_id")
			conn.execute(
				"INSERT INTO posts(post_id, author_id, text, created_tick) VALUES(?, ?, ?, ?)",
				(post_id, account_id, text, tick),
			)
			for tag in tags:
				conn.execute("INSERT OR IGNORE INTO post_tags(post_id, tag) VALUES(?, ?)", (post_id, tag))
			self._trace(conn, account_id, "create_post", "post", post_id, tick, payload)
		return [
			{
				"type": "SocialPostCreated",
				"account_id": account_id,
				"post_id": post_id,
				"text": text,
				"tags": tags,
				"tick": tick,
				"memory_hint": {"should_remember_by_default": True, "importance": 0.55},
			}
		]

	def _observe_feed(self, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		account_id = self._account_id(payload, context)
		if not account_id:
			return executor_error("observe_feed: account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_ACCOUNT_ID_MISSING")
		limit = max(1, min(20, int(payload.get("limit", 5) or 5)))
		tick = self._tick(payload, context)
		run_id = str(context.get("run_id", payload.get("run_id", "")) or "")
		with self._db() as conn:
			account = self._require_account(conn, account_id)
			if isinstance(account, list):
				return account
			session = conn.execute("SELECT cursor FROM feed_sessions WHERE account_id=?", (account_id,)).fetchone()
			cursor = int(session["cursor"] if session is not None else 0)
			scored = self._score_feed_candidates(conn, account_id, tick, cursor, run_id)
			items = scored[:limit]
			for pos, item in enumerate(items):
				exposure_id = self._next_id(conn, "exposure", "exposures", "exposure_id")
				conn.execute(
					"""
					INSERT INTO exposures(exposure_id, account_id, post_id, tick, source, score, position, seen_count)
					VALUES(?, ?, ?, ?, ?, ?, ?, 1)
					""",
					(exposure_id, account_id, item["post_id"], tick, item["why_visible"], float(item["score"]), pos),
				)
			conn.execute(
				"""
				INSERT INTO feed_sessions(account_id, cursor, last_refresh_tick)
				VALUES(?, ?, ?)
				ON CONFLICT(account_id) DO UPDATE SET
					cursor=excluded.cursor,
					last_refresh_tick=excluded.last_refresh_tick
				""",
				(account_id, cursor + 1, tick),
			)
			self._trace(conn, account_id, "observe_feed", "feed", account_id, tick, payload)
			cards = [self._post_card(conn, item["row"], why_visible=str(item["why_visible"])) for item in items]
		return [
			{
				"type": "SocialFeedObserved",
				"account_id": account_id,
				"items": cards,
				"cursor": cursor + 1,
				"tick": tick,
				"memory_hint": {"should_remember_by_default": False, "importance": 0.1},
			}
		]

	def _score_feed_candidates(self, conn: sqlite3.Connection, account_id: str, tick: int, cursor: int, run_id: str) -> list[dict[str, Any]]:
		interest_rows = conn.execute("SELECT tag, weight FROM account_interests WHERE account_id=?", (account_id,)).fetchall()
		interests = {str(r["tag"]): float(r["weight"] or 0.0) for r in interest_rows}
		followed = {
			str(r["followee_id"])
			for r in conn.execute("SELECT followee_id FROM follows WHERE follower_id=?", (account_id,)).fetchall()
		}
		rows = conn.execute(
			"SELECT * FROM posts WHERE status='active' AND created_tick <= ? ORDER BY created_tick DESC, post_id",
			(int(tick),),
		).fetchall()
		out: list[dict[str, Any]] = []
		for row in rows:
			post_id = str(row["post_id"])
			author_id = str(row["author_id"])
			tags = self._tags_for_post(conn, post_id)
			interest_match = sum(float(interests.get(tag, 0.0)) for tag in tags)
			if interests:
				interest_match = min(1.0, interest_match / max(1.0, sum(interests.values())))
			follow_boost = 1.0 if author_id in followed else 0.0
			age = max(0, int(tick) - int(row["created_tick"] or 0))
			freshness = 1.0 / (1.0 + age / 50.0)
			engagement = min(1.0, math.log1p(int(row["like_count"] or 0) + 2 * int(row["comment_count"] or 0) + 3 * int(row["repost_count"] or 0)) / 5.0)
			author_affinity = self._author_affinity(conn, account_id, author_id)
			exploration = self._stable_noise(run_id, account_id, post_id, tick, cursor)
			seen_count = int(
				conn.execute("SELECT COUNT(*) AS c FROM exposures WHERE account_id=? AND post_id=?", (account_id, post_id)).fetchone()["c"]
				or 0
			)
			seen_penalty = min(1.0, seen_count / 3.0)
			score = (
				2.0 * interest_match
				+ 1.5 * follow_boost
				+ 1.2 * freshness
				+ 1.0 * engagement
				+ 0.8 * author_affinity
				+ 0.4 * exploration
				- 2.0 * seen_penalty
			)
			source = "followed_author" if follow_boost else "interest_match" if interest_match > 0 else "hot_explore"
			out.append({"row": row, "post_id": post_id, "score": score, "why_visible": source})
		out.sort(key=lambda x: (-float(x["score"]), str(x["post_id"])))
		return out

	def _author_affinity(self, conn: sqlite3.Connection, account_id: str, author_id: str) -> float:
		row = conn.execute(
			"""
			SELECT COUNT(*) AS c
			FROM action_traces t
			JOIN posts p ON p.post_id=t.target_id
			WHERE t.account_id=? AND t.target_type='post' AND p.author_id=?
			""",
			(account_id, author_id),
		).fetchone()
		return min(1.0, float(row["c"] or 0) / 5.0)

	def _stable_noise(self, run_id: str, account_id: str, post_id: str, tick: int, cursor: int) -> float:
		seed = f"{run_id}|{account_id}|{post_id}|{int(tick)}|{int(cursor)}"
		digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
		return int(digest, 16) / 0xFFFFFFFF

	def _observe_post(self, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		account_id = self._account_id(payload, context)
		post_id = str(payload.get("post_id", "") or "").strip()
		if not account_id:
			return executor_error("observe_post: account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_ACCOUNT_ID_MISSING")
		if not post_id:
			return executor_error("observe_post: post_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_POST_ID_MISSING")
		tick = self._tick(payload, context)
		with self._db() as conn:
			account = self._require_account(conn, account_id)
			if isinstance(account, list):
				return account
			post = self._require_post(conn, post_id)
			if isinstance(post, list):
				return post
			conn.execute("INSERT INTO view_history(account_id, post_id, tick, view_type) VALUES(?, ?, ?, 'post')", (account_id, post_id, tick))
			self._trace(conn, account_id, "observe_post", "post", post_id, tick, payload)
			comments = [
				{
					"comment_id": str(r["comment_id"]),
					"author_id": str(r["author_id"]),
					"author_display_name": self._account_name(conn, str(r["author_id"])),
					"text": str(r["text"]),
					"like_count": int(r["like_count"] or 0),
				}
				for r in conn.execute(
					"SELECT * FROM comments WHERE post_id=? AND status='active' ORDER BY like_count DESC, created_tick DESC LIMIT 3",
					(post_id,),
				).fetchall()
			]
			post_payload = {
				"post_id": post_id,
				"author_id": str(post["author_id"]),
				"author_display_name": self._account_name(conn, str(post["author_id"])),
				"text": str(post["text"]),
				"tags": self._tags_for_post(conn, post_id),
				"metrics": {
					"likes": int(post["like_count"] or 0),
					"comments": int(post["comment_count"] or 0),
					"reposts": int(post["repost_count"] or 0),
				},
				"top_comments": comments,
			}
		return [
			{
				"type": "SocialPostObserved",
				"account_id": account_id,
				"post": post_payload,
				"tick": tick,
				"memory_hint": {"should_remember_by_default": True, "importance": 0.45},
			}
		]

	def _interact_post(self, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		account_id = self._account_id(payload, context)
		post_id = str(payload.get("post_id", "") or "").strip()
		action = str(payload.get("action", "") or "").strip()
		if not account_id:
			return executor_error("interact_post: account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_ACCOUNT_ID_MISSING")
		if not post_id:
			return executor_error("interact_post: post_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_POST_ID_MISSING")
		if action not in {"like", "unlike", "repost", "comment"}:
			return executor_error("interact_post: unsupported action", kind=ERROR_KIND_CONTRACT, code="SOCIAL_POST_ACTION_UNSUPPORTED")
		tick = self._tick(payload, context)
		detail: dict[str, Any] = {}
		with self._db() as conn:
			account = self._require_account(conn, account_id)
			if isinstance(account, list):
				return account
			post = self._require_post(conn, post_id)
			if isinstance(post, list):
				return post
			if action == "like":
				cur = conn.execute("INSERT OR IGNORE INTO likes(account_id, post_id, created_tick) VALUES(?, ?, ?)", (account_id, post_id, tick))
				if cur.rowcount:
					conn.execute("UPDATE posts SET like_count=like_count+1 WHERE post_id=?", (post_id,))
			elif action == "unlike":
				cur = conn.execute("DELETE FROM likes WHERE account_id=? AND post_id=?", (account_id, post_id))
				if cur.rowcount:
					conn.execute("UPDATE posts SET like_count=MAX(0, like_count-1) WHERE post_id=?", (post_id,))
			elif action == "comment":
				text = str(payload.get("text", "") or "").strip()
				if not text:
					return executor_error("interact_post.comment: text missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_COMMENT_TEXT_MISSING")
				comment_id = self._next_id(conn, "comment", "comments", "comment_id")
				conn.execute(
					"INSERT INTO comments(comment_id, post_id, author_id, text, created_tick) VALUES(?, ?, ?, ?, ?)",
					(comment_id, post_id, account_id, text, tick),
				)
				conn.execute("UPDATE posts SET comment_count=comment_count+1 WHERE post_id=?", (post_id,))
				detail = {"comment_id": comment_id, "text": text}
			elif action == "repost":
				text = str(payload.get("text", "") or "")
				repost_id = self._next_id(conn, "repost", "reposts", "repost_id")
				conn.execute(
					"INSERT INTO reposts(repost_id, account_id, post_id, text, created_tick) VALUES(?, ?, ?, ?, ?)",
					(repost_id, account_id, post_id, text, tick),
				)
				conn.execute("UPDATE posts SET repost_count=repost_count+1 WHERE post_id=?", (post_id,))
				detail = {"repost_id": repost_id, "text": text}
			self._trace(conn, account_id, f"interact_post.{action}", "post", post_id, tick, payload)
		importance = 0.35 if action in {"like", "unlike"} else 0.65
		return [
			{
				"type": "SocialPostInteracted",
				"account_id": account_id,
				"post_id": post_id,
				"action": action,
				"detail": detail,
				"tick": tick,
				"memory_hint": {"should_remember_by_default": action in {"comment", "repost"}, "importance": importance},
			}
		]

	def _follow_account(self, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		account_id = self._account_id(payload, context)
		target_id = str(payload.get("target_account_id", payload.get("followee_id", "")) or "").strip()
		if not account_id:
			return executor_error("follow_account: account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_ACCOUNT_ID_MISSING")
		if not target_id:
			return executor_error("follow_account: target_account_id missing", kind=ERROR_KIND_CONTRACT, code="SOCIAL_TARGET_ACCOUNT_ID_MISSING")
		if account_id == target_id:
			return executor_error("follow_account: cannot follow self", kind=ERROR_KIND_BUSINESS, code="SOCIAL_CANNOT_FOLLOW_SELF")
		tick = self._tick(payload, context)
		with self._db() as conn:
			account = self._require_account(conn, account_id)
			if isinstance(account, list):
				return account
			target = self._require_account(conn, target_id)
			if isinstance(target, list):
				return target
			cur = conn.execute("INSERT OR IGNORE INTO follows(follower_id, followee_id, created_tick) VALUES(?, ?, ?)", (account_id, target_id, tick))
			if cur.rowcount:
				conn.execute("UPDATE accounts SET following_count=following_count+1 WHERE account_id=?", (account_id,))
				conn.execute("UPDATE accounts SET follower_count=follower_count+1 WHERE account_id=?", (target_id,))
			self._trace(conn, account_id, "follow_account", "account", target_id, tick, payload)
			target_name = self._account_name(conn, target_id)
		return [
			{
				"type": "SocialAccountFollowed",
				"account_id": account_id,
				"target_account_id": target_id,
				"target_display_name": target_name,
				"tick": tick,
				"memory_hint": {"should_remember_by_default": True, "importance": 0.5},
			}
		]

	def _snapshot_state(self) -> dict[str, Any]:
		out: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tables": {}}
		with self._db() as conn:
			for table in DATA_TABLES:
				rows = conn.execute(f"SELECT * FROM {table}").fetchall()
				out["tables"][table] = [{str(k): row[k] for k in row.keys()} for row in rows]
		return out

	def _restore_state(self, snapshot: dict[str, Any]) -> None:
		tables = dict((snapshot or {}).get("tables", {}) or {})
		with self._db() as conn:
			conn.execute("PRAGMA foreign_keys = OFF")
			for table in reversed(DATA_TABLES):
				conn.execute(f"DELETE FROM {table}")
			for table in DATA_TABLES:
				rows = list(tables.get(table, []) or [])
				if not rows:
					continue
				for row in rows:
					if not isinstance(row, dict):
						continue
					cols = [str(k) for k in row.keys()]
					placeholders = ", ".join("?" for _ in cols)
					conn.execute(
						f"INSERT INTO {table}({', '.join(cols)}) VALUES({placeholders})",
						[row.get(c) for c in cols],
					)
			conn.execute("PRAGMA foreign_keys = ON")
