from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as fh:
		return json.load(fh)


def _load_trace(path: Path) -> dict[str, Any]:
	with gzip.open(path, "rt", encoding="utf-8") as fh:
		data = json.load(fh)
	if not isinstance(data, dict):
		raise ValueError(f"trace must be a JSON object: {path}")
	return data


def _parse_response(trace: dict[str, Any]) -> dict[str, Any]:
	parsed = trace.get("parsed_output")
	if isinstance(parsed, dict):
		return parsed
	text = trace.get("response_text")
	if isinstance(text, str) and text.strip():
		raw = json.loads(text)
		if isinstance(raw, dict):
			return raw
	return {}


def _request_payload(trace: dict[str, Any]) -> dict[str, Any]:
	request = trace.get("request")
	if not isinstance(request, dict):
		return {}
	messages = request.get("messages")
	if not isinstance(messages, list) or len(messages) < 2:
		return {}
	content = messages[1].get("content") if isinstance(messages[1], dict) else None
	if not isinstance(content, str) or not content.strip():
		return {}
	raw = json.loads(content)
	return raw if isinstance(raw, dict) else {}


def _first_action(parsed: dict[str, Any]) -> dict[str, Any] | None:
	actions = parsed.get("actions")
	if isinstance(actions, list) and actions and isinstance(actions[0], dict):
		return actions[0]
	return None


def _attempt_number(trace: dict[str, Any]) -> int | None:
	results = trace.get("action_results")
	if not isinstance(results, list) or not results:
		return None
	first = results[0]
	if not isinstance(first, dict):
		return None
	action_id = str(first.get("action_id", ""))
	match = re.search(r":attempt:(\d+)$", action_id)
	return int(match.group(1)) if match else None


def _trace_sort_key(root: Path, row: dict[str, Any]) -> tuple[int, float, str]:
	trace_path = root / str(row.get("path", ""))
	try:
		trace = _load_trace(trace_path)
		attempt = _attempt_number(trace)
	except Exception:
		attempt = None
	mtime = trace_path.stat().st_mtime if trace_path.exists() else 0.0
	return (attempt if attempt is not None else 10**9, mtime, str(row.get("path", "")))


def _load_trace_rows(root: Path) -> list[dict[str, Any]]:
	index_path = root / "index.jsonl"
	if not index_path.exists():
		raise FileNotFoundError(f"missing trace index: {index_path}")
	rows = []
	for line in index_path.read_text(encoding="utf-8").splitlines():
		if line.strip():
			row = json.loads(line)
			if isinstance(row, dict):
				rows.append(row)
	return rows


def _event_text(event: dict[str, Any]) -> str:
	keys = [
		"type",
		"effect",
		"actor_id",
		"account_id",
		"post_id",
		"feed_session_id",
		"exposure_id",
		"source_effect",
		"like_count",
		"comment_count",
		"repost_count",
	]
	parts = []
	for key in keys:
		if key in event:
			parts.append(f"{key}={event[key]!r}")
	return ", ".join(parts)


def _load_events(run_dir: Path, tick: int, actor_id: str) -> list[dict[str, Any]]:
	log_path = run_dir / "checkpoints" / "simulation_log.json"
	if not log_path.exists():
		return []
	obj = _load_json(log_path)
	records = obj.get("log", []) if isinstance(obj, dict) else obj
	if not isinstance(records, list):
		return []
	out: list[dict[str, Any]] = []
	for record in records:
		if not isinstance(record, dict):
			continue
		if int(record.get("tick", -1)) != tick:
			continue
		event = record.get("event")
		if not isinstance(event, dict):
			continue
		record_actor = record.get("actor_id") or event.get("actor_id")
		event_type = str(event.get("type", event.get("effect", "")))
		if record_actor != actor_id:
			continue
		if "Social" in event_type or "social_propagation:" in event_type or "Memory" in event_type:
			out.append(record)
	return out


def _print_feed(payload: dict[str, Any]) -> None:
	screen = payload.get("screen") if isinstance(payload.get("screen"), dict) else {}
	items = screen.get("feed_items") if isinstance(screen.get("feed_items"), list) else []
	for idx, item in enumerate(items):
		if not isinstance(item, dict):
			continue
		post_id = item.get("post_id")
		liked = item.get("viewer_has_liked")
		reposted = item.get("viewer_has_reposted")
		counts = f"L{item.get('like_count')} C{item.get('comment_count')} R{item.get('repost_count')}"
		text = str(item.get("text", "")).replace("\n", " ")
		if len(text) > 70:
			text = text[:67] + "..."
		print(f"    [{idx}] {post_id} liked={liked} reposted={reposted} {counts} text={text}")


def _print_memory(payload: dict[str, Any], limit: int) -> None:
	memory = payload.get("recent_social_memory")
	if not isinstance(memory, list):
		print("  memory: <missing>")
		return
	print(f"  memory: {len(memory)} entries")
	for item in memory[-limit:]:
		if not isinstance(item, dict):
			print(f"    {item!r}")
			continue
		content = str(item.get("content", item.get("summary", ""))).replace("\n", " ")
		if len(content) > 100:
			content = content[:97] + "..."
		print(f"    {item.get('record_type', item.get('type', 'memory'))} tick={item.get('tick')} post={item.get('post_id', '')} {content}")


