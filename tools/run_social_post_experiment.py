from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from KERN.llm.provider_factory import build_chat_provider


TRANSIENT_CONNECTION_PATTERNS = (
	"WinError 10061",
	"Connection refused",
	"actively refused",
	"目标计算机积极拒绝",
	"gateway_error",
	"Service Unavailable",
	"no healthy workers",
	"is unavailable",
)

DEFAULT_AGENTS_PATH = "KERN/external_runtimes/social_profiles/generated_social_agent_backgrounds.jsonl"


POSTS: dict[str, dict[str, str]] = {
	"high_consequence_low_solution": {
		"label": "高后果 + 低解决方案",
		"text": "想象一下，一个直径不到5毫米的塑料颗粒，从你的洗发水瓶或塑料袋上脱落。它开始了一场漫长的漂流，穿过海洋与土壤，悄悄搭上了食物链的便车。最终，它可能抵达我们的餐桌，潜入人体。科学家发现，这些难以降解的“漂流者”，并非无害的过客。它们在胃肠道、呼吸道等部位沉积，引发局部炎症与肺部损伤；它们释放的双酚A、邻苯二甲酸盐等有毒添加剂，会干扰你的内分泌系统，导致激素失衡，影响生殖发育、新陈代谢和免疫功能；更危险的是，它们可能吸附环境中的持久性有机污染物和重金属，一并带入体内，对细胞造成损伤，增加癌症、心血管疾病、神经退行性疾病等慢性病的风险。但你不必坐以待毙。要减少微塑料摄入，最简单的办法就在你手边：把水烧开再喝，并用不锈钢或玻璃杯代替塑料杯。",
	},
	"high_consequence_high_solution": {
		"label": "高后果 + 高解决方案",
		"text": "微塑料经由食物链进入人体。它们在胃肠道、呼吸道沉积，引发炎症与肺部损伤；它们释放的双酚A、邻苯二甲酸盐等有毒添加剂，会干扰你的内分泌系统，导致激素失衡，影响生殖发育、新陈代谢和免疫功能；更危险的是，它们可能吸附环境中的持久性有机污染物和重金属，对细胞造成损伤，增加癌症、心血管疾病、神经退行性疾病等慢性病的风险。但你不必坐以待毙。要减少微塑料摄入，可以把水烧开再喝，并用不锈钢或玻璃杯代替塑料杯。研究表明，把硬水烧开并简单过滤，能去除水中80%以上的微塑料，水温越高、水越硬，效果越好。但若用塑料杯盛装，杯壁因磨损和高温脱落的微塑料会让你前功尽弃。不锈钢与玻璃杯化学性质稳定、耐热、表面坚硬，几乎不释放微塑料，能守住这杯净水的最后一道防线。",
	},
	"low_consequence_low_solution": {
		"label": "低后果 + 低解决方案",
		"text": "从城市街道到偏远极地，从地表径流到深海沉积物，微塑料的踪迹几乎遍及地球各个角落。它们极其稳定，能在土壤、河流和海洋中存留数十年甚至更久，你可能每天都在接触它们，却浑然不觉。想象一下，一个直径不到5毫米的塑料颗粒，从你的洗发水瓶或塑料袋上无声脱落。它微小到肉眼几乎看不见，却开始了一场漫长的漂流，穿过海洋与土壤，悄悄搭上了食物链的便车。从浮游生物到小鱼，再到大鱼，不断累积。最终，它可能抵达我们的餐桌，潜入人体。科学家发现，这些难以降解的“漂流者”，并非无害的过客。它们可能对人体产生不利影响，包括潜在的炎症反应、内分泌干扰和细胞损伤。但你不必坐以待毙。要减少微塑料摄入，最简单的办法就在你手边：把水烧开再喝，并用不锈钢或玻璃杯代替塑料杯。",
	},
	"low_consequence_high_solution": {
		"label": "低后果 + 高解决方案",
		"text": "想象一下，一个直径不到5毫米的塑料颗粒，从你的洗发水瓶或塑料袋上脱落。它开始了一场漫长的漂流，穿过海洋与土壤，悄悄搭上了食物链的便车。最终，它可能抵达我们的餐桌，潜入人体。科学家发现，这些难以降解的“漂流者”，并非无害的过客。它们可能对人体产生不利影响，包括潜在的炎症反应、内分泌干扰和细胞损伤。但你不必坐以待毙。要减少微塑料摄入，最简单的办法就在你手边：把水烧开再喝，并用不锈钢或玻璃杯代替塑料杯。研究表明，把硬水烧开并简单过滤，能去除水中80%以上的微塑料，水温越高、水越硬，效果越好。但若用塑料杯盛装，杯壁因磨损和高温脱落的微塑料会让你前功尽弃。不锈钢与玻璃杯化学性质稳定、耐热、表面坚硬，几乎不释放微塑料，能守住这杯净水的最后一道防线。",
	},
}


