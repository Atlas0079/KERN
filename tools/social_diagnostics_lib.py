from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RUMOR_TAGS = {"rumor"}
DEFAULT_CLARIFICATION_TAGS = {"clarification"}


@dataclass(frozen=True)
class RunPaths:
	run_dir: Path
	social_db: Path | None
	simulation_log: Path | None


def resolve_run_paths(run_dir: str | Path, social_db: str | Path = "", simulation_log: str | Path = "") -> RunPaths:
	base = Path(run_dir).resolve()
	db = Path(social_db).resolve() if str(social_db or "").strip() else base / "social.sqlite3"
	log = Path(simulation_log).resolve() if str(simulation_log or "").strip() else base / "simulation_log.json"
	return RunPaths(
		run_dir=base,
		social_db=db if db.exists() else None,
		simulation_log=log if log.exists() else None,
	)


def parse_tags(raw: str | Iterable[str], defaults: set[str]) -> set[str]:
	if isinstance(raw, str):
		items = [x.strip() for x in raw.split(",")]
	else:
		items = [str(x).strip() for x in list(raw or [])]
	out = {x for x in items if x}
	return out or set(defaults)


def connect_social_db(db_path: Path) -> sqlite3.Connection:
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
	row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
	return row is not None


def count_rows(conn: sqlite3.Connection, table: str) -> int:
	if not table_exists(conn, table):
		return 0
	return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] or 0)


def load_simulation_log(log_path: Path | None) -> dict[str, Any]:
	if log_path is None or not log_path.exists():
		return {"meta": {}, "log": []}
	try:
		data = json.loads(log_path.read_text(encoding="utf-8"))
	except Exception:
		return {"meta": {}, "log": []}
	if not isinstance(data, dict):
		return {"meta": {}, "log": []}
	rows = data.get("log", []) or []
	return {
		"meta": dict(data.get("meta", {}) or {}) if isinstance(data.get("meta", {}), dict) else {},
		"log": [dict(x) for x in rows if isinstance(x, dict)] if isinstance(rows, list) else [],
	}


def classify_posts(conn: sqlite3.Connection, rumor_tags: set[str], clarification_tags: set[str]) -> dict[str, set[str]]:
	classes: dict[str, set[str]] = {"rumor": set(), "clarification": set(), "other": set()}
	if not table_exists(conn, "posts"):
		return classes
	rows = conn.execute(
		"""
		SELECT p.post_id, GROUP_CONCAT(pt.tag) AS tags
		FROM posts p
		LEFT JOIN post_tags pt ON pt.post_id=p.post_id
		GROUP BY p.post_id
		"""
	).fetchall()
	for row in rows:
		post_id = str(row["post_id"] or "")
		tags = {x.strip() for x in str(row["tags"] or "").split(",") if x.strip()}
		if tags & rumor_tags:
			classes["rumor"].add(post_id)
		elif tags & clarification_tags:
			classes["clarification"].add(post_id)
		else:
			classes["other"].add(post_id)
	return classes


def _post_class(post_id: str, classes: dict[str, set[str]]) -> str:
	if post_id in classes.get("rumor", set()):
		return "rumor"
	if post_id in classes.get("clarification", set()):
		return "clarification"
	return "other"


def social_summary(conn: sqlite3.Connection, rumor_tags: set[str], clarification_tags: set[str]) -> dict[str, Any]:
	classes = classify_posts(conn, rumor_tags, clarification_tags)
	out: dict[str, Any] = {
		"table_counts": {table: count_rows(conn, table) for table in [
			"accounts",
			"posts",
			"comments",
			"likes",
			"reposts",
			"follows",
			"exposures",
			"view_history",
			"action_traces",
		]},
		"post_classes": {k: len(v) for k, v in classes.items()},
		"class_post_ids": {k: sorted(v) for k, v in classes.items()},
	}

	for table, column in [("exposures", "post_id"), ("view_history", "post_id"), ("likes", "post_id"), ("comments", "post_id"), ("reposts", "post_id")]:
		counter: Counter[str] = Counter()
		account_counter: dict[str, set[str]] = defaultdict(set)
		if table_exists(conn, table):
			account_col = "author_id" if table == "comments" else "account_id"
			for row in conn.execute(f"SELECT {account_col} AS account_id, {column} AS post_id FROM {table}").fetchall():
				pid = str(row["post_id"] or "")
				cls = _post_class(pid, classes)
				counter[cls] += 1
				account_counter[cls].add(str(row["account_id"] or ""))
		out[f"{table}_by_class"] = dict(counter)
		out[f"{table}_accounts_by_class"] = {k: len(v) for k, v in account_counter.items()}

	if table_exists(conn, "action_traces"):
		out["operations"] = {
			str(row["operation"]): int(row["c"] or 0)
			for row in conn.execute("SELECT operation, COUNT(*) AS c FROM action_traces GROUP BY operation ORDER BY c DESC").fetchall()
		}
		out["operations_by_tick"] = [
			{"tick": int(row["tick"] or 0), "operation": str(row["operation"] or ""), "count": int(row["c"] or 0)}
			for row in conn.execute("SELECT tick, operation, COUNT(*) AS c FROM action_traces GROUP BY tick, operation ORDER BY tick, operation").fetchall()
		]
	else:
		out["operations"] = {}
		out["operations_by_tick"] = []

	if table_exists(conn, "exposures"):
		out["exposures_by_tick_class"] = []
		for row in conn.execute("SELECT tick, post_id, COUNT(*) AS c FROM exposures GROUP BY tick, post_id ORDER BY tick").fetchall():
			out["exposures_by_tick_class"].append(
				{"tick": int(row["tick"] or 0), "class": _post_class(str(row["post_id"] or ""), classes), "count": int(row["c"] or 0)}
			)
	else:
		out["exposures_by_tick_class"] = []

	return out


