from __future__ import annotations

import argparse
import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MACHINE_EVENT_TYPES = {
	"AdvanceTick",
	"EnvironmentConditionTick",
	"StatusTick",
	"WorkerTick",
	"WorldTickAdvanced",
}


@dataclass(frozen=True)
class TimelineFilters:
	tick: int | None = None
	tick_from: int | None = None
	tick_to: int | None = None
	agent_id: str = ""
	kinds: frozenset[str] = frozenset()
	event_type: str = ""
	include_machine_events: bool = False
	trace_detail: str = "summary"


def _read_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as stream:
		return json.load(stream)


def _read_json_gz(path: Path) -> Any:
	with gzip.open(path, "rt", encoding="utf-8") as stream:
		return json.load(stream)


def _trace_root(run_dir: Path) -> Path:
	candidate = run_dir / "llm_traces"
	return candidate if candidate.is_dir() else run_dir


def _load_simulation_rows(run_dir: Path) -> list[dict[str, Any]]:
	path = run_dir / "simulation_log.json"
	if not path.exists():
		return []
	payload = _read_json(path)
	rows = payload.get("log", payload.get("rows", [])) if isinstance(payload, dict) else payload
	return [dict(row) for row in list(rows or []) if isinstance(row, dict)]


def _load_trace_index(run_dir: Path) -> list[dict[str, Any]]:
	root = _trace_root(run_dir)
	path = root / "index.jsonl"
	if not path.exists():
		return []
	rows: list[dict[str, Any]] = []
	for line in path.read_text(encoding="utf-8").splitlines():
		text = line.strip()
		if not text:
			continue
		row = json.loads(text)
		if isinstance(row, dict):
			rows.append(dict(row))
	return rows


def _load_trace_payload(run_dir: Path, index_row: dict[str, Any]) -> dict[str, Any]:
	root = _trace_root(run_dir)
	rel = str(index_row.get("path", "") or "").strip()
	if not rel:
		return {}
	path = (root / rel).resolve()
	try:
		path.relative_to(root.resolve())
	except ValueError:
		raise ValueError(f"trace path escapes llm_traces root: {rel}")
	payload = _read_json_gz(path)
	return dict(payload) if isinstance(payload, dict) else {}


def _event_dict(row: dict[str, Any]) -> dict[str, Any]:
	event = row.get("event", {}) or {}
	return dict(event) if isinstance(event, dict) else {}


def _event_type(row: dict[str, Any]) -> str:
	return str(_event_dict(row).get("type", "") or "")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
	payload = _event_dict(row).get("payload", {}) or {}
	return dict(payload) if isinstance(payload, dict) else {}


def _context(row: dict[str, Any]) -> dict[str, Any]:
	context = _event_dict(row).get("context", {}) or {}
	return dict(context) if isinstance(context, dict) else {}


def _tick_of(row: dict[str, Any]) -> int:
	return int(row.get("tick", row.get("tick_at", 0)) or 0)


def _matches_tick(tick: int, filters: TimelineFilters) -> bool:
	if filters.tick is not None and int(tick) != int(filters.tick):
		return False
	if filters.tick_from is not None and int(tick) < int(filters.tick_from):
		return False
	if filters.tick_to is not None and int(tick) > int(filters.tick_to):
		return False
	return True


def _row_agent_ids(row: dict[str, Any]) -> set[str]:
	event = _event_dict(row)
	payload = _payload(row)
	context = _context(row)
	ids = {
		str(row.get("actor_id", "") or ""),
		str(context.get("actor_id", "") or ""),
		str(context.get("self_id", "") or ""),
		str(context.get("target_id", "") or ""),
		str(context.get("event_entity_id", "") or ""),
		str(payload.get("actor_id", "") or ""),
		str(payload.get("entity_id", "") or ""),
		str(payload.get("target_id", "") or ""),
		str(event.get("actor_id", "") or ""),
	}
	for key in ("participants", "assigned_agent_ids"):
		values = payload.get(key, []) or []
		if isinstance(values, list):
			ids.update(str(item or "") for item in values)
	return {item for item in ids if item}


