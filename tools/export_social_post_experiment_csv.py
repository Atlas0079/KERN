from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
	return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def export_csv(input_path: Path, output_path: Path) -> None:
	rows = _load_jsonl(input_path)
	fields = [
		"agent_id",
		"profile_id",
		"generated_name",
		"post_condition",
		"post_label",
		"repeat_index",
		"like",
		"comment",
		"share",
		"save",
		"follow_author",
		"report",
		"no_action",
		"actions",
		"impression",
		"error",
	]
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with output_path.open("w", encoding="utf-8-sig", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
		writer.writeheader()
		for row in rows:
			item = dict(row)
			if isinstance(item.get("actions"), list):
				item["actions"] = "|".join(str(x) for x in item["actions"])
			writer.writerow(item)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--input", default="tmp/social_post_experiment_full_100x4.jsonl")
	parser.add_argument("--output", default="tmp/social_post_experiment_full_100x4.csv")
	args = parser.parse_args()
	export_csv(Path(args.input), Path(args.output))


if __name__ == "__main__":
	main()
