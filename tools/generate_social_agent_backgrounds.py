from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from KERN.llm.provider_factory import build_chat_provider


DEFAULT_PROFILES_PATH = "KERN/external_runtimes/social_profiles/generated_social_profiles.json"
DEFAULT_OUTPUT_PATH = "KERN/external_runtimes/social_profiles/generated_social_agent_backgrounds.jsonl"


def _load_json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _runtime_llm_config(config_path: Path) -> tuple[Any, str, dict[str, Any]]:
	config = _load_json(config_path)
	env = dict(config["env"])
	extra_raw = str(env.get("LLM_REQUEST_EXTRA_JSON", "") or "").strip()
	extra = json.loads(extra_raw) if extra_raw else {}
	client = build_chat_provider(
		{
			"protocol": str(env["LLM_PROVIDER"]),
			"base_url": str(env["LLM_BASE_URL"]),
			"api_prefix": str(env.get("LLM_API_PREFIX", "/v1")),
			"api_key": str(env["LLM_API_KEY"]),
			"timeout_seconds": int(str(env.get("LLM_TIMEOUT_SECONDS", 60))),
			"max_retries": int(str(env.get("LLM_MAX_RETRIES", 0))),
		}
	)
	return client, str(env["LLM_PLANNER_MODEL"]), extra


def _interest_text(items: list[dict[str, Any]]) -> str:
	if not items:
		return "无"
	out: list[str] = []
	for item in items:
		label = str(item.get("label", "") or item.get("id", "") or "")
		specific = str(item.get("specific", "") or "")
		out.append(f"{label}（{specific}）" if specific else label)
	return "、".join(out)


def _source_card(profile: dict[str, Any]) -> dict[str, Any]:
	sample = dict(profile["sample"])
	display = dict(profile["display"])
	specifics = dict(sample["specifics"])
	family = dict(sample["family_profile"])
	family_labels = dict(family.get("labels", {}) or {})
	return {
		"profile_id": str(profile["profile_id"]),
		"platform_archetype": str(display["platform_archetype"]),
		"age_band": str(display["age_band"]),
		"age": int(specifics["age"]),
		"education": str(display["education"]),
		"specific_education": str(specifics["education"]),
		"occupation_domain": str(display["occupation_domain"]),
		"occupation": str(specifics["occupation"]),
		"economic_status": str(display["economic_status"]),
		"living_situation": str(display["living_situation"]),
		"specific_living_situation": str(specifics["living_situation"]),
		"family": "，".join(
			str(family_labels.get(key, "") or "")
			for key in ("marital_status", "children_status", "parent_support", "family_burden")
			if str(family_labels.get(key, "") or "")
		),
		"family_marital_status": str(family_labels.get("marital_status", "") or ""),
		"family_children_status": str(family_labels.get("children_status", "") or ""),
		"family_parent_support": str(family_labels.get("parent_support", "") or ""),
		"family_burden": str(family_labels.get("family_burden", "") or ""),
		"social_style": str(display["social_style"]),
		"media_style": str(display["media_style"]),
		"specific_media_habit": str(specifics["media_habit"]),
		"consumption_style": str(display["consumption_style"]),
		"specific_consumption_habit": str(specifics["consumption_habit"]),
		"big_five": dict(sample["big_five"]),
		"practical_interests": _interest_text(list(specifics.get("practical_interests", []) or [])),
		"aspirational_interests": _interest_text(list(specifics.get("aspirational_interests", []) or [])),
		"high_cost_consumption_interests": _interest_text(list(specifics.get("high_cost_consumption_interests", []) or [])),
		"science_video_topics": _interest_text(list(specifics.get("science_video_topics", []) or [])),
	}


