from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ACTION_FIELDS = ("like", "comment", "share", "save", "follow_author", "report", "no_action")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
	return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_post_meta(path: Path) -> dict[str, dict[str, Any]]:
	raw = json.loads(path.read_text(encoding="utf-8"))
	out: dict[str, dict[str, Any]] = {}
	for stimulus_set in raw.get("stimulus_sets", []) or []:
		for post in stimulus_set.get("posts", []) or []:
			post_id = str(post["post_id"])
			out[post_id] = {
				"stimulus_set_id": str(stimulus_set.get("stimulus_set_id", "")),
				"topic_id": str(stimulus_set.get("topic_id", "")),
				"topic_label": str(stimulus_set.get("topic_label", "")),
				"consequence_level": str(post.get("consequence_level", "")),
				"solution_level": str(post.get("solution_level", "")),
				"consequence_high": 1 if str(post.get("consequence_level", "")) == "high" else 0,
				"solution_high": 1 if str(post.get("solution_level", "")) == "high" else 0,
			}
	return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
	if len(xs) != len(ys) or len(xs) < 2:
		return None
	x_mean = sum(xs) / len(xs)
	y_mean = sum(ys) / len(ys)
	num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
	x_den = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
	y_den = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
	if x_den == 0 or y_den == 0:
		return None
	return num / (x_den * y_den)


def _rate(rows: list[dict[str, Any]], field: str) -> float:
	if not rows:
		return 0.0
	return sum(1 for row in rows if bool(row.get(field))) / len(rows)


def _pct(value: float) -> str:
	return f"{value * 100:.1f}%"


def _corr_text(value: float | None) -> str:
	return "NA" if value is None else f"{value:.4f}"


def analyze(input_path: Path, stimuli_path: Path, output_path: Path) -> str:
	rows = _load_jsonl(input_path)
	meta = _load_post_meta(stimuli_path)
	enriched: list[dict[str, Any]] = []
	missing_meta = 0
	error_rows = 0
	for row in rows:
		post_id = str(row.get("post_condition", ""))
		post_meta = meta.get(post_id)
		if post_meta is None:
			missing_meta += 1
			continue
		item = dict(row)
		item.update(post_meta)
		enriched.append(item)
		if item.get("error"):
			error_rows += 1

	ok_rows = [row for row in enriched if not row.get("error")]
	lines: list[str] = []
	lines.append("# Social Post Experiment Quick Analysis")
	lines.append("")
	lines.append(f"- input: `{input_path}`")
	lines.append(f"- stimuli: `{stimuli_path}`")
	lines.append(f"- raw rows: {len(rows)}")
	lines.append(f"- matched rows: {len(enriched)}")
	lines.append(f"- usable rows: {len(ok_rows)}")
	lines.append(f"- error rows: {error_rows}")
	lines.append(f"- missing post metadata rows: {missing_meta}")
	repeats = sorted({int(row.get("repeat_index", 1) or 1) for row in enriched})
	lines.append(f"- repeats observed: {len(repeats)} ({repeats[0] if repeats else 'NA'}..{repeats[-1] if repeats else 'NA'})")
	lines.append("")

	lines.append("## Overall Action Rates")
	lines.append("")
	lines.append("| action | rate | count |")
	lines.append("|---|---:|---:|")
	for field in ACTION_FIELDS:
		count = sum(1 for row in ok_rows if bool(row.get(field)))
		lines.append(f"| {field} | {_pct(count / len(ok_rows) if ok_rows else 0.0)} | {count} |")
	lines.append("")

	lines.append("## Correlation With Manipulated Dimensions")
	lines.append("")
	lines.append("Pearson r is phi correlation here because both predictors and action outcomes are binary.")
	lines.append("")
	lines.append("| outcome | r(consequence_high) | r(solution_high) | r(interaction_high_high) |")
	lines.append("|---|---:|---:|---:|")
	for field in ACTION_FIELDS:
		ys = [1.0 if bool(row.get(field)) else 0.0 for row in ok_rows]
		consequence = [float(row["consequence_high"]) for row in ok_rows]
		solution = [float(row["solution_high"]) for row in ok_rows]
		interaction = [float(row["consequence_high"] * row["solution_high"]) for row in ok_rows]
		lines.append(
			f"| {field} | {_corr_text(_pearson(consequence, ys))} | "
			f"{_corr_text(_pearson(solution, ys))} | {_corr_text(_pearson(interaction, ys))} |"
		)
	lines.append("")

	lines.append("## Rates By 2x2 Condition")
	lines.append("")
	lines.append("| consequence | solution | n | like | comment | share | save | follow_author | no_action |")
	lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
	for consequence in ("low", "high"):
		for solution in ("low", "high"):
			group = [
				row for row in ok_rows
				if row["consequence_level"] == consequence and row["solution_level"] == solution
			]
			lines.append(
				f"| {consequence} | {solution} | {len(group)} | "
				f"{_pct(_rate(group, 'like'))} | {_pct(_rate(group, 'comment'))} | "
				f"{_pct(_rate(group, 'share'))} | {_pct(_rate(group, 'save'))} | "
				f"{_pct(_rate(group, 'follow_author'))} | {_pct(_rate(group, 'no_action'))} |"
			)
	lines.append("")

	lines.append("## Share Rate By Topic And Condition")
	lines.append("")
	lines.append("| topic | low/low | low/high | high/low | high/high |")
	lines.append("|---|---:|---:|---:|---:|")
	topics = sorted({str(row["topic_label"]) for row in ok_rows})
	for topic in topics:
		cells = []
		for consequence, solution in (("low", "low"), ("low", "high"), ("high", "low"), ("high", "high")):
			group = [
				row for row in ok_rows
				if row["topic_label"] == topic
				and row["consequence_level"] == consequence
				and row["solution_level"] == solution
			]
			cells.append(_pct(_rate(group, "share")))
		lines.append(f"| {topic} | {' | '.join(cells)} |")
	lines.append("")

	action_patterns = Counter("|".join(row.get("actions", [])) for row in ok_rows)
	lines.append("## Top Action Patterns")
	lines.append("")
	lines.append("| actions | count |")
	lines.append("|---|---:|")
	for actions, count in action_patterns.most_common(12):
		lines.append(f"| {actions or '(blank)'} | {count} |")
	lines.append("")

	text = "\n".join(lines) + "\n"
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(text, encoding="utf-8")
	return text


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--input", default="tmp/social_post_experiment_100x40_v2.jsonl")
	parser.add_argument("--stimuli", default="tmp/social_post_stimuli_10_sets.json")
	parser.add_argument("--output", default="tmp/social_post_experiment_100x40_v2_analysis.md")
	args = parser.parse_args()
	text = analyze(Path(args.input), Path(args.stimuli), Path(args.output))
	print(text)
	print(f"wrote analysis to {Path(args.output).resolve()}")


if __name__ == "__main__":
	main()