def inspect(run_dir: Path, tick: int, actor_id: str, *, memory_limit: int, show_events: bool) -> None:
	root = run_dir / "checkpoints" / "llm_traces"
	rows = [
		row
		for row in _load_trace_rows(root)
		if int(row.get("tick", -1)) == tick and row.get("actor_id") == actor_id
	]
	rows.sort(key=lambda row: _trace_sort_key(root, row))
	print(f"run_dir: {run_dir}")
	print(f"actor: {actor_id}")
	print(f"tick: {tick}")
	print(f"llm_decisions: {len(rows)}")
	print()
	for number, row in enumerate(rows, start=1):
		trace_path = root / str(row["path"])
		trace = _load_trace(trace_path)
		payload = _request_payload(trace)
		parsed = _parse_response(trace)
		action = _first_action(parsed)
		results = trace.get("action_results") if isinstance(trace.get("action_results"), list) else []
		summary = str(parsed.get("decision_summary", "")).replace("\n", " ")
		print(f"Decision #{number}")
		print(f"  trace: {row['path']}")
		print(f"  action: {action if action is not None else 'NO_ACTION'}")
		print(f"  summary: {summary}")
		if results:
			for result in results:
				print(f"  result: {result}")
		else:
			print("  result: <none>")
		print("  visible feed:")
		_print_feed(payload)
		_print_memory(payload, memory_limit)
		print()
	if show_events:
		events = _load_events(run_dir, tick, actor_id)
		print(f"Events for {actor_id} tick {tick}: {len(events)}")
		for record in events:
			event = record.get("event", {})
			print(f"  seq={record.get('seq')} {_event_text(event)}")


def summarize(run_dir: Path) -> None:
	root = run_dir / "checkpoints" / "llm_traces"
	rows = _load_trace_rows(root)
	rows.sort(key=lambda row: (int(row.get("tick", -1)), str(row.get("actor_id", "")), _trace_sort_key(root, row)))
	per_tick: collections.Counter[int] = collections.Counter()
	per_agent: collections.Counter[str] = collections.Counter()
	per_turn: dict[tuple[int, str], list[dict[str, Any] | None]] = collections.defaultdict(list)
	actions: collections.Counter[str] = collections.Counter()
	output_errors = 0
	duplicate_targets = 0
	for row in rows:
		tick = int(row.get("tick", -1))
		actor_id = str(row.get("actor_id", ""))
		per_tick[tick] += 1
		per_agent[actor_id] += 1
		try:
			trace = _load_trace(root / str(row.get("path", "")))
			parsed = _parse_response(trace)
			action = _first_action(parsed)
		except Exception:
			output_errors += 1
			action = None
		per_turn[(tick, actor_id)].append(action)
		if action is None:
			actions["NO_ACTION"] += 1
		else:
			actions[str(action.get("action", ""))] += 1
	seen_by_turn: dict[tuple[int, str], set[tuple[str, str]]] = collections.defaultdict(set)
	for turn, turn_actions in per_turn.items():
		for action in turn_actions:
			if not isinstance(action, dict):
				continue
			key = (str(action.get("post_id", "")), str(action.get("action", "")))
			if key in seen_by_turn[turn]:
				duplicate_targets += 1
			seen_by_turn[turn].add(key)
	turn_lengths = collections.Counter(len(items) for items in per_turn.values())
	action_lengths = collections.Counter(sum(1 for item in items if item is not None) for items in per_turn.values())
	print(f"run_dir: {run_dir}")
	print(f"trace_count: {len(rows)}")
	print(f"agent_count: {len(per_agent)}")
	print(f"turn_count: {len(per_turn)}")
	print(f"output_errors: {output_errors}")
	print(f"duplicate_action_targets_within_turn: {duplicate_targets}")
	print(f"actions: {dict(sorted(actions.items()))}")
	print(f"decision_rounds_per_turn: {dict(sorted(turn_lengths.items()))}")
	print(f"actions_per_turn: {dict(sorted(action_lengths.items()))}")
	print(f"traces_by_tick: {dict(sorted(per_tick.items()))}")
	print()
	print("longest_turns:")
	for (tick, actor_id), turn_actions in sorted(per_turn.items(), key=lambda item: len(item[1]), reverse=True)[:20]:
		seq = []
		for action in turn_actions:
			if action is None:
				seq.append("NO_ACTION")
			else:
				seq.append(f"{action.get('action')}:{action.get('post_id')}")
		print(f"  tick={tick} actor={actor_id} decisions={len(turn_actions)} actions={', '.join(seq)}")


def main() -> None:
	if hasattr(sys.stdout, "reconfigure"):
		sys.stdout.reconfigure(encoding="utf-8", errors="replace")
	parser = argparse.ArgumentParser(description="Inspect social-platform LLM traces.")
	parser.add_argument("--run-dir", required=True, help="Run directory containing checkpoints/llm_traces.")
	parser.add_argument("--tick", type=int)
	parser.add_argument("--actor", help="Actor id, for example agent_001.")
	parser.add_argument("--summary", action="store_true", help="Print a run-wide summary instead of one actor turn.")
	parser.add_argument("--memory-limit", type=int, default=5, help="Recent memory entries to print for each decision.")
	parser.add_argument("--no-events", action="store_true", help="Skip simulation_log event summary.")
	args = parser.parse_args()
	run_dir = Path(args.run_dir).resolve()
	if args.summary:
		summarize(run_dir)
		return
	if args.tick is None or not args.actor:
		parser.error("--tick and --actor are required unless --summary is set")
	inspect(run_dir, args.tick, args.actor, memory_limit=max(0, args.memory_limit), show_events=not args.no_events)


if __name__ == "__main__":
	main()
