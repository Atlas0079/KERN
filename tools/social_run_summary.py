from __future__ import annotations

import argparse
import json
from pathlib import Path

from social_diagnostics_lib import (
	DEFAULT_CLARIFICATION_TAGS,
	DEFAULT_RUMOR_TAGS,
	connect_social_db,
	load_simulation_log,
	markdown_table,
	parse_tags,
	resolve_run_paths,
	runtime_health,
	social_summary,
	write_csv,
)


def _top_posts(summary: dict, class_name: str, limit: int = 10) -> list[dict]:
	post_ids = list((summary.get("class_post_ids", {}) or {}).get(class_name, []) or [])
	return [{"class": class_name, "post_id": pid} for pid in post_ids[:limit]]


def build_report(run_dir: Path, summary: dict, health: dict, has_log: bool, has_db: bool) -> str:
	lines: list[str] = []
	lines.append(f"# Social Run Summary")
	lines.append("")
	lines.append(f"- run_dir: `{run_dir}`")
	lines.append(f"- social_db: {'found' if has_db else 'missing'}")
	lines.append(f"- simulation_log: {'found' if has_log else 'missing'}")
	lines.append("")
	if has_db:
		counts = summary.get("table_counts", {}) or {}
		classes = summary.get("post_classes", {}) or {}
		lines.append("## Platform Counts")
		lines.append("")
		lines.append(markdown_table([counts], list(counts.keys())))
		lines.append("")
		lines.append("## Post Classes")
		lines.append("")
		lines.append(markdown_table([classes], ["rumor", "clarification", "other"]))
		lines.append("")
		lines.append("## Propagation")
		lines.append("")
		rows = []
		for cls in ["rumor", "clarification", "other"]:
			rows.append(
				{
					"class": cls,
					"exposures": (summary.get("exposures_by_class", {}) or {}).get(cls, 0),
					"exposed_accounts": (summary.get("exposures_accounts_by_class", {}) or {}).get(cls, 0),
					"views": (summary.get("view_history_by_class", {}) or {}).get(cls, 0),
					"view_accounts": (summary.get("view_history_accounts_by_class", {}) or {}).get(cls, 0),
					"likes": (summary.get("likes_by_class", {}) or {}).get(cls, 0),
					"comments": (summary.get("comments_by_class", {}) or {}).get(cls, 0),
					"reposts": (summary.get("reposts_by_class", {}) or {}).get(cls, 0),
				}
			)
		lines.append(markdown_table(rows, ["class", "exposures", "exposed_accounts", "views", "view_accounts", "likes", "comments", "reposts"]))
		lines.append("")
		lines.append("## Operations")
		lines.append("")
		op_rows = [{"operation": k, "count": v} for k, v in (summary.get("operations", {}) or {}).items()]
		lines.append(markdown_table(op_rows, ["operation", "count"]))
		lines.append("")
		lines.append("## Key Posts")
		lines.append("")
		lines.append(markdown_table(_top_posts(summary, "rumor") + _top_posts(summary, "clarification"), ["class", "post_id"]))
		lines.append("")
	if has_log:
		lines.append("## Runtime Health")
		lines.append("")
		lines.append(
			markdown_table(
				[
					{
						"gate_ticks": health.get("gate_tick_count", 0),
						"gate_candidates": health.get("gate_candidate_total", 0),
						"gate_selected": health.get("gate_selected_total", 0),
						"opportunities": health.get("opportunity_count", 0),
						"errors": health.get("error_count", 0),
					}
				],
				["gate_ticks", "gate_candidates", "gate_selected", "opportunities", "errors"],
			)
		)
		lines.append("")
		skipped = [{"reason": k, "count": v} for k, v in (health.get("gate_skipped", {}) or {}).items()]
		lines.append("## Gate Skips")
		lines.append("")
		lines.append(markdown_table(skipped, ["reason", "count"]))
		lines.append("")
	else:
		lines.append("## Runtime Health")
		lines.append("")
		lines.append("`simulation_log.json` was not found, so gate/LLM/runtime health could not be inspected.")
		lines.append("")
	return "\n".join(lines)


def main() -> None:
	parser = argparse.ArgumentParser(description="Summarize a KERN social-platform simulation run.")
	parser.add_argument("run_dir", help="Checkpoint/run directory, usually checkpoints/<run_name>.")
	parser.add_argument("--social-db", default="", help="Override social.sqlite3 path.")
	parser.add_argument("--simulation-log", default="", help="Override simulation_log.json path.")
	parser.add_argument("--rumor-tags", default=",".join(sorted(DEFAULT_RUMOR_TAGS)), help="Comma-separated tags that mark rumor posts.")
	parser.add_argument("--clarification-tags", default=",".join(sorted(DEFAULT_CLARIFICATION_TAGS)), help="Comma-separated tags that mark clarification posts.")
	parser.add_argument("--out-md", default="", help="Write Markdown report to this path.")
	parser.add_argument("--out-json", default="", help="Write raw summary JSON to this path.")
	parser.add_argument("--out-ops-csv", default="", help="Write per-tick operation counts CSV.")
	args = parser.parse_args()

	paths = resolve_run_paths(args.run_dir, args.social_db, args.simulation_log)
	rumor_tags = parse_tags(args.rumor_tags, DEFAULT_RUMOR_TAGS)
	clarification_tags = parse_tags(args.clarification_tags, DEFAULT_CLARIFICATION_TAGS)

	summary: dict = {}
	if paths.social_db is not None:
		conn = connect_social_db(paths.social_db)
		try:
			summary = social_summary(conn, rumor_tags, clarification_tags)
		finally:
			conn.close()
	log_payload = load_simulation_log(paths.simulation_log)
	health = runtime_health(list(log_payload.get("log", []) or []))
	report = build_report(paths.run_dir, summary, health, paths.simulation_log is not None, paths.social_db is not None)

	if args.out_md:
		Path(args.out_md).write_text(report, encoding="utf-8")
	else:
		print(report)
	if args.out_json:
		Path(args.out_json).write_text(json.dumps({"summary": summary, "health": health}, ensure_ascii=False, indent=2), encoding="utf-8")
	if args.out_ops_csv and summary:
		write_csv(Path(args.out_ops_csv), list(summary.get("operations_by_tick", []) or []))


if __name__ == "__main__":
	main()