def agent_rows(conn: sqlite3.Connection, rumor_tags: set[str], clarification_tags: set[str]) -> list[dict[str, Any]]:
	classes = classify_posts(conn, rumor_tags, clarification_tags)
	account_names = {}
	if table_exists(conn, "accounts"):
		for row in conn.execute("SELECT account_id, display_name FROM accounts ORDER BY account_id").fetchall():
			account_names[str(row["account_id"] or "")] = str(row["display_name"] or "")
	account_ids = set(account_names.keys())
	for table in ["exposures", "view_history", "action_traces", "likes", "reposts", "comments"]:
		if not table_exists(conn, table):
			continue
		account_col = "author_id" if table == "comments" else "account_id"
		for row in conn.execute(f"SELECT DISTINCT {account_col} AS account_id FROM {table}").fetchall():
			account_ids.add(str(row["account_id"] or ""))

	rows: list[dict[str, Any]] = []
	for account_id in sorted(x for x in account_ids if x):
		row: dict[str, Any] = {"account_id": account_id, "display_name": account_names.get(account_id, "")}
		for cls in ["rumor", "clarification", "other"]:
			post_ids = classes.get(cls, set())
			if post_ids:
				placeholders = ",".join("?" for _ in post_ids)
				args = [account_id, *sorted(post_ids)]
				row[f"{cls}_exposures"] = _count_where(conn, "exposures", "account_id=? AND post_id IN (" + placeholders + ")", args)
				row[f"{cls}_views"] = _count_where(conn, "view_history", "account_id=? AND post_id IN (" + placeholders + ")", args)
				row[f"{cls}_likes"] = _count_where(conn, "likes", "account_id=? AND post_id IN (" + placeholders + ")", args)
				row[f"{cls}_reposts"] = _count_where(conn, "reposts", "account_id=? AND post_id IN (" + placeholders + ")", args)
				row[f"{cls}_comments"] = _count_where(conn, "comments", "author_id=? AND post_id IN (" + placeholders + ")", args)
			else:
				for metric in ["exposures", "views", "likes", "reposts", "comments"]:
					row[f"{cls}_{metric}"] = 0
		row["posts_created"] = _count_where(conn, "posts", "author_id=?", [account_id])
		row["actions_total"] = _count_where(conn, "action_traces", "account_id=?", [account_id])
		rows.append(row)
	return rows


def _count_where(conn: sqlite3.Connection, table: str, where: str, args: list[Any]) -> int:
	if not table_exists(conn, table):
		return 0
	return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", args).fetchone()["c"] or 0)


def runtime_health(log_rows: list[dict[str, Any]]) -> dict[str, Any]:
	event_counts: Counter[str] = Counter()
	error_rows: list[dict[str, Any]] = []
	gate_rows: list[dict[str, Any]] = []
	opportunity_rows: list[dict[str, Any]] = []
	interaction_status: Counter[str] = Counter()
	for row in log_rows:
		if str(row.get("kind", "") or "") == "interaction":
			interaction_status[str(row.get("status", "") or "unknown")] += 1
		etype = str(row.get("type", "") or "")
		if etype:
			event_counts[etype] += 1
		if etype == "ExecutorError" or "Error" in etype or str(row.get("kind", "") or "") == "error":
			error_rows.append(dict(row))
		if etype == "SocialActivityGateEvaluated":
			gate_rows.append(dict(row))
		if etype == "SocialActivityOpportunityGranted":
			opportunity_rows.append(dict(row))
	skipped: Counter[str] = Counter()
	selected_total = 0
	candidate_total = 0
	for row in gate_rows:
		selected_total += int(row.get("selected_count", 0) or 0)
		candidate_total += int(row.get("candidate_count", 0) or 0)
		for key, value in dict(row.get("skipped", {}) or {}).items():
			skipped[str(key)] += int(value or 0)
	return {
		"event_counts": dict(event_counts),
		"interaction_status": dict(interaction_status),
		"error_count": len(error_rows),
		"error_samples": error_rows[:10],
		"gate_tick_count": len(gate_rows),
		"gate_candidate_total": candidate_total,
		"gate_selected_total": selected_total,
		"gate_skipped": dict(skipped),
		"opportunity_count": len(opportunity_rows),
		"decision_modes": dict(Counter(str(x.get("decision_mode", "") or "") for x in gate_rows)),
	}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	keys: list[str] = []
	seen: set[str] = set()
	for row in rows:
		for key in row.keys():
			if key not in seen:
				seen.add(key)
				keys.append(key)
	with path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=keys)
		writer.writeheader()
		for row in rows:
			writer.writerow(row)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
	if not rows:
		return "(none)"
	header = "| " + " | ".join(columns) + " |"
	sep = "| " + " | ".join("---" for _ in columns) + " |"
	body = []
	for row in rows:
		body.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
	return "\n".join([header, sep, *body])