def _prompt(card: dict[str, Any]) -> list[dict[str, str]]:
	system = (
		"你是社会仿真实验中的角色设定生成器。你的任务是把结构化 agent 属性改写成自然、可信、"
		"可用于角色扮演实验的人物背景。结构化属性是主要锚点，可以补充生活化细节让人物更自然，"
		"但不要写出与属性明显冲突的身份、家庭、职业、资产、健康或消费事实。"
	)
	user = f"""
请根据下面的结构化信息，为一个中文社交平台用户生成自然语言背景。

硬性要求：
1. 输出 JSON 对象，不要输出 Markdown。
2. JSON 只能包含这五个顶层字段：profile_id, generated_name, natural_language_background, correspondence_notes, logic_issues。
3. natural_language_background 必须是一个字符串，写 2-4 段中文自然语言，段落之间用换行符分隔；不要拆成 natural_language_background_2 等多个字段。
4. correspondence_notes 必须是一个 JSON 对象，至少包含 demographics, work_life, family, platform_media, consumption_interests, personality 六个键。
5. natural_language_background 不要用列表，不要出现字段名，不要直接写 openness/conscientiousness/extraversion/agreeableness/neuroticism。
6. 所有结构化属性都要能在自然语言中找到对应表达：年龄、教育、职业、经济状态、居住、家庭责任、社交风格、媒体习惯、消费风格、兴趣、人格倾向；如果提供了“science_video_topics”，要自然表达对这些科普主题的关注。
7. 可以自由发挥姓名、语气、低风险日常细节和生活片段；轻微延展可以接受，人物要像真实社交平台用户。
8. 不要明显违反结构化属性，例如年龄、学历、职业、婚恋/子女状态、经济状态、居住状态和兴趣类型。
9. 避免补出强情节事实：严重疾病、明确债务来源、婚姻变故、父母患病、具体资产来源、真实高价消费、配偶或子女的详细安排。
10. 父母支持压力可以写成帮衬、贴补、照应；如果是“无固定赡养支持”，可以笼统写家庭责任或生活压力，不要写成长期固定赡养。
11. 有幼儿/学龄儿童/成年子女可以按类别自然表达，不要写具体年龄。
12. 向往型兴趣写成关注、观看、收藏、想象或讨论；高成本真实消费兴趣为“无”时，不要写成真实高价消费习惯。
13. 写完后简单自查，删除明显冲突的事实，再输出 JSON。
14. 检查结构化信息本身是否存在明显逻辑错误。只报告硬矛盾或几乎不可能同时成立的组合，不要把少见但可能成立的情况当成错误。
15. logic_issues 必须是数组；每项包含 severity、fields、issue、reason。没有明显错误时输出空数组。不要因为发现问题而擅自修正 source card，也不要把问题藏起来。

结构化信息：
{json.dumps(card, ensure_ascii=False, indent=2)}
""".strip()
	return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_json_object(text: str) -> dict[str, Any]:
	raw = str(text or "").strip()
	if raw.startswith("```"):
		raw = raw.strip("`")
		if raw.lstrip().startswith("json"):
			raw = raw.lstrip()[4:].strip()
	start = raw.find("{")
	end = raw.rfind("}")
	if start < 0 or end < start:
		raise ValueError("LLM response did not contain a JSON object")
	return json.loads(raw[start : end + 1])