def _trace_agent_ids(trace: dict[str, Any]) -> set[str]:
	ids = {str(trace.get("actor_id", "") or "")}
	for result in list(trace.get("action_results", []) or []):
		if not isinstance(result, dict):
			continue
		intent = result.get("intent", {}) or {}
		if isinstance(intent, dict):
			ids.add(str(intent.get("target_id", "") or ""))
	return {item for item in ids if item}


def _matches_agent(row_or_trace: dict[str, Any], agent_id: str, *, is_trace: bool = False) -> bool:
	agent = str(agent_id or "").strip()
	if not agent:
		return True
	ids = _trace_agent_ids(row_or_trace) if is_trace else _row_agent_ids(row_or_trace)
	return agent in ids


def _action_id_sort_value(action_id: str) -> tuple[int, int]:
	text = str(action_id or "")
	match = re.search(r"turn:(\d+):attempt:(\d+)", text)
	if not match:
		return (999999, 999999)
	return (int(match.group(1)), int(match.group(2)))


def _event_action_id(row: dict[str, Any]) -> str:
	event = _event_dict(row)
	return str(event.get("action_id", "") or "")


def _build_action_seq_index(rows: list[dict[str, Any]]) -> dict[str, int]:
	out: dict[str, int] = {}
	for row in rows:
		action_id = _event_action_id(row)
		if not action_id:
			continue
		seq = int(row.get("seq", 0) or 0)
		if action_id not in out or seq < out[action_id]:
			out[action_id] = seq
	return out


def _interaction_summary(row: dict[str, Any]) -> dict[str, Any]:
	return {
		"seq": int(row.get("seq", 0) or 0),
		"tick": _tick_of(row),
		"actor_id": str(row.get("actor_id", "") or ""),
		"action_id": str(row.get("action_id", "") or ""),
		"verb": str(row.get("verb", "") or ""),
		"target_id": str(row.get("target_id", "") or ""),
		"status": str(row.get("status", "") or ""),
		"reason": str(row.get("reason", "") or ""),
		"narrative": str(row.get("narrative", row.get("speech", "")) or ""),
	}


def _event_summary(row: dict[str, Any]) -> dict[str, Any]:
	event = _event_dict(row)
	payload = _payload(row)
	return {
		"seq": int(row.get("seq", 0) or 0),
		"tick": _tick_of(row),
		"actor_id": str(row.get("actor_id", "") or ""),
		"type": str(event.get("type", "") or ""),
		"source_effect": str(event.get("source_effect", "") or ""),
		"action_id": str(event.get("action_id", "") or ""),
		"payload": payload,
	}


def _last_role_value(trace: dict[str, Any], role: str, key: str) -> Any:
	for attempt in reversed([item for item in list(trace.get("attempts", []) or []) if isinstance(item, dict)]):
		data = attempt.get(role, {}) or {}
		if isinstance(data, dict) and key in data:
			return data.get(key)
	return None


