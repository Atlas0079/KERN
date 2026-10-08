from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from KERN.external_runtime_catalog import ExternalRuntimeSpec
from KERN.external_runtimes import SQLiteSocialPlatform
from KERN.external_runtimes.social_platform import FeedRecommendationContext, HybridFeedRecommender
from KERN.package_definitions import package_external_runtime


class ExperimentalFeedRecommender(HybridFeedRecommender):
	"""Keep background interactions factual without amplifying their distribution."""

	def __init__(self, propagating_post_ids: list[str]) -> None:
		if (
			not isinstance(propagating_post_ids, list)
			or not propagating_post_ids
			or any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in propagating_post_ids)
			or len(set(propagating_post_ids)) != len(propagating_post_ids)
		):
			raise ValueError("propagating_post_ids must be a non-empty list of unique trimmed post IDs")
		self.propagating_post_ids = frozenset(propagating_post_ids)

	def select_page(self, context: FeedRecommendationContext, *, original_cards: list[dict[str, Any]], repost_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
		adjusted_cards: list[dict[str, Any]] = []
		for original in original_cards:
			card = dict(original)
			if str(card["post_id"]) not in self.propagating_post_ids:
				# Retain the existing interest/follow/freshness terms, without engagement.
				freshness = 1.0 / (1.0 + max(0, context.tick - int(card["created_tick"])))
				card["score"] = 0.0 if card["previously_exposed"] else (
					2.0 * float(card["_interest_score"])
					+ 1.5 * float(card["source_kind"] == "followed_author") + freshness
				)
				card["_engagement_score"] = 0.0
				card["_hot_score"] = freshness
			adjusted_cards.append(card)
		return super().select_page(
			context,
			original_cards=adjusted_cards,
			repost_cards=[card for card in repost_cards if str(card["post_id"]) in self.propagating_post_ids],
		)


class SQLiteSocialPlatformAdapter:
	"""KERN lifecycle and operation adapter for the standalone SQLite platform."""

	_WRITE_OPERATIONS = frozenset({"open_feed_session", "repost", "like", "comment"})

	def __init__(self, context: dict[str, Any], options: dict[str, Any]) -> None:
		unknown = set(options).difference({"database_path", "seed_path", "propagating_post_ids"})
		if unknown:
			raise ValueError(f"sqlite social platform has unknown options: {sorted(unknown)}")
		project_root = Path(str(context.get("project_root", "") or "")).resolve()
		if not project_root.is_dir():
			raise ValueError("sqlite social platform requires a valid project_root")
		self.runtime_id = str(context.get("runtime_id", "") or "").strip()
		if not self.runtime_id:
			raise ValueError("sqlite social platform runtime_id must not be blank")
		self.database_path = self._resolve_path(project_root, options.get("database_path"), "database_path")
		self.seed_path = self._resolve_path(project_root, options.get("seed_path"), "seed_path")
		self.checkpoint_root = Path(str(context.get("checkpoint_dir", "") or "")).resolve() / "external_runtimes" / self.runtime_id
		restore_path = str(context.get("restore_path", "") or "").strip()
		self.restore_requested = bool(restore_path)
		self.restore_checkpoint_root = self._restore_checkpoint_root(restore_path, self.runtime_id) if restore_path else None
		recommender = None
		if "propagating_post_ids" in options:
			recommender = ExperimentalFeedRecommender(options["propagating_post_ids"])
			seed = json.loads(self.seed_path.read_text(encoding="utf-8"))
			post_ids = {post["post_id"] for post in seed["posts"]}
			missing = recommender.propagating_post_ids - post_ids
			if missing:
				raise ValueError(f"propagating_post_ids are missing from seed: {sorted(missing)}")
		self.platform = SQLiteSocialPlatform(self.database_path, checkpoint_dir=self.checkpoint_root, recommender=recommender)
		self._active_transaction_id = ""

	@staticmethod
	def _resolve_path(project_root: Path, raw: Any, label: str) -> Path:
		text = str(raw or "").strip()
		if not text:
			raise ValueError(f"sqlite social platform option {label} must not be blank")
		candidate = Path(text)
		return (project_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

	@staticmethod
	def _restore_checkpoint_root(restore_path: str, runtime_id: str) -> Path:
		source = Path(restore_path).resolve()
		if source.is_file() and source.parent.name == "snapshots":
			source = source.parent.parent
		return source / "external_runtimes" / runtime_id

	def start(self, _context: dict[str, Any]) -> list[dict[str, Any]]:
		if not self.restore_requested:
			if any(self.platform.counts().values()):
				raise ValueError("sqlite social platform database must be empty at run start")
			self.platform.seed_from_file(self.seed_path)
		return [{"type": "SocialPlatformStarted", "runtime_id": self.runtime_id}]

	def close(self, _context: dict[str, Any]) -> list[dict[str, Any]]:
		self.platform.close()
		self._active_transaction_id = ""
		return [{"type": "SocialPlatformClosed", "runtime_id": self.runtime_id}]

	def invoke(self, operation: str, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
		op = str(operation or "").strip()
		data = dict(payload or {})
		tick = int(data.get("tick"))
		transaction_id = str(context.get("external_transaction_id", "") or "").strip()
		if op in self._WRITE_OPERATIONS:
			self._join_transaction(transaction_id)
		if op == "recommend_feed":
			items = self.platform.recommend_feed(str(data.get("account_id", "")), tick=tick, limit=int(data.get("limit")))
			return [{"type": "SocialFeedRecommended", "account_id": str(data.get("account_id", "")), "tick": tick, "feed_items": items}]
		if op == "open_feed_session":
			session = self.platform.open_feed_session(
				str(data.get("account_id", "")),
				tick=tick,
				limit=int(data.get("limit")),
				transaction_id=transaction_id,
			)
			return [
				{"type": "SocialFeedOpened", **session},
				*[
					{
						"type": "SocialPostExposed",
						"feed_session_id": int(session["feed_session_id"]),
						**{key: item[key] for key in ("exposure_id", "post_id", "source_kind", "source_account_id", "section", "position")},
						"account_id": str(session["account_id"]),
						"tick": int(session["tick"]),
					}
					for item in session["feed_items"]
				],
			]
		if op == "open_post_detail":
			detail = self.platform.post_detail(
				str(data.get("account_id", "")),
				str(data.get("post_id", "")),
				source_exposure_id=int(data.get("source_exposure_id")),
				tick=tick,
				recent_comments_limit=int(data.get("recent_comments_limit", 5)),
			)
			return [{"type": "SocialPostDetailOpened", **detail}]
		if op == "repost":
			record = self.platform.repost(
				str(data.get("account_id", "")),
				str(data.get("post_id", "")),
				source_exposure_id=int(data.get("source_exposure_id")),
				tick=tick,
				text=str(data.get("text", "") or ""),
				transaction_id=transaction_id,
			)
			return [{"type": "SocialPostReposted", **record}]
		if op == "like":
			record = self.platform.like(
				str(data.get("account_id", "")),
				str(data.get("post_id", "")),
				source_exposure_id=int(data.get("source_exposure_id")),
				tick=tick,
				transaction_id=transaction_id,
			)
			return [{"type": "SocialPostLiked", **record}]
		if op == "comment":
			record = self.platform.comment(
				str(data.get("account_id", "")),
				str(data.get("post_id", "")),
				source_exposure_id=int(data.get("source_exposure_id")),
				text=str(data.get("text", "") or ""),
				tick=tick,
				transaction_id=transaction_id,
			)
			return [{"type": "SocialCommentCreated", **record}]
		if op == "metrics":
			return [{"type": "SocialMetricsObserved", "tick": tick, "metrics": self.platform.metrics()}]
		raise ValueError(f"unsupported social platform operation: {op}")

	def _join_transaction(self, transaction_id: str) -> None:
		if not transaction_id:
			raise ValueError("social platform write requires external_transaction_id")
		if not self._active_transaction_id:
			self.platform.begin_transaction(transaction_id)
			self._active_transaction_id = transaction_id
			return
		if self._active_transaction_id != transaction_id:
			raise ValueError("social platform transaction_id does not match active bundle")

	def commit_bundle(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		transaction_id = str(context.get("transaction_id", "") or "").strip()
		if not self._active_transaction_id:
			return []
		self.platform.commit_transaction(transaction_id)
		self._active_transaction_id = ""
		return [{"type": "SocialPlatformBundleCommitted", "transaction_id": transaction_id}]

	def rollback_bundle(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		transaction_id = str(context.get("transaction_id", "") or "").strip()
		if not self._active_transaction_id:
			return []
		self.platform.rollback_transaction(transaction_id)
		self._active_transaction_id = ""
		return [{"type": "SocialPlatformBundleRolledBack", "transaction_id": transaction_id}]

	def save_checkpoint(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		path = self.platform.save_checkpoint(str(context.get("run_id", "")), tick=int(context.get("tick")))
		return [{"type": "SocialPlatformCheckpointSaved", "tick": int(context.get("tick")), "path": str(path)}]

	def restore_checkpoint(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		if self.restore_checkpoint_root is None:
			raise ValueError("social platform restore source is unavailable")
		self.platform.checkpoint_dir = self.restore_checkpoint_root
		try:
			self.platform.restore_checkpoint(str(context.get("run_id", "")), tick=int(context.get("tick")))
		finally:
			self.platform.checkpoint_dir = self.checkpoint_root
		return [{"type": "SocialPlatformCheckpointRestored", "tick": int(context.get("tick"))}]


def _create_sqlite_social_platform(context: dict[str, Any], options: dict[str, Any]) -> SQLiteSocialPlatformAdapter:
	return SQLiteSocialPlatformAdapter(dict(context), dict(options))


@package_external_runtime(
	ExternalRuntimeSpec(
		provider_id="social_propagation:sqlite_platform",
		factory=_create_sqlite_social_platform,
	)
)
def sqlite_social_platform_runtime() -> None:
	pass