def _condition_label(consequence_level: str, solution_level: str) -> str:
	consequence = "高后果" if consequence_level == "high" else "低后果"
	solution = "高解决方案" if solution_level == "high" else "低解决方案"
	return f"{consequence} + {solution}"


def _load_posts(path: Path | None) -> dict[str, dict[str, str]]:
	if path is None:
		return {post_id: dict(post) for post_id, post in POSTS.items()}
	raw = _load_json(path)
	posts: dict[str, dict[str, str]] = {}
	for stimulus_set in list(raw.get("stimulus_sets", []) or []):
		if not isinstance(stimulus_set, dict):
			continue
		set_id = str(stimulus_set.get("stimulus_set_id", "") or "").strip()
		topic_id = str(stimulus_set.get("topic_id", "") or "").strip()
		topic_label = str(stimulus_set.get("topic_label", "") or topic_id or set_id).strip()
		for post in list(stimulus_set.get("posts", []) or []):
			if not isinstance(post, dict):
				continue
			post_id = str(post.get("post_id", "") or "").strip()
			if not post_id:
				raise ValueError("stimulus post_id must not be blank")
			consequence_level = str(post.get("consequence_level", "") or "").strip()
			solution_level = str(post.get("solution_level", "") or "").strip()
			text = str(post.get("text", "") or "").strip()
			if not text:
				raise ValueError(f"stimulus post {post_id} text must not be blank")
			if post_id in posts:
				raise ValueError(f"duplicate stimulus post_id: {post_id}")
			condition_label = _condition_label(consequence_level, solution_level)
			posts[post_id] = {
				"label": f"{topic_label}｜{condition_label}",
				"text": text,
				"stimulus_set_id": set_id,
				"topic_id": topic_id,
				"topic_label": topic_label,
				"consequence_level": consequence_level,
				"solution_level": solution_level,
				"condition_label": condition_label,
			}
	if not posts:
		raise ValueError(f"no posts found in stimulus file: {path}")
	return posts


