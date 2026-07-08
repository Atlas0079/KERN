from __future__ import annotations

import argparse
from pathlib import Path

from social_diagnostics_lib import (
	DEFAULT_CLARIFICATION_TAGS,
	DEFAULT_RUMOR_TAGS,
	agent_rows,
	connect_social_db,
	markdown_table,
	parse_tags,
	resolve_run_paths,
	write_csv,
)


def _sort_rows(rows: list[dict], sort_key: str) -> list[dict]:
	return sorted(rows, key=lambda x: (-int(x.get(sort_key, 0) or 0), str(x.get("account_id", ""))))


def main() -> None:
	parser = argparse.ArgumentParser(description="Report per-account social-platform activity for a KERN run.")
	parser.add_argument("run_dir", help="Checkpoint/run directory, usually checkpoints/<run_name>.")
	parser.add_argument("--social-db", default="", help="Override social.sqlite3 path.")
	parser.add_argument("--rumor-tags", default=",".join(sorted(DEFAULT_RUMOR_TAGS)), help="Comma-separated tags that mark rumor posts.")
	parser.add_argument("--clarification-tags", default=",".join(sorted(DEFAULT_CLARIFICATION_TAGS)), help="Comma-separated tags that mark clarification posts.")
	parser.add_argument("--sort", default="rumor_exposures", help="Metric column to sort by.")
	parser.add_argument("--limit", type=int, default=30, help="Max rows to print in Markdown output.")
	parser.add_argument("--out-csv", default="", help="Write complete account table as CSV.")
	args = parser.parse_args()

	paths = resolve_run_paths(args.run_dir, args.social_db)
	if paths.social_db is None:
		raise SystemExit(f"social db not found under {paths.run_dir}")

	rumor_tags = parse_tags(args.rumor_tags, DEFAULT_RUMOR_TAGS)
	clarification_tags = parse_tags(args.clarification_tags, DEFAULT_CLARIFICATION_TAGS)
	conn = connect_social_db(paths.social_db)
	try:
		rows = agent_rows(conn, rumor_tags, clarification_tags)
	finally:
		conn.close()

	if args.out_csv:
		write_csv(Path(args.out_csv), rows)

	ordered = _sort_rows(rows, args.sort)
	columns = [
		"account_id",
		"display_name",
		"rumor_exposures",
		"rumor_views",
		"rumor_likes",
		"rumor_comments",
		"rumor_reposts",
		"clarification_exposures",
		"clarification_views",
		"posts_created",
		"actions_total",
	]
	print("# Social Agent Report")
	print("")
	print(f"- run_dir: `{paths.run_dir}`")
	print(f"- social_db: `{paths.social_db}`")
	print(f"- sort: `{args.sort}`")
	print("")
	print(markdown_table(ordered[: max(0, int(args.limit or 0))], columns))


if __name__ == "__main__":
	main()
