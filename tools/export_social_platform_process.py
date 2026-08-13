from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TABLES = (
	"accounts",
	"account_interests",
	"posts",
	"post_ranking_topics",
	"post_display_hashtags",
	"follows",
	"feed_sessions",
	"exposures",
	"reposts",
	"likes",
	"comments",
)


def _connect(path: Path) -> sqlite3.Connection:
	conn = sqlite3.connect(path)
	conn.row_factory = sqlite3.Row
	return conn


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
	return [dict(row) for row in conn.execute(query, params)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	fieldnames: list[str] = []
	seen: set[str] = set()
	for row in rows:
		for key in row:
			if key not in seen:
				seen.add(key)
				fieldnames.append(key)
	with path.open("w", encoding="utf-8", newline="") as stream:
		writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
	order_by = {
		"accounts": "account_id",
		"account_interests": "account_id, topic",
		"posts": "created_tick, post_id",
		"post_ranking_topics": "post_id, topic",
		"post_display_hashtags": "post_id, position",
		"follows": "follower_id, followee_id",
		"feed_sessions": "tick, feed_session_id",
		"exposures": "tick, exposure_id",
		"reposts": "created_tick, repost_id",
		"likes": "created_tick, account_id, post_id",
		"comments": "created_tick, comment_id",
	}[table]
	return _rows(conn, f"SELECT * FROM {table} ORDER BY {order_by}")


def _condition_by_post(conn: sqlite3.Connection) -> dict[str, str]:
	return {str(row["post_id"]): str(row["condition_id"]) for row in conn.execute("SELECT post_id, condition_id FROM posts")}


def _repost_depths(reposts: list[dict[str, Any]], exposures_by_id: dict[int, dict[str, Any]]) -> dict[int, int]:
	by_account_post = {(str(row["account_id"]), str(row["post_id"])): row for row in reposts}
	depth_by_repost: dict[int, int] = {}

	def depth_for(row: dict[str, Any]) -> int:
		repost_id = int(row["repost_id"])
		if repost_id in depth_by_repost:
			return depth_by_repost[repost_id]
		source = exposures_by_id.get(int(row["source_exposure_id"]))
		parent_depth = 0
		if source and str(source.get("source_kind", "")) == "followed_repost":
			parent = by_account_post.get((str(source.get("source_account_id", "")), str(row["post_id"])))
			if parent is not None and int(parent["repost_id"]) != repost_id:
				parent_depth = depth_for(parent)
		depth_by_repost[repost_id] = parent_depth + 1
		return depth_by_repost[repost_id]

	for repost in reposts:
		depth_for(repost)
	return depth_by_repost


def _derived_exports(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
	conditions = _condition_by_post(conn)
	exposures = _table_rows(conn, "exposures")
	reposts = _table_rows(conn, "reposts")
	likes = _table_rows(conn, "likes")
	comments = _table_rows(conn, "comments")
	feed_sessions = _table_rows(conn, "feed_sessions")
	exposures_by_id = {int(row["exposure_id"]): row for row in exposures}
	depth_by_repost = _repost_depths(reposts, exposures_by_id)
	repost_by_account_post = {(str(row["account_id"]), str(row["post_id"])): row for row in reposts}

	first_exposure_key: set[tuple[str, str]] = set()
	exposure_process: list[dict[str, Any]] = []
	for exposure in exposures:
		account_id = str(exposure["account_id"])
		post_id = str(exposure["post_id"])
		key = (account_id, post_id)
		first = key not in first_exposure_key
		first_exposure_key.add(key)
		source_repost = repost_by_account_post.get((str(exposure["source_account_id"]), post_id))
		source_depth = depth_by_repost.get(int(source_repost["repost_id"]), 0) if source_repost else 0
		exposure_process.append(
			{
				"exposure_id": int(exposure["exposure_id"]),
				"feed_session_id": int(exposure["feed_session_id"]),
				"tick": int(exposure["tick"]),
				"account_id": account_id,
				"post_id": post_id,
				"condition_id": conditions.get(post_id, ""),
				"is_first_account_post_exposure": int(first),
				"source_kind": str(exposure["source_kind"]),
				"source_account_id": str(exposure["source_account_id"]),
				"section": str(exposure["section"]),
				"position": int(exposure["position"]),
				"source_repost_depth": int(source_depth),
			}
		)

	repost_process: list[dict[str, Any]] = []
	for repost in reposts:
		source = exposures_by_id.get(int(repost["source_exposure_id"]), {})
		repost_process.append(
			{
				"repost_id": int(repost["repost_id"]),
				"tick": int(repost["created_tick"]),
				"account_id": str(repost["account_id"]),
				"post_id": str(repost["post_id"]),
				"condition_id": conditions.get(str(repost["post_id"]), ""),
				"source_exposure_id": int(repost["source_exposure_id"]),
				"source_kind": str(source.get("source_kind", "")),
				"source_account_id": str(source.get("source_account_id", "")),
				"cascade_depth": int(depth_by_repost[int(repost["repost_id"])]),
			}
		)

	by_tick: dict[int, Counter[str]] = defaultdict(Counter)
	for session in feed_sessions:
		by_tick[int(session["tick"])]["feed_sessions"] += 1
	for exposure in exposure_process:
		tick = int(exposure["tick"])
		by_tick[tick]["exposures"] += 1
		by_tick[tick]["first_exposures"] += int(exposure["is_first_account_post_exposure"])
	for row in likes:
		by_tick[int(row["created_tick"])]["likes"] += 1
	for row in comments:
		by_tick[int(row["created_tick"])]["comments"] += 1
	for row in repost_process:
		by_tick[int(row["tick"])]["reposts"] += 1
	summary_by_tick = [
		{
			"tick": tick,
			"feed_sessions": counts["feed_sessions"],
			"exposures": counts["exposures"],
			"first_exposures": counts["first_exposures"],
			"likes": counts["likes"],
			"comments": counts["comments"],
			"reposts": counts["reposts"],
			"cumulative_reposts": sum(by_tick[past]["reposts"] for past in sorted(by_tick) if past <= tick),
		}
		for tick, counts in sorted(by_tick.items())
	]
	return {
		"exposure_process": exposure_process,
		"repost_process": repost_process,
		"summary_by_tick": summary_by_tick,
	}


def export(database_path: Path, output_dir: Path) -> dict[str, Any]:
	conn = _connect(database_path)
	try:
		meta = {str(row["key"]): str(row["value"]) for row in conn.execute("SELECT key, value FROM platform_meta")}
		if meta.get("schema_version") != "social_platform.v3":
			raise ValueError("exporter requires social_platform.v3")
		table_counts: dict[str, int] = {}
		for table in TABLES:
			rows = _table_rows(conn, table)
			table_counts[table] = len(rows)
			_write_csv(output_dir / "tables" / f"{table}.csv", rows)
		derived = _derived_exports(conn)
		for name, rows in derived.items():
			_write_csv(output_dir / f"{name}.csv", rows)
		manifest = {
			"schema_version": "social_platform_process_export.v1",
			"source_database": str(database_path.resolve()),
			"platform_schema_version": meta["schema_version"],
			"table_counts": table_counts,
			"derived_counts": {name: len(rows) for name, rows in derived.items()},
		}
		_write_json(output_dir / "manifest.json", manifest)
		return manifest
	finally:
		conn.close()


def main() -> None:
	parser = argparse.ArgumentParser(description="Export raw social-platform process facts from a social_platform.v3 SQLite database.")
	parser.add_argument("--database", required=True, help="Path to platform.sqlite")
	parser.add_argument("--out", required=True, help="Output directory for CSV files and manifest.json")
	args = parser.parse_args()
	manifest = export(Path(args.database), Path(args.out))
	print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