def _load_json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _runtime_llm_config(config_path: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
	config = _load_json(config_path)
	env = dict(config["env"])
	extra_raw = str(env.get("LLM_REQUEST_EXTRA_JSON", "") or "").strip()
	extra = json.loads(extra_raw) if extra_raw else {}
	provider_config = {
		"protocol": str(env["LLM_PROVIDER"]),
		"base_url": str(env["LLM_BASE_URL"]),
		"api_prefix": str(env.get("LLM_API_PREFIX", "/v1")),
		"api_key": str(env["LLM_API_KEY"]),
		"timeout_seconds": int(str(env.get("LLM_TIMEOUT_SECONDS", 60))),
		"max_retries": int(str(env.get("LLM_MAX_RETRIES", 0))),
	}
	return provider_config, str(env["LLM_PLANNER_MODEL"]), extra


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


def _normalize_result(raw: dict[str, Any], agent: dict[str, Any], post_id: str, posts: dict[str, dict[str, str]]) -> dict[str, Any]:
	action_keys = ("like", "comment", "share", "save", "follow_author", "report", "no_action")
	actions_raw = raw.get("actions", [])
	actions = [str(item).strip() for item in actions_raw] if isinstance(actions_raw, list) else []
	actions = [item for item in actions if item in action_keys]
	no_action = bool(raw.get("no_action", False)) or "no_action" in actions or not actions
	if no_action:
		actions = ["no_action"]
	flags = {key: key in actions for key in action_keys}
	flags["no_action"] = no_action
	return {
		"agent_id": str(agent["agent_id"]),
		"profile_id": str(agent["profile_id"]),
		"generated_name": str(agent["generated"]["generated_name"]),
		"post_condition": post_id,
		"post_label": posts[post_id]["label"],
		"repeat_index": int(agent.get("_repeat_index", 1)),
		"actions": actions,
		**flags,
		"impression": str(raw.get("impression", "") or "").strip(),
		"raw_response": raw,
	}


def _messages(agent: dict[str, Any], post_id: str, posts: dict[str, dict[str, str]]) -> list[dict[str, str]]:
	card = agent["source_card"]
	generated = agent["generated"]
	system = (
		"你正在参加一个社交平台行为仿真实验。请严格扮演给定用户，判断这个用户看到帖子后最可能做出的平台行为。"
		"目标是抽取大语言模型关于“这种人在这种内容下可能如何反应”的先验判断。"
	)
	user = f"""
请扮演下面这个中文社交平台用户，阅读帖子后输出 JSON 对象，不要输出 Markdown。

用户自然语言背景：
{generated["natural_language_background"]}

大五人格分数（0-1）：
- 开放性：{card["big_five"]["openness"]}
- 尽责性：{card["big_five"]["conscientiousness"]}
- 外向性：{card["big_five"]["extraversion"]}
- 宜人性：{card["big_five"]["agreeableness"]}
- 神经质：{card["big_five"]["neuroticism"]}

帖子条件：{posts[post_id]["label"]}
帖子正文：
{posts[post_id]["text"]}

可选平台行为：
- like：点赞
- comment：评论
- share：转发/分享
- save：收藏
- follow_author：关注作者
- report：举报
- no_action：不做任何行为

规则：
1. 可以同时做多个行为，例如同时点赞、评论、转发。
2. 也可以不做任何行为；不操作是一种有效选择，此时 actions 必须只包含 no_action。
3. 如果选择 no_action，不要再同时选择其他行为。
4. impression 用 1-3 句简短中文写读完帖子的直接感受或想法，不要分析人格，不要写评分。

输出 JSON 字段：
{{
  "actions": ["no_action"],
  "impression": ""
}}
""".strip()
	return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _is_transient_connection_error(error: BaseException | str) -> bool:
	text = str(error)
	return any(pattern in text for pattern in TRANSIENT_CONNECTION_PATTERNS)


def _call_one(
	job: dict[str, Any],
	provider_config: dict[str, Any],
	model: str,
	extra: dict[str, Any],
	posts: dict[str, dict[str, str]],
	*,
	temperature: float,
	connection_retry_attempts: int,
	connection_retry_cooldown_seconds: float,
) -> dict[str, Any]:
	client = build_chat_provider(provider_config)
	start = time.time()
	for attempt in range(max(1, int(connection_retry_attempts))):
		try:
			text = client.chat_text(
				messages=_messages(job["agent"], job["post_id"], posts),
				model=model,
				temperature=float(temperature),
				max_tokens=900,
				response_format={"type": "json_object"},
				extra=extra,
			)
			break
		except Exception as exc:
			if not _is_transient_connection_error(exc) or attempt >= int(connection_retry_attempts) - 1:
				raise
			sleep_seconds = max(0.0, float(connection_retry_cooldown_seconds)) * float(attempt + 1)
			print(
				f"transient connection error for {job['agent']['profile_id']} {job['post_id']}; "
				f"sleeping {sleep_seconds:.1f}s before retry {attempt + 2}/{connection_retry_attempts}: {exc}",
				flush=True,
			)
			time.sleep(sleep_seconds)
	parsed = _parse_json_object(text)
	result = _normalize_result(parsed, job["agent"], job["post_id"], posts)
	result["latency_seconds"] = round(time.time() - start, 3)
	return result


def run_experiment(
	*,
	config_path: Path,
	agents_path: Path,
	output_path: Path,
	sample_size: int,
	seed: int,
	concurrency: int,
	repeats: int = 1,
	temperature: float = 0.2,
	posts_path: Path | None = None,
	profile_ids: set[str] | None = None,
	post_conditions: set[str] | None = None,
	connection_retry_attempts: int = 3,
	connection_retry_cooldown_seconds: float = 20.0,
) -> None:
	provider_config, model, extra = _runtime_llm_config(config_path)
	posts = _load_posts(posts_path)
	rows = [json.loads(line) for line in agents_path.read_text(encoding="utf-8").splitlines() if line.strip()]
	for idx, row in enumerate(rows, 1):
		row["agent_id"] = f"agent_{idx:03d}"
	if profile_ids:
		selected = [row for row in rows if str(row.get("profile_id", "") or "") in profile_ids]
	else:
		rng = random.Random(seed)
		selected = rng.sample(rows, sample_size)
	available_posts = [post_id for post_id in posts.keys() if not post_conditions or post_id in post_conditions]
	jobs = []
	for agent in selected:
		for post_id in available_posts:
			for repeat_index in range(1, max(1, int(repeats)) + 1):
				job_agent = dict(agent)
				job_agent["_repeat_index"] = repeat_index
				jobs.append({"agent": job_agent, "post_id": post_id})
	results: list[dict[str, Any]] = []
	output_path.parent.mkdir(parents=True, exist_ok=True)
	total = len(jobs)
	started = time.perf_counter()
	completed = 0
	# Append each completed result immediately so Ctrl+C or a worker failure
	# preserves all records that have already finished.
	with output_path.open("w", encoding="utf-8") as output_file:
		print(f"incremental output: {output_path}", flush=True)
		pool = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
		try:
			future_map = {
				pool.submit(
					_call_one,
					job,
					provider_config,
					model,
					extra,
					posts,
					temperature=float(temperature),
					connection_retry_attempts=int(connection_retry_attempts),
					connection_retry_cooldown_seconds=float(connection_retry_cooldown_seconds),
				): job
				for job in jobs
			}
			for future in concurrent.futures.as_completed(future_map):
				job = future_map[future]
				try:
					result = future.result()
				except Exception as exc:
					agent = job["agent"]
					result = {
						"agent_id": str(agent["agent_id"]),
						"profile_id": str(agent["profile_id"]),
						"generated_name": str(agent["generated"]["generated_name"]),
						"post_condition": str(job["post_id"]),
						"post_label": posts[str(job["post_id"])]["label"],
						"repeat_index": int(agent.get("_repeat_index", 1)),
						"error": str(exc),
					}
				results.append(result)
				output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
				output_file.flush()
				completed += 1
				elapsed = time.perf_counter() - started
				average = elapsed / completed
				remaining = max(0.0, average * (total - completed))
				print(
					f"[{completed}/{total}] {result['profile_id']} {result['post_condition']} "
					f"repeat={result.get('repeat_index', 1)} "
					f"| elapsed={elapsed:.1f}s avg={average:.2f}s/call ETA={remaining:.1f}s",
					flush=True,
				)
		finally:
			pool.shutdown(wait=True, cancel_futures=True)
	print(f"finished total={total} elapsed={time.perf_counter() - started:.1f}s", flush=True)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", default="runtime_config.camping.llm.local.json")
	parser.add_argument("--agents", default=DEFAULT_AGENTS_PATH)
	parser.add_argument("--output", default="tmp/social_post_experiment_sample_5.jsonl")
	parser.add_argument("--sample-size", type=int, default=5)
	parser.add_argument("--seed", type=int, default=20260726)
	parser.add_argument("--concurrency", type=int, default=50)
	parser.add_argument("--repeats", type=int, default=1, help="Number of repeated LLM calls for each agent/post pair.")
	parser.add_argument("--temperature", type=float, default=0.2)
	parser.add_argument("--posts", default="tmp/social_post_stimuli_10_sets.json", help="Stimulus JSON file. Omit to use built-in posts.")
	parser.add_argument("--profile-ids", default="", help="Comma-separated profile IDs to run. Overrides random sampling when set.")
	parser.add_argument("--post-conditions", default="", help="Comma-separated post condition IDs to run.")
	parser.add_argument("--connection-retry-attempts", type=int, default=3, help="Extra local attempts for transient connection/gateway errors.")
	parser.add_argument("--connection-retry-cooldown-seconds", type=float, default=20.0, help="Sleep before retrying transient connection/gateway errors.")
	args = parser.parse_args()
	root = Path.cwd()
	profile_ids = {item.strip() for item in str(args.profile_ids or "").split(",") if item.strip()}
	post_conditions = {item.strip() for item in str(args.post_conditions or "").split(",") if item.strip()}
	run_experiment(
		config_path=(root / args.config).resolve(),
		agents_path=(root / args.agents).resolve(),
		output_path=(root / args.output).resolve(),
		sample_size=int(args.sample_size),
		seed=int(args.seed),
		concurrency=int(args.concurrency),
		repeats=int(args.repeats),
		temperature=float(args.temperature),
		posts_path=(root / args.posts).resolve() if str(args.posts or "").strip() else None,
		profile_ids=profile_ids or None,
		post_conditions=post_conditions or None,
		connection_retry_attempts=int(args.connection_retry_attempts),
		connection_retry_cooldown_seconds=float(args.connection_retry_cooldown_seconds),
	)


if __name__ == "__main__":
	main()
