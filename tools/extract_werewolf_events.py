from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


INTERESTING_EVENT_TYPES = {
	"SimulationAbortRequested",
	"WorkflowDecisionError",
	"EntityMoved",
	"EntityDied",
	"EntityCreated",
	"EntityDestroyed",
	"TaskCreated",
	"TaskAssigned",
	"TaskAccepted",
	"TaskProgressed",
	"TaskFinished",
	"TaskInterrupted",
	"TaskCancelled",
	"ConversationStarted",
	"ConversationSpoken",
	"ConversationEnded",
	"MemoryPatched",
	"RandomBundleResolved",
	"ExecutorError",
	"BindError",
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CONSOLE_RE = re.compile(r"^\[(?P<level>[A-Z]+)\]\[(?P<category>[^\]]+)\]\[(?P<event>[^\]]+)\]\s*(?P<context>\{.*\})\s*$")


def _load_json(path: Path) -> dict[str, Any]:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _resolve_log_path(path_text: str) -> Path:
	path = Path(path_text)
	if path.is_dir():
		return path / "simulation_log.json"
	return path


def _iter_console_rows(path: Path) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	try:
		text = path.read_text(encoding="utf-8", errors="replace")
	except Exception:
		return rows
	for idx, raw in enumerate(text.splitlines(), start=1):
		line = ANSI_RE.sub("", raw).strip()
		match = CONSOLE_RE.match(line)
		if not match:
			continue
		context_text = match.group("context")
		try:
			context = json.loads(context_text)
		except Exception:
			context = {"raw": context_text}
		rows.append(
			{
				"kind": "console",
				"line": idx,
				"level": match.group("level"),
				"category": match.group("category"),
				"event_name": match.group("event"),
				"context": context,
			}
		)
	return rows


def _load_rows(path: Path) -> tuple[Path, list[dict[str, Any]], str]:
	resolved = _resolve_log_path(str(path))
	if resolved.exists() and resolved.suffix.lower() == ".json":
		payload = _load_json(resolved)
		rows = payload.get("log", []) or []
		return resolved, [dict(x) for x in list(rows) if isinstance(x, dict)] if isinstance(rows, list) else [], "simulation_log"
	if resolved.exists():
		return resolved, _iter_console_rows(resolved), "console_log"
	if path.exists() and path.suffix.lower() != ".json":
		return path, _iter_console_rows(path), "console_log"
	return resolved, [], "missing"


def _event_summary(event: dict[str, Any]) -> str:
	etype = str(event.get("type", "") or "")
	if etype == "EntityMoved":
		return f"{event.get('entity_id', '')}: {event.get('source_id', '')} -> {event.get('destination_id', '')}"
	if etype == "ConversationSpoken":
		return f"{event.get('speaker_id', '')}: {event.get('text', '')}"
	if etype == "ConversationEnded":
		return f"{event.get('conversation_id', '')}: spoken={event.get('spoken_count', 0)} participants={event.get('joined_participants', [])}"
	if etype in {"TaskCreated", "TaskAssigned", "TaskAccepted", "TaskProgressed", "TaskFinished", "TaskInterrupted", "TaskCancelled"}:
		return f"task={event.get('task_id', '')} worker={event.get('worker_id', '')} progress={event.get('new_progress', '')}/{event.get('required', '')}"
	if etype == "WorkflowDecisionError":
		return str(event.get("detail", ""))
	if etype in {"ExecutorError", "BindError"}:
		return str(event.get("message", event))
	return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _interaction_summary(row: dict[str, Any]) -> str:
	actor = str(row.get("actor_name", "") or row.get("actor_id", "") or "")
	verb = str(row.get("verb", "") or "")
	status = str(row.get("status", "") or "")
	target = str(row.get("target_name", "") or row.get("target_id", "") or "")
	extra: list[str] = []
	for key in ["reason", "speech", "travel_phase", "to_location_id", "reaction_phase", "reaction_rule_id"]:
		value = row.get(key, "")
		if value:
			extra.append(f"{key}={value}")
	return f"{actor} {verb} -> {target} [{status}]" + (f" {' '.join(extra)}" if extra else "")


def _is_interesting_interaction(row: dict[str, Any], include_reactions: bool) -> bool:
	verb = str(row.get("verb", "") or "")
	if not include_reactions and verb.startswith("Reaction"):
		return False
	return bool(row.get("is_dialogue", False)) or bool(row.get("is_reaction", False)) or verb not in {"ReactionTriggered", ""}


def _is_interesting_event(event: dict[str, Any]) -> bool:
	etype = str(event.get("type", "") or "")
	if etype == "MemoryPatched" and int(event.get("notes_added", 0) or 0) <= 0:
		return False
	return etype in INTERESTING_EVENT_TYPES


def _console_summary(row: dict[str, Any]) -> str:
	ctx = dict(row.get("context", {}) or {})
	category = str(row.get("category", "") or "")
	event = str(row.get("event_name", "") or "")
	if category == "llm":
		fields = []
		for key in ["self_id", "stage", "tick", "cooldown_until_tick", "error", "intent", "actions"]:
			if key in ctx:
				fields.append(f"{key}={ctx.get(key)}")
		return f"{category}.{event} " + " ".join(fields)
	return f"{category}.{event} {json.dumps(ctx, ensure_ascii=False, separators=(',', ':'))}"


def main() -> None:
	parser = argparse.ArgumentParser(description="Extract concise interesting events from a KERN simulation_log.json.")
	parser.add_argument("path", nargs="?", default="checkpoints/werewolf_gemini_10tick_local", help="checkpoint dir or simulation_log.json path")
	parser.add_argument("--max-lines", type=int, default=200)
	parser.add_argument("--include-reactions", action="store_true", help="include ReactionTriggered/ReactionApplied rows")
	parser.add_argument("--console", action="store_true", help="treat input as console log even when extension is not .log")
	args = parser.parse_args()

	input_path = Path(str(args.path))
	if bool(args.console):
		log_path = input_path
		rows = _iter_console_rows(log_path)
		source_type = "console_log"
	else:
		log_path, rows, source_type = _load_rows(input_path)

	print(f"log={log_path}")
	print(f"source={source_type}")
	print(f"rows={len(rows)}")
	print("")
	count = 0
	stats: dict[str, int] = {}
	for row in rows:
		if not isinstance(row, dict):
			continue
		kind = str(row.get("kind", "") or "")
		tick = int(row.get("tick", 0) or 0)
		if kind == "interaction":
			if not _is_interesting_interaction(row, include_reactions=bool(args.include_reactions)):
				continue
			stats["interaction"] = stats.get("interaction", 0) + 1
			print(f"[tick {tick:03d}] interaction {str(row.get('seq', ''))}: {_interaction_summary(row)}")
			count += 1
		elif kind == "event":
			event = row.get("event", {}) or {}
			if not isinstance(event, dict):
				continue
			if not _is_interesting_event(event):
				continue
			etype = str(event.get("type", "") or "")
			stats[etype] = stats.get(etype, 0) + 1
			print(f"[tick {tick:03d}] event {str(row.get('seq', ''))}: {etype} | {_event_summary(event)}")
			count += 1
		elif kind == "console":
			level = str(row.get("level", "") or "")
			category = str(row.get("category", "") or "")
			event_name = str(row.get("event_name", "") or "")
			if category not in {"llm", "system"} and level not in {"WARN", "ERROR"}:
				continue
			if category == "checkpoint":
				continue
			stats[f"console:{category}.{event_name}"] = stats.get(f"console:{category}.{event_name}", 0) + 1
			print(f"[line {int(row.get('line', 0) or 0):04d}] {level} {_console_summary(row)}")
			count += 1
		if count >= int(args.max_lines):
			print(f"... truncated at {count} lines")
			break
	print("")
	if stats:
		print("summary=" + json.dumps(stats, ensure_ascii=False, sort_keys=True))
	print(f"interesting_lines={count}")


if __name__ == "__main__":
	main()
