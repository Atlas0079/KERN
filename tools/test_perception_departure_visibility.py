from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEBUG_LINE_RE = re.compile(r"^\[DEBUG\]\[(?P<category>[^\]]+)\]\[(?P<event>[^\]]+)\]\s*(?P<context>\{.*\})\s*$")
ANON_LEAVE_RE = re.compile(r"(有人离开|someone.*left|离开了)", re.IGNORECASE)


@dataclass
class LogRecord:
	line_no: int
	category: str
	event: str
	context: dict[str, Any]


def parse_debug_records(text: str) -> list[LogRecord]:
	records: list[LogRecord] = []
	for idx, raw in enumerate(text.splitlines(), start=1):
		line = raw.strip()
		if not line:
			continue
		match = DEBUG_LINE_RE.match(line)
		if not match:
			continue
		context_text = match.group("context")
		try:
			context = json.loads(context_text)
		except Exception:
			continue
		records.append(
			LogRecord(
				line_no=idx,
				category=match.group("category"),
				event=match.group("event"),
				context=context,
			)
		)
	return records


def is_travel_like(record: LogRecord) -> bool:
	ctx = record.context
	verb = str(ctx.get("verb", "") or "")
	event_name = str(record.event or "")
	if verb == "Travel":
		return True
	if "travel" in event_name.lower():
		return True
	return False


def is_anonymous_departure_thought(record: LogRecord) -> bool:
	if record.category != "llm" or record.event != "planner_thought":
		return False
	text = str(record.context.get("thought", "") or "")
	return bool(ANON_LEAVE_RE.search(text))


def analyze(records: list[LogRecord], window: int = 80) -> None:
	travels = [r for r in records if is_travel_like(r)]
	anon = [r for r in records if is_anonymous_departure_thought(r)]

	print("=== Summary ===")
	print(f"parsed_records={len(records)}")
	print(f"travel_like_records={len(travels)}")
	print(f"anonymous_departure_thoughts={len(anon)}")

	if not anon:
		print("\n未发现“有人离开”这类匿名 thought。")
		return

	for item in anon:
		agent_id = str(item.context.get("self_id", "") or "")
		tick = int(item.context.get("tick", 0) or 0)
		print("\n--- Case ---")
		print(f"line={item.line_no} tick={tick} self_id={agent_id}")
		print(f"thought={item.context.get('thought', '')}")
		candidates = []
		for tr in travels:
			if abs(tr.line_no - item.line_no) > int(window):
				continue
			candidates.append(tr)
		if not candidates:
			print("nearby_travel_records=0")
			print("结论：当前日志片段里没有可关联的 Travel 记录，无法确认身份是否可见。")
			continue
		print(f"nearby_travel_records={len(candidates)}")
		for tr in candidates:
			ctx = tr.context
			print(
				f"- line={tr.line_no} event={tr.event} actor_id={ctx.get('actor_id', '')} "
				f"actor_name={ctx.get('actor_name', '')} status={ctx.get('status', '')} "
				f"from={ctx.get('location_id', '')} to={ctx.get('to_location_id', '')}"
			)
		with_identity = [
			tr
			for tr in candidates
			if str(tr.context.get("actor_id", "") or "").strip() or str(tr.context.get("actor_name", "") or "").strip()
		]
		if with_identity:
			print("结论：日志里存在带身份的移动事件，匿名 thought 更可能发生在提示词压缩/总结阶段。")
		else:
			print("结论：日志里移动事件本身就缺少 actor identity，需要先补日志字段。")


def main() -> None:
	default_sample = """
[DEBUG][llm][planner_intent] {"self_id": "imposter_01", "intent": "立即前往会议室。"}
[DEBUG][llm][grounder_actions] {"self_id": "imposter_01", "actions": [{"verb": "Travel", "target_id": "imposter_01", "parameters": {"to_location_id": "meeting_room"}}]}
[DEBUG][interaction][action_executed] {"tick": 17, "actor_id": "imposter_01", "actor_name": "Imposter 01", "verb": "Travel", "status": "success", "location_id": "medical_room", "to_location_id": "meeting_room"}
[DEBUG][llm][planner_thought] {"tick": 17, "self_id": "civilian_02", "thought": "观察变化显示有人离开了医疗室。"}
""".strip()
	log_path = Path("tools/departure_debug_sample.log")
	if log_path.exists():
		text = log_path.read_text(encoding="utf-8")
		print(f"using_log_file={log_path}")
	else:
		text = default_sample
		print("using_embedded_sample=true")
	records = parse_debug_records(text)
	analyze(records)


if __name__ == "__main__":
	main()