def _trace_summary(trace: dict[str, Any], detail: str) -> dict[str, Any]:
	out: dict[str, Any] = {
		"trace_id": str(trace.get("trace_id", "") or ""),
		"tick": int(trace.get("tick", 0) or 0),
		"actor_id": str(trace.get("actor_id", "") or ""),
		"context_type": str(trace.get("context_type", "") or ""),
		"status": str(trace.get("status", "") or ""),
		"location_id": str(trace.get("location_id", "") or ""),
		"planner_thought": str(_last_role_value(trace, "planner", "thought") or ""),
		"planner_intent": str(_last_role_value(trace, "planner", "intent") or ""),
		"actions": [dict(item) for item in list(trace.get("actions", []) or []) if isinstance(item, dict)],
		"action_results": [dict(item) for item in list(trace.get("action_results", []) or []) if isinstance(item, dict)],
	}
	if detail in {"context", "full"}:
		perception = dict(trace.get("perception", {}) or {}) if isinstance(trace.get("perception", {}), dict) else {}
		out["context"] = {
			"agent_name": str(perception.get("agent_name", "") or ""),
			"personality_summary": str(perception.get("personality_summary", "") or ""),
			"common_knowledge_summary": str(perception.get("common_knowledge_summary", "") or ""),
			"location": dict(perception.get("location", {}) or {}) if isinstance(perception.get("location", {}), dict) else {},
			"vitals": dict(perception.get("vitals", {}) or {}) if isinstance(perception.get("vitals", {}), dict) else {},
			"current_task_id": str(perception.get("current_task_id", "") or ""),
			"entities": [dict(item) for item in list(perception.get("entities", []) or []) if isinstance(item, dict)],
			"inventory": [dict(item) for item in list(perception.get("inventory", []) or []) if isinstance(item, dict)],
			"recent_interactions": [dict(item) for item in list(perception.get("recent_interactions", []) or []) if isinstance(item, dict)],
			"short_term_memory_items": [dict(item) for item in list(perception.get("short_term_memory_items", []) or []) if isinstance(item, dict)],
		}
	if detail in {"prompts", "full"}:
		out["attempts"] = [dict(item) for item in list(trace.get("attempts", []) or []) if isinstance(item, dict)]
	return out


def build_timeline(run_dir: str | Path, filters: TimelineFilters | None = None) -> list[dict[str, Any]]:
	run_path = Path(run_dir)
	active_filters = filters or TimelineFilters()
	rows = _load_simulation_rows(run_path)
	action_seq = _build_action_seq_index(rows)
	items: list[dict[str, Any]] = []
	for row in rows:
		kind = str(row.get("kind", "event") or "event")
		tick = _tick_of(row)
		if not _matches_tick(tick, active_filters):
			continue
		if active_filters.kinds and kind not in active_filters.kinds:
			continue
		if not _matches_agent(row, active_filters.agent_id):
			continue
		if kind == "event":
			etype = _event_type(row)
			if active_filters.event_type and etype != active_filters.event_type:
				continue
			if not active_filters.include_machine_events and etype in MACHINE_EVENT_TYPES:
				continue
			payload = _event_summary(row)
		elif kind == "interaction":
			if active_filters.event_type:
				continue
			payload = _interaction_summary(row)
			action_id = str(row.get("action_id", "") or "")
			order = action_seq.get(action_id, int(row.get("seq", 0) or 0)) * 10 + (1 if action_id in action_seq else 0)
		else:
			continue
		if kind == "event":
			order = int(row.get("seq", 0) or 0) * 10
		items.append(
			{
				"kind": kind,
				"tick": tick,
				"order": order,
				"payload": payload,
			}
		)
	if not active_filters.kinds or "trace" in active_filters.kinds:
		for index_row in _load_trace_index(run_path):
			trace_tick = int(index_row.get("tick", 0) or 0)
			if not _matches_tick(trace_tick, active_filters):
				continue
			trace = _load_trace_payload(run_path, index_row)
			if not trace:
				continue
			if not _matches_agent(trace, active_filters.agent_id, is_trace=True):
				continue
			if active_filters.event_type:
				continue
			result_ids = [
				str((item or {}).get("action_id", "") or "")
				for item in list(trace.get("action_results", []) or [])
				if isinstance(item, dict)
			]
			known_orders = [action_seq[action_id] for action_id in result_ids if action_id in action_seq]
			if known_orders:
				order = min(known_orders) * 10 - 1
			else:
				turn_attempts = [_action_id_sort_value(action_id) for action_id in result_ids]
				turn_order = min(turn_attempts) if turn_attempts else (999999, 999999)
				order = 1_000_000 + turn_order[0] * 1000 + turn_order[1]
			items.append(
				{
					"kind": "trace",
					"tick": trace_tick,
					"order": order,
					"payload": _trace_summary(trace, active_filters.trace_detail),
				}
			)
	return sorted(items, key=lambda item: (int(item.get("tick", 0) or 0), int(item.get("order", 0) or 0), str(item.get("kind", ""))))


