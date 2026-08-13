from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.llm.provider_factory import build_chat_provider


POST_COUNT = 200
PUBLISHER_COUNT = 40
SOURCE_CARD_SCHEMA = "sea_level_background_post_source_cards.v1"
BACKGROUND_POSTS_SCHEMA = "social_background_posts.v1"

PLAN_BUCKETS = (
	("interest_hobby", 70),
	("everyday_life", 55),
	("community_public", 35),
	("light_public_issue", 25),
	("loose_social", 15),
)
BUCKET_LABELS = {
	"interest_hobby": "兴趣爱好与个人经验",
	"everyday_life": "日常生活、家庭、工作、消费或通勤",
	"community_public": "社区、城市、公共服务、健康或技术社会",
	"light_public_issue": "轻公共议题或信息转述",
	"loose_social": "随手记录、求建议、小抱怨或轻量情绪",
}
PUBLISHER_NAMES = (
	"生活碎片簿",
	"城市小观察",
	"健康随手记",
	"科技日常谈",
	"邻里频道",
	"阅读与文化角",
	"家庭备忘录",
	"运动慢记录",
	"职场午休",
	"消费体验站",
	"旅行计划本",
	"家常厨房",
	"亲子小纸条",
	"理财学习桌",
	"游戏与数码",
	"手作修理铺",
	"通勤路上",
	"公共服务观察",
	"天气与生活",
	"情绪便利贴",
	"社区活动板",
	"学习复盘页",
	"小区见闻",
	"家居整理箱",
	"摄影练习册",
	"公园散步线",
	"展览与音乐",
	"信息核查台",
	"绿色生活笔记",
	"晚间闲聊",
	"普通上班族",
	"生活提问箱",
	"居家维修记",
	"育儿互助角",
	"周末安排局",
	"饭后散步群",
	"城市交通线",
	"新工具试用",
	"老街新事",
	"日常长帖",
)
TOPIC_HASHTAGS = {
	"cooking": ("家常菜", "备餐", "厨房经验", "生活技巧"),
	"fitness": ("运动日常", "散步", "轻运动", "健康习惯"),
	"gaming": ("游戏日常", "攻略讨论", "休息时间"),
	"crafts": ("动手维修", "手作", "生活小事"),
	"community": ("社区观察", "邻里活动", "公共空间"),
	"reading": ("阅读笔记", "图书馆", "时间管理"),
	"photography": ("摄影练习", "生活影像", "手机拍照"),
	"gardening": ("阳台种植", "植物养护", "日常记录"),
	"parenting": ("亲子生活", "上学准备", "家庭协作"),
	"travel": ("旅行准备", "路线规划", "周末去处"),
	"premium_tech": ("产品体验", "数码生活", "消费观察"),
	"home_design": ("整理收纳", "居家生活", "家居动线"),
	"career_learning": ("技能学习", "工作方法", "阶段复盘"),
	"financial_learning": ("家庭预算", "理性消费", "储蓄计划"),
	"culture_art": ("城市文化", "展览", "音乐现场"),
	"public_health": ("健康科普", "社区健康", "规律作息"),
	"technology_society": ("数字服务", "技术社会", "用户体验"),
	"environment": ("绿色生活", "社区实践", "环保措施"),
	"ecology": ("生态社区", "本地植物", "雨水花园"),
	"technology": ("数字生活", "实用技巧", "新工具"),
	"general_knowledge": ("信息核查", "生活常识", "经验分享"),
	"extreme_weather": ("天气变化", "出行提醒", "城市安全"),
	"health_risk": ("健康提醒", "风险意识", "日常管理"),
}
BUCKET_TOPIC_POOL = {
	"interest_hobby": (
		"cooking",
		"fitness",
		"gaming",
		"crafts",
		"reading",
		"photography",
		"gardening",
		"parenting",
		"travel",
		"premium_tech",
		"home_design",
		"career_learning",
		"financial_learning",
		"culture_art",
	),
	"everyday_life": (
		"cooking",
		"parenting",
		"home_design",
		"financial_learning",
		"career_learning",
		"technology",
		"fitness",
		"general_knowledge",
	),
	"community_public": (
		"community",
		"public_health",
		"technology_society",
		"environment",
		"fitness",
		"reading",
		"culture_art",
		"general_knowledge",
	),
	"light_public_issue": (
		"public_health",
		"technology_society",
		"environment",
		"ecology",
		"extreme_weather",
		"general_knowledge",
	),
	"loose_social": (
		"general_knowledge",
		"cooking",
		"fitness",
		"community",
		"career_learning",
		"technology",
		"reading",
	),
}
SCENE_POOL = {
	"interest_hobby": (
		"休息时试了一个小方法",
		"周末给自己安排了一段练习",
		"看到别人分享后自己也试了试",
		"把一个长期收藏的想法做成了小尝试",
	),
	"everyday_life": (
		"工作日晚上处理了一件家里的小事",
		"通勤或排队时想到一个日常问题",
		"家里人临时提起一件需要安排的事",
		"买东西、做预算或整理物品时发现了细节",
	),
	"community_public": (
		"社区或城市里有一个新变化",
		"公共服务的小流程最近调整了",
		"附近空间被更多人使用后出现了新问题",
		"线下服务和手机小程序之间有了新的衔接",
	),
	"light_public_issue": (
		"刷到一条公共议题相关信息后做了简单核查",
		"身边人讨论天气、健康或环境变化",
		"看到一个倡议或试点后想到日常执行成本",
		"信息很多但说法不一，需要给判断留一点余地",
	),
	"loose_social": (
		"随手记录一个不大不小的困扰",
		"想问问大家有没有类似经验",
		"今天情绪被一件普通小事带动了一下",
		"把一个小发现先记下来",
	),
}
STYLE_POOL = {
	"interest_hobby": ("经验分享", "复盘记录", "小技巧", "试用感受"),
	"everyday_life": ("生活记录", "轻量吐槽", "求建议", "家庭备忘"),
	"community_public": ("观察记录", "温和讨论", "信息整理", "现场见闻"),
	"light_public_issue": ("信息核查", "转述见闻", "提醒建议", "谨慎感想"),
	"loose_social": ("碎碎念", "求建议", "情绪记录", "随手一问"),
}
TONE_POOL = ("平实", "轻微困惑", "有点感慨", "温和提醒", "认真复盘", "带一点自嘲", "谨慎观察")


