from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import (
	CHILDREN_LABELS,
	ECONOMIC_LABELS,
	EDUCATION_FIELDS,
	EDUCATION_LEVELS,
	ELDER_SUPPORT_LABELS,
	FAMILY_BURDEN_LABELS,
	GENDER_LABELS,
	LIFECYCLE_LABELS,
	OCCUPATION_STATUS_LABELS,
	PARTNERSHIP_LABELS,
	SCHEMA_VERSION,
	GenerationSpec,
	validate_profile,
)
from KERN.llm.provider_factory import build_chat_provider


DEFAULT_PROFILES_PATH = "KERN/external_runtimes/social_profiles/generated_social_profiles.json"
DEFAULT_OUTPUT_PATH = "KERN/external_runtimes/social_profiles/generated_social_agent_backgrounds.jsonl"


def _load_json(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(value, dict):
		raise ValueError("expected a JSON object")
	return value


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
	return "、".join(f"{item['label']}（{item['expression']}）" for item in items)


def _trait_phrase(value: float, low: str, middle: str, high: str) -> str:
	return low if value <= 0.3 else high if value >= 0.7 else middle


def _source_card(profile: dict[str, Any], spec: GenerationSpec | None = None) -> dict[str, Any]:
	issues = validate_profile(profile, spec)
	if issues:
		raise ValueError(f"cannot narrate invalid profile {profile.get('profile_id', '')}: {issues}")
	demographics = dict(profile["demographics"])
	education = dict(profile["education"])
	occupation = dict(profile["occupation"])
	household = dict(profile["household"])
	socioeconomic = dict(profile["socioeconomic"])
	personality = dict(profile["personality"])
	interests = dict(profile["interests"])
	education_current = "目前没有在读项目"
	if education["current_status"] == "enrolled":
		education_current = f"目前正在攻读{EDUCATION_FIELDS[education['current_program_field']]}方向的{EDUCATION_LEVELS[education['current_program']]['label']}阶段课程"
	elif education["current_status"] == "continuing_education":
		education_current = f"目前在{EDUCATION_FIELDS[education['current_program_field']]}方向参加继续教育"
	education_history = "，随后".join(f"完成{item['field_label']}方向的{item['level_label']}阶段" for item in education["history"])
	personality_text = "，".join(
		[
			_trait_phrase(float(personality["openness"]), "偏好熟悉经验", "对新事物保持适度好奇", "很愿意探索新观点"),
			_trait_phrase(float(personality["conscientiousness"]), "做事较随性", "做事有一定计划", "做事很有计划和条理"),
			_trait_phrase(float(personality["extraversion"]), "性格较内向", "社交主动性适中", "性格外向主动"),
			_trait_phrase(float(personality["agreeableness"]), "表达立场较直接", "合作与坚持之间较平衡", "通常体谅并配合他人"),
			_trait_phrase(float(personality["neuroticism"]), "情绪通常稳定", "会有普通程度的担忧", "面对压力时较容易焦虑"),
		]
	)
	# Each sampled element receives its own coverage ID. This makes exhaustive
	# coverage auditable while leaving the prose free to merge and reorder facts.
	facts = [
		{"fact_id": "demographics.gender", "text": f"我是{GENDER_LABELS[demographics['gender']]}。"},
		{"fact_id": "demographics.age", "text": f"我今年{demographics['age']}岁。"},
		{"fact_id": "demographics.lifecycle_stage", "text": f"我处于{LIFECYCLE_LABELS[demographics['lifecycle_stage']]}。"},
	]
	for index, stage in enumerate(education["history"], start=1):
		facts.append({"fact_id": f"education.history.{index}", "text": f"我完成了{stage['field_label']}方向的{stage['level_label']}阶段。"})
	facts.extend(
		[
			{"fact_id": "education.highest_completed", "text": f"我的最高完成教育经历是{education['description']}。"},
			{"fact_id": "education.current_status", "text": f"{education_current.replace('目前', '我目前', 1)}。"},
			{"fact_id": "occupation", "text": f"我当前的身份或职业是{occupation['description']}，处于{OCCUPATION_STATUS_LABELS[occupation['status']]}状态。"},
			{"fact_id": "household.partnership", "text": f"我的婚恋状态是{PARTNERSHIP_LABELS[household['partnership']]}。"},
			{"fact_id": "household.children", "text": f"我的子女情况是{CHILDREN_LABELS[household['children']]}。"},
			{"fact_id": "household.elder_support", "text": f"我的长辈支持情况是{ELDER_SUPPORT_LABELS[household['elder_support']]}。"},
			{"fact_id": "household.family_burden", "text": f"我的{FAMILY_BURDEN_LABELS[household['family_burden']]}。"},
			{"fact_id": "socioeconomic.economic_pressure", "text": f"我的经济状况{ECONOMIC_LABELS[socioeconomic['economic_pressure']]}。"},
			{"fact_id": "socioeconomic.housing", "text": f"我{socioeconomic['housing_description']}。"},
			{"fact_id": "socioeconomic.consumption_style", "text": f"我{socioeconomic['consumption_description']}。"},
		]
	)
	trait_phrases = personality_text.split("，")
	for trait, phrase in zip(("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"), trait_phrases):
		facts.append({"fact_id": f"personality.{trait}", "text": f"我{phrase}。"})
	for kind, prefix in (("practical", "我实际参与"), ("aspirational", "我目前主要关注、了解或向往"), ("high_cost", "我已有现实投入或明确计划")):
		items = list(interests[kind])
		if items:
			for index, item in enumerate(items, start=1):
				facts.append({"fact_id": f"interests.{kind}.{index}", "text": f"{prefix}{item['label']}，具体表现为{item['expression']}。"})
		else:
			facts.append({"fact_id": f"interests.{kind}.none", "text": f"{prefix}的项目为无。"})
	for index, item in enumerate(interests["science_topics"], start=1):
		facts.append({"fact_id": f"interests.science_topics.{index}", "text": f"我关注{item['label']}，具体是{item['expression']}。"})
	return {
		"schema_version": "social_profile_source_card.v5",
		"profile_id": str(profile["profile_id"]),
		"population_id": str(profile["provenance"]["population_id"]),
		"facts": facts,
	}


def _prompt(card: dict[str, Any]) -> list[dict[str, str]]:
	expected_ids = [item["fact_id"] for item in card["facts"]]
	# Research decision (2026-08-08): every sampled profile element is closed-world
	# and must appear in the prose; unsampled narrative detail is open-world and may
	# be added when it stays coherent. The background is always written in the
	# agent's first-person voice. Names are not an experiment variable and are not
	# required or validated. Ambiguous source values may be resolved to one concrete
	# interpretation for this narrative. Only
	# mutually incompatible or impossible facts count as logic issues; unusual but
	# possible combinations do not. Added details and resolutions remain narrative
	# context rather than structured experiment variables.
	system = (
		"你是社会仿真实验的人物背景撰写者。source card 是人物的核心事实骨架。"
		"请用人物自述的第一人称口吻，完整保留每条原子事实及其关系，并将它们扩写成自然、可信、有生活感的中文背景。"
		"可以加入合理且低影响的衔接性细节，使人物更连贯；结构化字段仍是实验变量的正式来源。"
		"平台上的具体选择将在仿真情境中形成，这份背景聚焦人物的日常身份、经历和处境。"
	)
	user = f"""
将 source card 改写为第一人称“我”的自然中文人物背景。

输出契约：
1. 输出 JSON 对象，核心字段为 profile_id、natural_language_background、covered_fact_ids、logic_issue_explanation。
2. profile_id 必须原样复制。
3. covered_fact_ids 必须完整且仅包含以下 ID：{json.dumps(expected_ids, ensure_ascii=False)}。
4. source card 中每个 fact_id 对应的元素都必须在正文中明确表达；可以调整语序和合并句子，覆盖不能只体现在 covered_fact_ids 声明里。
5. 向往型兴趣可以表现为关注、了解、学习或未来打算；实际参与和高成本投入保持与 source card 的程度一致。
6. 使用自然中文表达字段含义，人物补充细节与已有年龄、教育、职业、家庭和经济处境保持协调。
7. 全文保持人物自述视角，以“我”组织经历、处境、性格和兴趣；整体写成可信的人物背景，而不是字段清单或审计说明。
8. source card 未规定的元素可以合理扩写，它们作为叙事细节存在，不替代或省略任何已采样元素。
9. 结构化字段若提供了合并或模糊类别，可以为这个人物选择一种确定解释并在全文保持一致。例如“离异或丧偶”可以具体化为离异或丧偶；这种具体化不是逻辑错误。
10. logic_issue_explanation 通常为 null。只有两条事实互相排斥、无法同时成立或形成明确逻辑错误时，才填写一段中文说明。罕见、非典型、跨专业、职业不对口、较晚生育或特殊居住安排本身都属于可能的人生经历。没有自己的子女但陪伴亲友或社区儿童阅读、活动，同样是可以直接合理解释的经历，不属于逻辑错误。
11. 遇到明确逻辑错误时，正文在完整保留相关采样元素的基础上，给出尽可能合理的情境解释；logic_issue_explanation 说明冲突为什么属于逻辑问题以及正文如何处理。

source card：
{json.dumps(card, ensure_ascii=False, indent=2)}
""".strip()
	return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_json_object(text: str) -> dict[str, Any]:
	raw = str(text or "").strip()
	if raw.startswith("```"):
		raw = raw.strip("`")
		if raw.lstrip().startswith("json"):
			raw = raw.lstrip()[4:].strip()
	start, end = raw.find("{"), raw.rfind("}")
	if start < 0 or end < start:
		raise ValueError("LLM response did not contain a JSON object")
	value = json.loads(raw[start : end + 1])
	if not isinstance(value, dict):
		raise ValueError("LLM response must be a JSON object")
	return value


def _normalize_generated(card: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
	expected_keys = {"profile_id", "natural_language_background", "covered_fact_ids", "logic_issue_explanation"}
	if not expected_keys <= set(generated):
		raise ValueError(f"LLM response must contain {sorted(expected_keys)}")
	if str(generated["profile_id"]) != str(card["profile_id"]):
		raise ValueError("LLM response changed profile_id")
	background = generated["natural_language_background"]
	if not isinstance(background, str) or not background.strip():
		raise ValueError("LLM response has no non-empty natural_language_background")
	if "我" not in background:
		raise ValueError("natural_language_background must use first-person voice")
	logic_issue = generated["logic_issue_explanation"]
	if logic_issue is not None and not isinstance(logic_issue, str):
		raise ValueError("logic_issue_explanation must be null or a string")
	logic_issue = logic_issue.strip() if isinstance(logic_issue, str) and logic_issue.strip() else None
	expected_ids = [str(item["fact_id"]) for item in card["facts"]]
	covered = generated["covered_fact_ids"]
	if not isinstance(covered, list) or len(covered) != len(expected_ids) or set(map(str, covered)) != set(expected_ids):
		raise ValueError("covered_fact_ids must contain every source fact exactly once")
	normalized = {
		"profile_id": str(card["profile_id"]),
		"natural_language_background": background.strip(),
		"covered_fact_ids": expected_ids,
		"logic_issue_explanation": logic_issue,
	}
	# Research decision (2026-08-08): extra model fields are retained for review
	# instead of rejecting an otherwise useful background. Downstream code relies
	# only on the three normalized core fields above.
	extras = {key: value for key, value in generated.items() if key not in expected_keys}
	if extras:
		normalized["model_extras"] = extras
	return normalized


def _fingerprint(card: Mapping[str, Any]) -> str:
	raw = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	return hashlib.sha256(raw).hexdigest()


def generate_backgrounds(
	*,
	config_path: Path,
	profiles_path: Path,
	output_path: Path,
	limit: int,
	profile_ids: set[str] | None = None,
	concurrency: int = 1,
) -> None:
	client, model, extra = _runtime_llm_config(config_path)
	population = _load_json(profiles_path)
	if population.get("schema_version") != SCHEMA_VERSION:
		raise ValueError(f"profiles input must use {SCHEMA_VERSION}")
	generation = population.get("generation")
	if not isinstance(generation, dict) or not isinstance(generation.get("resolved_config"), dict):
		raise ValueError("profiles input has no resolved generation config")
	spec = GenerationSpec.from_dict(generation["resolved_config"])
	if generation.get("config_sha256") != spec.config_sha256:
		raise ValueError("profiles generation config fingerprint mismatch")
	profiles = list(population["profiles"])
	if profile_ids:
		profiles = [profile for profile in profiles if str(profile.get("profile_id", "")) in profile_ids]
	else:
		profiles = profiles[:limit]
	if int(concurrency) < 1:
		raise ValueError("concurrency must be positive")
	output_path.parent.mkdir(parents=True, exist_ok=True)

	def generate_one(profile: dict[str, Any]) -> dict[str, Any]:
		card = _source_card(profile, spec)
		text = client.chat_text(
			messages=_prompt(card),
			model=model,
			temperature=0.4,
			max_tokens=1200,
			response_format={"type": "json_object"},
			extra=extra,
		)
		return {
			"profile_id": card["profile_id"],
			"status": "ok",
			"source_card_schema": card["schema_version"],
			"source_card_fingerprint": _fingerprint(card),
			"generated": _normalize_generated(card, _parse_json_object(text)),
		}

	started = time.perf_counter()
	rows: list[dict[str, Any]] = []
	with concurrent.futures.ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
		future_map = {pool.submit(generate_one, profile): str(profile["profile_id"]) for profile in profiles}
		for future in concurrent.futures.as_completed(future_map):
			profile_id = future_map[future]
			try:
				row = future.result()
			except Exception as exc:
				row = {"profile_id": profile_id, "status": "error", "generated": None, "error": {"type": type(exc).__name__, "message": str(exc)}}
				print(f"failed {profile_id}: {exc}", file=sys.stderr)
			rows.append(row)
			print(f"processed {profile_id} ({len(rows)}/{len(profiles)})")
	rows.sort(key=lambda item: str(item["profile_id"]))
	output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
	failed = sum(row["status"] == "error" for row in rows)
	print(f"completed={len(rows) - failed} failed={failed} elapsed_seconds={time.perf_counter() - started:.3f}")
	if failed:
		raise RuntimeError(f"background generation failed for {failed} profile(s); see {output_path}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Render validated social profiles as grounded natural-language backgrounds.")
	parser.add_argument("--config", default="runtime_config.camping.llm.local.json")
	parser.add_argument("--profiles", default=DEFAULT_PROFILES_PATH)
	parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
	parser.add_argument("--limit", type=int, default=5)
	parser.add_argument("--concurrency", type=int, default=1)
	parser.add_argument("--profile-ids", default="")
	args = parser.parse_args()
	profile_ids = {item.strip() for item in str(args.profile_ids).split(",") if item.strip()}
	generate_backgrounds(
		config_path=(ROOT / args.config).resolve(),
		profiles_path=(ROOT / args.profiles).resolve(),
		output_path=(ROOT / args.output).resolve(),
		limit=int(args.limit),
		profile_ids=profile_ids or None,
		concurrency=int(args.concurrency),
	)


if __name__ == "__main__":
	main()
