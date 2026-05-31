from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.agent_workflow.llm_action_provider import LLMActionProvider
from KERN.llm.openai_compat_client import OpenAICompatClient


def _load_runtime_env(config_path: Path) -> dict[str, str]:
	data = json.loads(config_path.read_text(encoding="utf-8"))
	env_raw = data.get("env", {}) if isinstance(data, dict) else {}
	if not isinstance(env_raw, dict):
		return {}
	out: dict[str, str] = {}
	for k, v in env_raw.items():
		out[str(k)] = str(v)
	return out


def _fill_template(tpl: str, mapping: dict[str, Any]) -> str:
	out = str(tpl or "")
	for k, v in mapping.items():
		out = out.replace("{{" + str(k) + "}}", str(v))
	return out


def _build_dialogue_user_prompt() -> str:
	template_path = Path(__file__).resolve().parents[1] / "Data" / "LLMContext_Dialogue.md"
	tpl = template_path.read_text(encoding="utf-8")
	mapping = {
		"self_id": "civilian_01",
		"agent_name": "Mira",
		"personality_summary": "谨慎、合作导向，偏好先沟通再行动。",
		"common_knowledge_summary": "空间站损坏，需要协作修复并防范风险。",
		"mid_term_summary": "刚参与了会议室讨论，观察到有人主张分头行动。",
		"mode": "dialogue",
		"current_task_summary": "无",
		"location_id": "meeting_room",
		"location_name": "Meeting Room",
		"conversation_id": "conv_probe_001",
		"dialogue_phase": "dialogue",
		"initiator_id": "imposter_01",
		"participants_table": "- imposter_01 | Eris\n- civilian_01 | Mira\n- civilian_02 | Noah",
		"utterance_index": "2",
		"max_utterances_per_tick": "4",
		"remaining_utterances_in_tick": "2",
		"conversation_transcript": "[Eris] 我们应该马上分工。\n[Noah] 我先去机库检查设备。",
		"visible_entities_table": "- civilian_02 | Noah | tags=character,agent",
		"inventory_table": "- medkit_01 | Emergency Medkit",
		"reachable_locations_table": "- meeting_room -> corridor\n- meeting_room -> medbay",
		"recent_interactions_text": "你注意到机库附近最近有异常移动记录。",
	}
	return _fill_template(tpl, mapping)