def _load_json(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(value, dict):
		raise ValueError(f"JSON root must be an object: {path}")
	return value


def _write_json(path: Path, value: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(value: Any) -> str:
	raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def _rng(seed: str, *parts: str) -> random.Random:
	digest = hashlib.sha256("\x1f".join((seed, *parts)).encode("utf-8")).digest()
	return random.Random(int.from_bytes(digest[:16], "big"))


def _runtime_llm_config(config_path: Path) -> tuple[Any, str, dict[str, Any]]:
	config = _load_json(config_path)
	env = dict(config["env"])
	api_key = str(env.get("LLM_API_KEY", "") or "").strip()
	if not api_key:
		key_env = str(env.get("LLM_API_KEY_ENV", "") or "").strip()
		if key_env:
			import os

			api_key = str(os.environ.get(key_env, "") or "").strip()
	if not api_key:
		raise ValueError("LLM API key is missing; set LLM_API_KEY or configure env.LLM_API_KEY")
	extra_raw = str(env.get("LLM_REQUEST_EXTRA_JSON", "") or "").strip()
	extra = json.loads(extra_raw) if extra_raw else {}
	client = build_chat_provider(
		{
			"protocol": str(env["LLM_PROVIDER"]),
			"base_url": str(env["LLM_BASE_URL"]),
			"api_prefix": str(env.get("LLM_API_PREFIX", "/v1")),
			"api_key": api_key,
			"timeout_seconds": int(str(env.get("LLM_TIMEOUT_SECONDS", 120))),
			"max_retries": int(str(env.get("LLM_MAX_RETRIES", 2))),
		}
	)
	model = str(env.get("SOCIAL_BACKGROUND_POST_MODEL") or env.get("LLM_PLANNER_MODEL") or env.get("SOCIAL_WORKFLOW_MODEL") or "").strip()
	if not model:
		raise ValueError("LLM model is missing; set SOCIAL_BACKGROUND_POST_MODEL, LLM_PLANNER_MODEL, or SOCIAL_WORKFLOW_MODEL")
	return client, model, extra


def _compact_background(text: str, *, max_chars: int = 360) -> str:
	cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
	return cleaned[:max_chars] + "..." if len(cleaned) > max_chars else cleaned


def _profile_cards_from_world(world_path: Path) -> list[dict[str, Any]]:
	world = _load_json(world_path)
	cards: list[dict[str, Any]] = []
	for location in list(world.get("locations") or []):
		if not isinstance(location, dict):
			continue
		for entity in list(location.get("entities") or []):
			if not isinstance(entity, dict):
				continue
			overrides = entity.get("component_overrides")
			if not isinstance(overrides, dict):
				continue
			identity = overrides.get("sea_level_social_experiment:SocialIdentityComponent")
			if not isinstance(identity, dict):
				continue
			profile_id = str(identity.get("profile_id", "") or "").strip()
			background = str(identity.get("natural_language_background", "") or "").strip()
			big_five = identity.get("big_five")
			if not profile_id or not background or not isinstance(big_five, dict):
				continue
			cards.append(
				{
					"profile_id": profile_id,
					"agent_id": str(entity.get("instance_id", "") or ""),
					"natural_language_background_excerpt": _compact_background(background),
					"big_five": {str(key): float(value) for key, value in big_five.items() if isinstance(value, (int, float)) and not isinstance(value, bool)},
				}
			)
	if not cards:
		raise ValueError(f"no social identity profiles found in {world_path}")
	return sorted(cards, key=lambda item: str(item["profile_id"]))


def _profiles_from_population(path: Path) -> list[dict[str, Any]]:
	population = _load_json(path)
	profiles = population.get("profiles")
	if not isinstance(profiles, list):
		raise ValueError(f"population has no profiles array: {path}")
	cards: list[dict[str, Any]] = []
	for profile in profiles:
		if not isinstance(profile, dict):
			continue
		profile_id = str(profile.get("profile_id", "") or "").strip()
		if not profile_id:
			continue
		cards.append(
			{
				"profile_id": profile_id,
				"agent_id": "",
				"natural_language_background_excerpt": str(profile.get("summary_line", "") or "").strip(),
				"big_five": dict(profile.get("personality", {}) or {}),
				"raw_interests": dict(profile.get("interests", {}) or {}),
			}
		)
	if not cards:
		raise ValueError(f"no profiles found in {path}")
	return sorted(cards, key=lambda item: str(item["profile_id"]))


def _load_profile_cards(profile_source: Path) -> list[dict[str, Any]]:
	if profile_source.name.lower().endswith("world.json"):
		return _profile_cards_from_world(profile_source)
	return _profiles_from_population(profile_source)


def _choice(rng: random.Random, items: Iterable[str]) -> str:
	seq = list(items)
	if not seq:
		raise ValueError("cannot choose from an empty sequence")
	return seq[rng.randrange(len(seq))]


def _sample_topics(rng: random.Random, bucket: str, index: int) -> list[str]:
	pool = list(BUCKET_TOPIC_POOL[bucket])
	if bucket == "light_public_issue" and index % 5 == 0:
		topics = ["environment", "general_knowledge"]
	else:
		topics = [_choice(rng, pool)]
		if rng.random() < 0.38:
			other = _choice(rng, [item for item in pool if item != topics[0]])
			topics.append(other)
	return list(dict.fromkeys(topics))[:2]


def _hashtags(rng: random.Random, topics: list[str]) -> list[str]:
	candidates: list[str] = []
	for topic in topics:
		candidates.extend(TOPIC_HASHTAGS.get(topic, (topic,)))
	rng.shuffle(candidates)
	out = list(dict.fromkeys(candidates))[: rng.choice((2, 2, 3))]
	return out or ["日常记录"]


def build_source_cards(*, seed: str, profile_cards: list[dict[str, Any]], count: int = POST_COUNT) -> dict[str, Any]:
	if int(count) != POST_COUNT:
		raise ValueError(f"background post count is fixed at {POST_COUNT}")
	if len(profile_cards) < 1:
		raise ValueError("profile_cards must not be empty")
	publishers = [
		{"account_id": f"background_publisher_{index:03d}", "display_name": PUBLISHER_NAMES[index - 1]}
		for index in range(1, PUBLISHER_COUNT + 1)
	]
	buckets = [bucket for bucket, bucket_count in PLAN_BUCKETS for _ in range(bucket_count)]
	rng = _rng(seed, "source_cards")
	rng.shuffle(buckets)
	profile_rng = _rng(seed, "profile_assignment")
	profile_indices = list(range(len(profile_cards)))
	profile_rng.shuffle(profile_indices)
	cards: list[dict[str, Any]] = []
	for index, bucket in enumerate(buckets, start=1):
		card_rng = _rng(seed, f"post_{index:03d}")
		profile = profile_cards[profile_indices[(index - 1) % len(profile_indices)]]
		topics = _sample_topics(card_rng, bucket, index)
		publisher = publishers[(index - 1) % len(publishers)]
		cards.append(
			{
				"post_id": f"background_{index:03d}",
				"account_id": publisher["account_id"],
				"publisher_display_name": publisher["display_name"],
				"bucket": bucket,
				"bucket_label": BUCKET_LABELS[bucket],
				"author_basis": {
					"kind": "profile_inspired_background_user",
					"profile_id": str(profile["profile_id"]),
					"agent_id": str(profile.get("agent_id", "") or ""),
					"background_excerpt": str(profile.get("natural_language_background_excerpt", "") or ""),
					"big_five": dict(profile.get("big_five", {}) or {}),
				},
				"ranking_topics": topics,
				"display_hashtags": _hashtags(card_rng, topics),
				"content_style": _choice(card_rng, STYLE_POOL[bucket]),
				"life_scene": _choice(card_rng, SCENE_POOL[bucket]),
				"emotional_tone": _choice(card_rng, TONE_POOL),
				"length_chars": {"min": 130, "max": 210},
			}
		)
	return {
		"schema_version": SOURCE_CARD_SCHEMA,
		"generation": {
			"seed": seed,
			"post_count": len(cards),
			"publisher_count": len(publishers),
			"bucket_counts": dict(Counter(card["bucket"] for card in cards)),
			"profile_source_count": len(profile_cards),
		},
		"publishers": publishers,
		"source_cards": cards,
	}


def _prompt(card: Mapping[str, Any]) -> list[dict[str, str]]:
	system = (
		"你是中文社交平台背景内容池的生成器。请根据 source card 写一条自然的普通社交平台帖子。"
		"这些帖子用于仿真实验里的背景内容，不是广告、新闻稿、宣传稿或问卷材料。"
		"写法要像普通用户或轻量内容号在休息时间看到、经历或想到的一件事。"
		"可以发散，但必须保留 source card 的主题、场景、语气和发布风格。"
		"不要提及 source card、实验、agent、画像、仿真或生成规则。"
	)
	user = f"""
请为下面的 source card 生成一条中文社交平台背景帖。

输出契约：
1. 只输出 JSON 对象，不输出解释性正文。
2. 字段必须是 post_id、text、ranking_topics、display_hashtags。
3. post_id、ranking_topics、display_hashtags 必须原样复制 source card。
4. text 长度控制在 130-210 个中文字符左右，可以一段或两段，不要超过 230 字。
5. text 不能写成标题党、新闻通稿、政策宣传或知识百科；要有具体生活场景、轻微个人判断或情绪。
6. text 不要包含“请点赞/转发/评论”、不要刻意煽动传播。
7. 不要直接讨论海平面上升；轻公共议题可以涉及天气、健康、环保、技术或社区，但保持日常化。
8. 如果 author_basis 给出了人物片段，只借用其生活处境和表达气质，不要复制原文，不要暴露 profile_id。

source card：
{json.dumps(card, ensure_ascii=False, indent=2)}
""".strip()
	return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_json_object(text: str) -> dict[str, Any]:
	def _try_load(candidate: str) -> dict[str, Any] | None:
		candidate = str(candidate or "").strip()
		if not candidate:
			return None
		try:
			value = json.loads(candidate)
		except json.JSONDecodeError:
			return None
		if not isinstance(value, dict):
			raise ValueError("LLM response JSON must be an object")
		return value

	def _field_value_start(candidate: str, field_name: str) -> int:
		match = re.search(rf'"{re.escape(field_name)}"\s*:\s*', candidate)
		return int(match.end()) if match else -1

	def _decode_loose_json_string(value: str) -> str:
		out: list[str] = []
		escape = False
		for ch in str(value):
			if ch == '"' and not escape:
				out.append(r"\"")
			else:
				out.append(ch)
			if escape:
				escape = False
			elif ch == "\\":
				escape = True
		try:
			return str(json.loads('"' + "".join(out) + '"'))
		except json.JSONDecodeError:
			return str(value)

	def _loose_string_field(candidate: str, field_name: str) -> str | None:
		start = _field_value_start(candidate, field_name)
		if start < 0 or start >= len(candidate) or candidate[start] != '"':
			return None
		i = start + 1
		escape = False
		while i < len(candidate):
			ch = candidate[i]
			if escape:
				escape = False
				i += 1
				continue
			if ch == "\\":
				escape = True
				i += 1
				continue
			if ch == '"':
				j = i + 1
				while j < len(candidate) and candidate[j] in " \t\r\n":
					j += 1
				if j >= len(candidate) or candidate[j] in ",}]":
					return _decode_loose_json_string(candidate[start + 1 : i])
			i += 1
		return None

	def _balanced_span_from(candidate: str, start: int, open_ch: str, close_ch: str) -> str | None:
		if start < 0 or start >= len(candidate) or candidate[start] != open_ch:
			return None
		depth = 1
		in_str = False
		escape = False
		j = start + 1
		while j < len(candidate):
			ch = candidate[j]
			if in_str:
				if escape:
					escape = False
				elif ch == "\\":
					escape = True
				elif ch == '"':
					in_str = False
				j += 1
				continue
			if ch == '"':
				in_str = True
			elif ch == open_ch:
				depth += 1
			elif ch == close_ch:
				depth -= 1
				if depth == 0:
					return candidate[start : j + 1]
			j += 1
		return None

	def _array_field(candidate: str, field_name: str) -> list[Any] | None:
		start = _field_value_start(candidate, field_name)
		if start < 0 or start >= len(candidate) or candidate[start] != "[":
			return None
		span = _balanced_span_from(candidate, start, "[", "]")
		if span is None:
			return None
		try:
			value = json.loads(span)
		except json.JSONDecodeError:
			return None
		return value if isinstance(value, list) else None

	def _loose_contract_object(candidate: str) -> dict[str, Any] | None:
		post_id = _loose_string_field(candidate, "post_id")
		body = _loose_string_field(candidate, "text")
		topics = _array_field(candidate, "ranking_topics")
		hashtags = _array_field(candidate, "display_hashtags")
		if post_id is None or body is None or topics is None or hashtags is None:
			return None
		return {"post_id": post_id, "text": body, "ranking_topics": topics, "display_hashtags": hashtags}

	raw = str(text or "").strip()
	if not raw:
		raise ValueError("LLM response is empty")
	for candidate in (raw, *re.findall(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```", raw)):
		candidate = str(candidate or "").strip()
		if not candidate:
			continue
		value = _try_load(candidate)
		if value is not None:
			return value
		value = _loose_contract_object(candidate)
		if value is not None:
			return value
	start, end = raw.find("{"), raw.rfind("}")
	if start < 0 or end < start:
		raise ValueError("LLM response did not contain a JSON object")
	candidate = raw[start : end + 1]
	value = _try_load(candidate)
	if value is not None:
		return value
	value = _loose_contract_object(candidate)
	if value is not None:
		return value
	raise ValueError("LLM response did not contain a valid background post JSON object")


def _normalize_post(card: Mapping[str, Any], generated: Mapping[str, Any]) -> dict[str, Any]:
	expected_keys = {"post_id", "text", "ranking_topics", "display_hashtags"}
	if not expected_keys <= set(generated):
		raise ValueError(f"LLM response must contain {sorted(expected_keys)}")
	if str(generated["post_id"]) != str(card["post_id"]):
		raise ValueError("LLM response changed post_id")
	text = str(generated["text"] or "").strip()
	text = re.sub(r"\n{3,}", "\n\n", text)
	if not 110 <= len(text) <= 260:
		raise ValueError(f"text length out of bounds: {len(text)}")
	for forbidden in ("海平面", "仿真实验", "实验任务", "agent", "source card", "profile_id", "仿真"):
		if forbidden in text:
			raise ValueError(f"text contains forbidden marker: {forbidden}")
	if list(map(str, generated["ranking_topics"])) != list(map(str, card["ranking_topics"])):
		raise ValueError("LLM response changed ranking_topics")
	if list(map(str, generated["display_hashtags"])) != list(map(str, card["display_hashtags"])):
		raise ValueError("LLM response changed display_hashtags")
	return {
		"post_id": str(card["post_id"]),
		"account_id": str(card["account_id"]),
		"text": text,
		"ranking_topics": list(card["ranking_topics"]),
		"display_hashtags": list(card["display_hashtags"]),
	}


def _render_deterministic(card: Mapping[str, Any]) -> dict[str, Any]:
	topics = "、".join(map(str, card["ranking_topics"]))
	hashtags = "、".join(f"#{item}" for item in card["display_hashtags"])
	text = (
		f"{card['life_scene']}，顺手记下这点感受。这个话题和{topics}有关，但落到生活里往往不是大道理，"
		f"而是时间、精力和身边人的配合。今天的体会是，先把问题说具体，再找一个能坚持的小动作，"
		f"比一开始就追求完美更容易。{hashtags}"
	)
	return {
		"post_id": str(card["post_id"]),
		"account_id": str(card["account_id"]),
		"text": text[:220],
		"ranking_topics": list(card["ranking_topics"]),
		"display_hashtags": list(card["display_hashtags"]),
	}


def generate_posts_with_llm(
	*,
	source_cards: dict[str, Any],
	config_path: Path,
	output_jsonl_path: Path,
	concurrency: int,
	temperature: float,
	max_tokens: int,
) -> list[dict[str, Any]]:
	client, model, extra = _runtime_llm_config(config_path)
	cards = [dict(card) for card in list(source_cards["source_cards"])]
	output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
	existing: dict[str, dict[str, Any]] = {}
	if output_jsonl_path.exists():
		for line in output_jsonl_path.read_text(encoding="utf-8").splitlines():
			if not line.strip():
				continue
			try:
				row = json.loads(line)
			except json.JSONDecodeError:
				continue
			if not isinstance(row, dict) or row.get("status") != "ok" or not isinstance(row.get("generated"), dict):
				continue
			existing[str(row.get("post_id", "") or "")] = dict(row)
	rows: list[dict[str, Any]] = [
		dict(existing[str(card["post_id"])])
		for card in cards
		if str(card["post_id"]) in existing and str(existing[str(card["post_id"])].get("source_card_fingerprint", "")) == _sha256(card)
	]
	preserved_ids = {str(row["post_id"]) for row in rows}
	pending_cards = [card for card in cards if str(card["post_id"]) not in preserved_ids]
	if preserved_ids:
		print(f"reusing {len(preserved_ids)} successful generated post(s) from {output_jsonl_path}")

	def generate_one(card: dict[str, Any]) -> dict[str, Any]:
		text = client.chat_text(
			messages=_prompt(card),
			model=model,
			temperature=float(temperature),
			max_tokens=int(max_tokens),
			response_format=None,
			extra=extra,
		)
		post = _normalize_post(card, _parse_json_object(text))
		return {
			"post_id": str(card["post_id"]),
			"status": "ok",
			"source_card_fingerprint": _sha256(card),
			"generated": post,
			"raw_response": text,
		}

	started = time.perf_counter()
	with concurrent.futures.ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
		future_map = {pool.submit(generate_one, card): card for card in pending_cards}
		for future in concurrent.futures.as_completed(future_map):
			card = future_map[future]
			try:
				row = future.result()
			except Exception as exc:
				row = {
					"post_id": str(card["post_id"]),
					"status": "error",
					"source_card_fingerprint": _sha256(card),
					"generated": None,
					"error": {"type": type(exc).__name__, "message": str(exc)},
				}
				print(f"failed {card['post_id']}: {exc}", file=sys.stderr)
			rows.append(row)
			print(f"processed {card['post_id']} ({len(rows)}/{len(cards)})")
	rows.sort(key=lambda item: str(item["post_id"]))
	output_jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
	failed = sum(row["status"] != "ok" for row in rows)
	print(f"completed={len(rows) - failed} failed={failed} elapsed_seconds={time.perf_counter() - started:.3f}")
	if failed:
		raise RuntimeError(f"background post generation failed for {failed} post(s); see {output_jsonl_path}")
	return [dict(row["generated"]) for row in rows]


def posts_from_jsonl(path: Path) -> list[dict[str, Any]]:
	posts: list[dict[str, Any]] = []
	for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
		if not line.strip():
			continue
		row = json.loads(line)
		if not isinstance(row, dict) or row.get("status") != "ok" or not isinstance(row.get("generated"), dict):
			raise ValueError(f"generated row {line_number} is not successful")
		posts.append(dict(row["generated"]))
	posts.sort(key=lambda item: str(item["post_id"]))
	if len(posts) != POST_COUNT:
		raise ValueError(f"generated post JSONL must contain exactly {POST_COUNT} successful posts")
	return posts


def build_background_catalog(publishers: list[dict[str, Any]], posts: list[dict[str, Any]], source_cards: dict[str, Any]) -> dict[str, Any]:
	if len(posts) != POST_COUNT:
		raise ValueError(f"background catalog must contain exactly {POST_COUNT} posts")
	publisher_ids = {str(item["account_id"]) for item in publishers}
	seen: set[str] = set()
	for post in posts:
		post_id = str(post.get("post_id", "") or "")
		if not post_id or post_id in seen:
			raise ValueError("background post IDs must be unique")
		seen.add(post_id)
		if str(post.get("account_id", "") or "") not in publisher_ids:
			raise ValueError(f"post {post_id} uses an unknown publisher")
		if not isinstance(post.get("ranking_topics"), list) or not post["ranking_topics"]:
			raise ValueError(f"post {post_id} has no ranking_topics")
		if not isinstance(post.get("display_hashtags"), list) or not post["display_hashtags"]:
			raise ValueError(f"post {post_id} has no display_hashtags")
	return {
		"schema_version": BACKGROUND_POSTS_SCHEMA,
		"generation": {
			"source_card_schema": source_cards["schema_version"],
			"source_cards_sha256": _sha256(source_cards),
			"bucket_counts": source_cards["generation"]["bucket_counts"],
		},
		"publishers": publishers,
		"posts": posts,
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate 200 LLM-written background posts for the sea-level social experiment.")
	parser.add_argument("--seed", default="sea-level-background-posts-2026-08-v1")
	parser.add_argument("--profile-source", default="Packages/SeaLevelSocialExperiment/Data/World.json")
	parser.add_argument("--source-cards-output", default="Packages/SeaLevelSocialExperiment/Study/background_post_source_cards.v1.json")
	parser.add_argument("--output", default="Packages/SeaLevelSocialExperiment/Study/background_posts.v1.json")
	parser.add_argument("--llm-config", default="")
	parser.add_argument("--generated-jsonl", default="Packages/SeaLevelSocialExperiment/Study/background_posts.generated.v1.jsonl")
	parser.add_argument("--concurrency", type=int, default=8)
	parser.add_argument("--temperature", type=float, default=0.8)
	parser.add_argument("--max-tokens", type=int, default=900)
	parser.add_argument("--from-jsonl", default="", help="Build the final catalog from an existing successful generation JSONL.")
	parser.add_argument("--deterministic-draft", action="store_true", help="Generate placeholder posts without calling an LLM; useful for tests.")
	args = parser.parse_args()

	profile_source = (ROOT / args.profile_source).resolve()
	source_cards_path = (ROOT / args.source_cards_output).resolve()
	output_path = (ROOT / args.output).resolve()
	jsonl_path = (ROOT / args.generated_jsonl).resolve()
	profile_cards = _load_profile_cards(profile_source)
	source_cards = build_source_cards(seed=str(args.seed), profile_cards=profile_cards, count=POST_COUNT)
	_write_json(source_cards_path, source_cards)
	if args.from_jsonl:
		posts = posts_from_jsonl((ROOT / args.from_jsonl).resolve())
	elif args.deterministic_draft:
		posts = [_render_deterministic(card) for card in source_cards["source_cards"]]
	else:
		if not args.llm_config:
			raise ValueError("--llm-config is required unless --from-jsonl or --deterministic-draft is used")
		posts = generate_posts_with_llm(
			source_cards=source_cards,
			config_path=(ROOT / args.llm_config).resolve(),
			output_jsonl_path=jsonl_path,
			concurrency=int(args.concurrency),
			temperature=float(args.temperature),
			max_tokens=int(args.max_tokens),
		)
	catalog = build_background_catalog(list(source_cards["publishers"]), posts, source_cards)
	_write_json(output_path, catalog)
	print(
		json.dumps(
			{
				"post_count": len(posts),
				"publisher_count": len(source_cards["publishers"]),
				"source_cards_sha256": _file_sha256(source_cards_path),
				"background_posts_sha256": _file_sha256(output_path),
				"bucket_counts": source_cards["generation"]["bucket_counts"],
			},
			ensure_ascii=False,
			indent=2,
		)
	)


if __name__ == "__main__":
	main()
