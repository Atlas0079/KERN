from __future__ import annotations

from pathlib import Path
from typing import Any

from .social_platform import SQLiteSocialPlatformRuntime


def _as_list(value: Any) -> list[Any]:
	return list(value or []) if isinstance(value, list) else []


def _clean_str(value: Any) -> str:
	return str(value or "").strip()


def seed_social_platform_runtime(runtime: SQLiteSocialPlatformRuntime, seed: dict[str, Any]) -> None:
	"""
	Apply deterministic initial social-platform data.

	This is intentionally a data seeding helper, not runtime behavior. It can be
	called during config-time adapter construction and kept out of effect handlers.
	"""

	data = dict(seed or {}) if isinstance(seed, dict) else {}
	for account in _as_list(data.get("accounts", [])):
		if not isinstance(account, dict):
			continue
		runtime.upsert_account(
			_clean_str(account.get("account_id")),
			_clean_str(account.get("display_name")),
			bio=str(account.get("bio", "") or ""),
			interests=dict(account.get("interests", {}) or {}) if isinstance(account.get("interests", {}), dict) else {},
			created_tick=int(account.get("created_tick", 0) or 0),
		)
	for post in build_seed_posts(data):
		post_id = _clean_str(post.get("post_id"))
		if post_id and _post_exists(runtime, post_id):
			continue
		events = runtime.invoke(
			"create_post",
			{
				"account_id": _clean_str(post.get("account_id") or post.get("author_id")),
				"post_id": post_id,
				"text": str(post.get("text", "") or ""),
				"tags": [str(x).strip() for x in _as_list(post.get("tags", [])) if str(x).strip()],
				"tick": int(post.get("tick", post.get("created_tick", 0)) or 0),
			},
			{},
		)
		if events and str(events[0].get("type", "") or "") == "ExecutorError":
			raise RuntimeError(str(events[0].get("message", events[0]) or events[0]))
	for follow in _as_list(data.get("follows", [])):
		if not isinstance(follow, dict):
			continue
		events = runtime.invoke(
			"follow_account",
			{
				"account_id": _clean_str(follow.get("follower_id") or follow.get("account_id")),
				"target_account_id": _clean_str(follow.get("followee_id") or follow.get("target_account_id")),
				"tick": int(follow.get("tick", 0) or 0),
			},
			{},
		)
		if events and str(events[0].get("type", "") or "") == "ExecutorError":
			raise RuntimeError(str(events[0].get("message", events[0]) or events[0]))


def build_seed_posts(seed: dict[str, Any]) -> list[dict[str, Any]]:
	"""
	Build initial posts from explicit rows plus lightweight topic generators.

	Generator shape:
	{
	  "author_id": "acc_teacher",
	  "post_id_prefix": "post_notice",
	  "tick": 1,
	  "tags": ["school"],
	  "texts": ["...", "..."]
	}
	"""

	data = dict(seed or {}) if isinstance(seed, dict) else {}
	out = [dict(x) for x in _as_list(data.get("posts", [])) if isinstance(x, dict)]
	for gen in _as_list(data.get("post_generators", [])):
		if not isinstance(gen, dict):
			continue
		author_id = _clean_str(gen.get("author_id") or gen.get("account_id"))
		prefix = _clean_str(gen.get("post_id_prefix")) or f"post_{author_id or 'seed'}"
		base_tick = int(gen.get("tick", gen.get("created_tick", 0)) or 0)
		tags = [str(x).strip() for x in _as_list(gen.get("tags", [])) if str(x).strip()]
		for idx, text in enumerate(_as_list(gen.get("texts", [])), start=1):
			clean_text = str(text or "").strip()
			if not author_id or not clean_text:
				continue
			out.append(
				{
					"account_id": author_id,
					"post_id": f"{prefix}_{idx:03d}",
					"text": clean_text,
					"tags": list(tags),
					"tick": base_tick + idx - 1,
				}
			)
	return out


def _post_exists(runtime: SQLiteSocialPlatformRuntime, post_id: str) -> bool:
	with runtime._db() as conn:
		row = conn.execute("SELECT 1 FROM posts WHERE post_id=? LIMIT 1", (str(post_id),)).fetchone()
	return row is not None


def seed_social_platform_runtime_from_file(runtime: SQLiteSocialPlatformRuntime, seed_path: str | Path) -> None:
	import json

	path = Path(seed_path)
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict):
		raise ValueError(f"social seed must be a JSON object: {path}")
	seed_social_platform_runtime(runtime, data)