def _analyze_output(raw: str) -> dict[str, Any]:
	s = str(raw or "")
	first_line = s.splitlines()[0].strip() if s.splitlines() else ""
	return {
		"raw": s,
		"first_line": first_line,
		"line_count": len(s.splitlines()) if s else 0,
		"char_count": len(s),
		"has_thought_tag": bool(re.search(r"<\s*thought\s*>", s, flags=re.IGNORECASE)),
		"has_thought_label": bool(re.search(r"\bTHOUGHT\s*:", s, flags=re.IGNORECASE)),
		"looks_json": s.lstrip().startswith("{") or s.lstrip().startswith("["),
		"is_pass": first_line == "PASS",
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Probe Gemma dialogue output style across prompt variants.")
	parser.add_argument("--config", default="runtime_config.json", help="Path to runtime config json")
	parser.add_argument("--trials", type=int, default=3, help="Calls per prompt variant")
	parser.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature")
	parser.add_argument("--output", default="", help="Optional output file path")
	args = parser.parse_args()

	root = Path(__file__).resolve().parents[1]
	config_path = Path(args.config)
	if not config_path.is_absolute():
		config_path = root / config_path
	env = _load_runtime_env(config_path)

	model = str(env.get("LLM_GROUNDER_MODEL", "") or env.get("LLM_PLANNER_MODEL", "") or "gemma-4-31b-it")
	client = OpenAICompatClient(
		base_url=str(env.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com") or "https://generativelanguage.googleapis.com"),
		api_prefix=str(env.get("LLM_API_PREFIX", "/v1beta/openai") or "/v1beta/openai"),
		api_key=str(env.get("LLM_API_KEY", "REPLACE_ME") or "REPLACE_ME"),
		timeout_seconds=int(str(env.get("LLM_TIMEOUT_SECONDS", "60") or "60")),
		max_retries=int(str(env.get("LLM_MAX_RETRIES", "1") or "1")),
		retry_backoff_seconds=float(str(env.get("LLM_RETRY_BACKOFF_SECONDS", "1") or "1")),
	)

	base_system = LLMActionProvider.DIALOGUE_SYSTEM_PROMPT
	template_user = _build_dialogue_user_prompt()

	cases: list[dict[str, Any]] = [
		{
			"name": "current_dialogue_prompt",
			"system": base_system,
			"user": template_user,
			"response_format": None,
			"temperature": float(args.temperature),
		},
		{
			"name": "strict_no_thought_append",
			"system": base_system + "\n\nHard rule: NEVER output <thought> tags or reasoning.",
			"user": template_user + "\n\nFinal reminder: output exactly one short spoken line or PASS.",
			"response_format": None,
			"temperature": float(args.temperature),
		},
		{
			"name": "minimal_one_line_prompt",
			"system": "You are Mira in a game dialogue turn. Output exactly one line, no reasoning, no tags.",
			"user": "Context: Eris says 'Let's split up to repair faster'. Reply as Mira in one short line, or PASS.",
			"response_format": None,
			"temperature": 0.7,
		},
		{
			"name": "json_wrapped_line",
			"system": "Return strict JSON only.",
			"user": "Output JSON object: {\"line\":\"<one short spoken line or PASS>\"}. No extra text.",
			"response_format": {"type": "json_object"},
			"temperature": 0.3,
		},
	]

	report: dict[str, Any] = {
		"meta": {
			"timestamp": datetime.now().isoformat(),
			"config_path": str(config_path),
			"model": model,
			"trials_per_case": int(args.trials),
		},
		"results": [],
	}

	print(f"[probe] model={model} trials={int(args.trials)}")
	for case in cases:
		case_name = str(case["name"])
		print(f"[probe] running case={case_name}")
		item: dict[str, Any] = {"name": case_name, "samples": []}
		for i in range(int(args.trials)):
			messages = [
				{"role": "system", "content": str(case["system"])},
				{"role": "user", "content": str(case["user"])},
			]
			try:
				text = client.chat_text(
					messages=messages,
					model=model,
					temperature=float(case["temperature"]),
					response_format=case.get("response_format", None),
				)
				analysis = _analyze_output(text)
				analysis["ok"] = True
			except Exception as e:
				analysis = {"ok": False, "error": str(e), "raw": ""}
			analysis["trial"] = i + 1
			item["samples"].append(analysis)
			time.sleep(0.2)
		ok_samples = [s for s in item["samples"] if bool(s.get("ok", False))]
		item["summary"] = {
			"ok_count": len(ok_samples),
			"error_count": len(item["samples"]) - len(ok_samples),
			"thought_tag_count": sum(1 for s in ok_samples if bool(s.get("has_thought_tag", False))),
			"thought_label_count": sum(1 for s in ok_samples if bool(s.get("has_thought_label", False))),
			"multiline_count": sum(1 for s in ok_samples if int(s.get("line_count", 0)) > 1),
		}
		report["results"].append(item)

	print("\n=== Summary ===")
	for item in report["results"]:
		s = item["summary"]
		print(
			f"{item['name']}: ok={s['ok_count']} err={s['error_count']} "
			f"thought_tag={s['thought_tag_count']} thought_label={s['thought_label_count']} multiline={s['multiline_count']}"
		)

	out_path = Path(args.output).expanduser() if args.output else (root / "checkpoints" / "gemma4_prompt_probe_report.json")
	if not out_path.is_absolute():
		out_path = root / out_path
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"\n[probe] report written: {out_path}")


if __name__ == "__main__":
	main()