def _normalize_generated(card: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
	background_parts: list[str] = []
	main_background = generated.get("natural_language_background", "")
	if not isinstance(main_background, str) or not main_background.strip():
		raise ValueError("LLM response has no non-empty natural_language_background")
	background_parts.append(main_background.strip())
	for key in sorted(str(k) for k in generated.keys() if str(k).startswith("natural_language_background_")):
		value = generated.get(key, "")
		if isinstance(value, str) and value.strip():
			background_parts.append(value.strip())
	notes = generated.get("correspondence_notes", {})
	if not isinstance(notes, dict):
		raise ValueError("LLM response correspondence_notes must be an object")
	issues = generated.get("logic_issues", [])
	if not isinstance(issues, list) or any(not isinstance(item, dict) for item in issues):
		raise ValueError("LLM response logic_issues must be an array of objects")
	return {
		"profile_id": str(generated.get("profile_id", "") or card["profile_id"]),
		"generated_name": str(generated.get("generated_name", "") or "").strip(),
		"natural_language_background": "\n\n".join(background_parts).strip(),
		"correspondence_notes": notes,
		"logic_issues": issues,
	}


def generate_backgrounds(
	*,
	project_root: Path,
	config_path: Path,
	profiles_path: Path,
	output_path: Path,
	limit: int,
	profile_ids: set[str] | None = None,
	concurrency: int = 1,
) -> None:
	client, model, extra = _runtime_llm_config(config_path)
	profiles = list(_load_json(profiles_path)["profiles"])
	if profile_ids:
		profiles = [profile for profile in profiles if str(profile.get("profile_id", "") or "") in profile_ids]
	else:
		profiles = profiles[:limit]
	output_path.parent.mkdir(parents=True, exist_ok=True)
	if int(concurrency) < 1:
		raise ValueError("concurrency must be positive")

	def generate_one(profile: dict[str, Any]) -> dict[str, Any]:
		card = _source_card(profile)
		text = client.chat_text(
			messages=_prompt(card),
			model=model,
			temperature=0.1,
			max_tokens=1200,
			response_format={"type": "json_object"},
			extra=extra,
		)
		generated = _normalize_generated(card, _parse_json_object(text))
		return {
			"profile_id": str(card["profile_id"]),
			"status": "ok",
			"source_card": card,
			"generated": generated,
		}

	started = time.perf_counter()
	completed = 0
	failed = 0
	generated_rows: list[dict[str, Any]] = []
	with output_path.open("w", encoding="utf-8") as f:
		with concurrent.futures.ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
			future_map = {pool.submit(generate_one, profile): str(profile["profile_id"]) for profile in profiles}
			for future in concurrent.futures.as_completed(future_map):
				profile_id = future_map[future]
				try:
					row = future.result()
				except Exception as exc:
					failed += 1
					row = {
						"profile_id": profile_id,
						"status": "error",
						"source_card": _source_card(next(profile for profile in profiles if str(profile.get("profile_id", "")) == profile_id)),
						"generated": None,
						"error": {"type": type(exc).__name__, "message": str(exc)},
					}
					print(f"failed {profile_id}: {exc}", file=sys.stderr)
					generated_rows.append(row)
					f.write(json.dumps(row, ensure_ascii=False) + "\n")
					f.flush()
					continue
				f.write(json.dumps(row, ensure_ascii=False) + "\n")
				f.flush()
				generated_rows.append(row)
				completed += 1
				print(f"generated {profile_id} ({completed}/{len(profiles)})")
	output_path.write_text(
		"".join(
			json.dumps(row, ensure_ascii=False) + "\n"
			for row in sorted(generated_rows, key=lambda item: str(item["profile_id"]))
		),
		encoding="utf-8",
	)
	print(f"completed={completed} failed={failed} elapsed_seconds={time.perf_counter() - started:.3f}")
	if failed:
		raise RuntimeError(f"background generation failed for {failed} profile(s); see error rows in {output_path}")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", default="runtime_config.camping.llm.local.json")
	parser.add_argument("--profiles", default=DEFAULT_PROFILES_PATH)
	parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
	parser.add_argument("--limit", type=int, default=5)
	parser.add_argument("--concurrency", type=int, default=1)
	parser.add_argument("--profile-ids", default="", help="Comma-separated profile IDs to generate. Overrides --limit when set.")
	args = parser.parse_args()
	project_root = Path.cwd()
	profile_ids = {item.strip() for item in str(args.profile_ids or "").split(",") if item.strip()}
	generate_backgrounds(
		project_root=project_root,
		config_path=(project_root / args.config).resolve(),
		profiles_path=(project_root / args.profiles).resolve(),
		output_path=(project_root / args.output).resolve(),
		limit=int(args.limit),
		profile_ids=profile_ids or None,
		concurrency=int(args.concurrency),
	)


if __name__ == "__main__":
	main()