def _format_action(action: dict[str, Any]) -> str:
	verb = str(action.get("verb", "") or "")
	target = str(action.get("target_id", "") or "")
	params = action.get("parameters", {}) or {}
	param_text = f" {json.dumps(params, ensure_ascii=False, separators=(',', ':'))}" if params else ""
	target_text = f" -> {target}" if target else ""
	return f"{verb}{target_text}{param_text}".strip()


def format_timeline_text(items: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in items:
		kind = str(item.get("kind", "") or "")
		tick = int(item.get("tick", 0) or 0)
		payload = dict(item.get("payload", {}) or {})
		if kind == "trace":
			actions = [_format_action(dict(action)) for action in list(payload.get("actions", []) or []) if isinstance(action, dict)]
			results = [
				f"{str(result.get('status', '') or '')}:{str(result.get('rejection_code', '') or '')}".rstrip(":")
				for result in list(payload.get("action_results", []) or [])
				if isinstance(result, dict)
			]
			lines.append(
				f"[tick {tick}] trace {payload.get('actor_id')} {payload.get('context_type')} "
				f"intent={payload.get('planner_intent')!r} actions={actions} results={results}"
			)
			continue
		if kind == "interaction":
			lines.append(
				f"[tick {tick}] interaction #{payload.get('seq')} {payload.get('actor_id')} "
				f"{payload.get('verb')} {payload.get('status')} target={payload.get('target_id')} "
				f"{payload.get('narrative') or payload.get('reason')}"
			)
			continue
		if kind == "event":
			lines.append(
				f"[tick {tick}] event #{payload.get('seq')} {payload.get('type')} "
				f"actor={payload.get('actor_id')} action={payload.get('action_id')} "
				f"payload={json.dumps(payload.get('payload', {}), ensure_ascii=False, separators=(',', ':'))}"
			)
	return "\n".join(lines)


def _parse_kinds(value: str) -> frozenset[str]:
	out = {item.strip() for item in str(value or "").split(",") if item.strip()}
	allowed = {"event", "interaction", "trace"}
	unknown = sorted(out - allowed)
	if unknown:
		raise ValueError(f"unknown kind(s): {', '.join(unknown)}")
	return frozenset(out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build a filtered KERN simulation timeline from archive logs and LLM traces.")
	parser.add_argument("--run", required=True, help="checkpoint run directory")
	parser.add_argument("--tick", type=int, default=None, help="single tick to show")
	parser.add_argument("--from", dest="tick_from", type=int, default=None, help="first tick to show")
	parser.add_argument("--to", dest="tick_to", type=int, default=None, help="last tick to show")
	parser.add_argument("--agent", default="", dest="agent_id", help="agent/entity id filter")
	parser.add_argument("--kind", default="", help="comma-separated filter: event,interaction,trace")
	parser.add_argument("--event-type", default="", help="event type filter, e.g. InteractionRecorded")
	parser.add_argument("--include-machine-events", action="store_true", help="include AdvanceTick/WorkerTick/StatusTick/etc.")
	parser.add_argument("--trace-detail", choices=["summary", "context", "prompts", "full"], default="summary")
	parser.add_argument("--format", choices=["text", "json"], default="text")
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
	args = parse_args(argv)
	filters = TimelineFilters(
		tick=args.tick,
		tick_from=args.tick_from,
		tick_to=args.tick_to,
		agent_id=str(args.agent_id or ""),
		kinds=_parse_kinds(str(args.kind or "")),
		event_type=str(args.event_type or ""),
		include_machine_events=bool(args.include_machine_events),
		trace_detail=str(args.trace_detail or "summary"),
	)
	items = build_timeline(args.run, filters)
	if args.format == "json":
		print(json.dumps(items, ensure_ascii=False, indent=2))
	else:
		print(format_timeline_text(items))


if __name__ == "__main__":
	main()
