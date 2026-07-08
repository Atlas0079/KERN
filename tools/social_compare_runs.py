from __future__ import annotations

import argparse
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


def _label_for(path: Path, explicit: str, index: int) -> str:
	labels = [x.strip() for x in str(explicit or "").split(",") if x.strip()]
	if index < len(labels):
		return labels[index]
	return path.name


def main() -> None:
	parser = argparse.ArgumentParser(description="Compare multiple KERN social-platform simulation runs.")
	parser.add_argument("run_dirs", nargs="+", help="Checkpoint/run directories.")
	parser.add_argument("--labels", default="", help="Comma-separated labels matching run_dirs.")
	parser.add_argument("--rumor-tags", default=",".join(sorted(DEFAULT_RUMOR_TAGS)), help="Comma-separated tags that mark rumor posts.")
	parser.add_argument("--clarification-tags", default=",".join(sorted(DEFAULT_CLARIFICATION_TAGS)), help="Comma-separated tags that mark clarification posts.")
	parser.add_argument("--out-csv", default="", help="Write comparison table as CSV.")
	args = parser.parse_args()

	rumor_tags = parse_tags(args.rumor_tags, DEFAULT_RUMOR_TAGS)
	clarification_tags = parse_tags(args.clarification_tags, DEFAULT_CLARIFICATION_TAGS)
	rows: list[dict] = []
	for idx, run_dir in enumerate(args.run_dirs):
		paths = resolve_run_paths(run_dir)
		row = {
			"label": _label_for(paths.run_dir, args.labels, idx),
			"run_dir": str(paths.run_dir),
			"has_social_db": bool(paths.social_db),
			"has_log": bool(paths.simulation_log),
		}
		if paths.social_db is not None:
			conn = connect_social_db(paths.social_db)
			try:
				summary = social_summary(conn, rumor_tags, clarification_tags)
			finally:
				conn.close()
			row.update(
				{
					"accounts": (summary.get("table_counts", {}) or {}).get("accounts", 0),
					"posts": (summary.get("table_counts", {}) or {}).get("posts", 0),
					"rumor_posts": (summary.get("post_classes", {}) or {}).get("rumor", 0),
					"clarification_posts": (summary.get("post_classes", {}) or {}).get("clarification", 0),
					"rumor_exposures": (summary.get("exposures_by_class", {}) or {}).get("rumor", 0),
					"rumor_exposed_accounts": (summary.get("exposures_accounts_by_class", {}) or {}).get("rumor", 0),
					"rumor_views": (summary.get("view_history_by_class", {}) or {}).get("rumor", 0),
					"rumor_reposts": (summary.get("reposts_by_class", {}) or {}).get("rumor", 0),
					"clarification_exposures": (summary.get("exposures_by_class", {}) or {}).get("clarification", 0),
					"clarification_views": (summary.get("view_history_by_class", {}) or {}).get("clarification", 0),
				}
			)
		if paths.simulation_log is not None:
			health = runtime_health(list(load_simulation_log(paths.simulation_log).get("log", []) or []))
			row.update(
				{
					"gate_ticks": health.get("gate_tick_count", 0),
					"gate_candidates": health.get("gate_candidate_total", 0),
					"gate_selected": health.get("gate_selected_total", 0),
					"errors": health.get("error_count", 0),
				}
			)
		rows.append(row)

	if args.out_csv:
		write_csv(Path(args.out_csv), rows)

	columns = [
		"label",
		"accounts",
		"posts",
		"rumor_posts",
		"rumor_exposures",
		"rumor_exposed_accounts",
		"rumor_views",
		"rumor_reposts",
		"clarification_exposures",
		"clarification_views",
		"gate_selected",
		"errors",
	]
	print("# Social Run Comparison")
	print("")
	print(markdown_table(rows, columns))


if __name__ == "__main__":
	main()
