from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import generate_social_profiles


DEFAULT_OUTPUT_DIR = ROOT / "Packages" / "SU7Crisis" / "Data"
DEFAULT_CONFIG_PATH = ROOT / "runtime_config.su7_crisis.package.smoke.json"

EVENT_CLASSES = {
	"incident_initial": "事故初始信息",
	"unverified_claim": "未证实归因/质疑",
	"technical_explanation": "技术解释",
	"empathy_response": "情绪与善后回应",
	"expert_context": "专家/第三方解释",
	"official_investigation": "调查进展",
	"platform_label": "平台提示",
	"background": "背景讨论",
}

STRATEGIES: dict[str, dict[str, Any]] = {
	"baseline": {
		"label": "Baseline: delayed response",
		"description": "未证实质疑先扩散，企业与第三方回应较晚出现。",
		"schedule": {
			"incident": 1,
			"claims": 2,
			"technical": 5,
			"empathy": 6,
			"expert": 7,
			"investigation": 9,
			"platform": 10,
		},
	},
	"technical_only": {
		"label": "Technical-only response",
		"description": "企业较快发布技术事实，但较少回应家属和情绪关切。",
		"schedule": {
			"incident": 1,
			"claims": 2,
			"technical": 3,
			"empathy": 8,
			"expert": 5,
			"investigation": 9,
			"platform": 10,
		},
	},
	"empathy_first": {
		"label": "Empathy-first staged response",
		"description": "先表达哀悼、善后和配合调查，再分阶段发布技术事实。",
		"schedule": {
			"incident": 1,
			"claims": 2,
			"empathy": 3,
			"technical": 4,
			"expert": 5,
			"investigation": 7,
			"platform": 8,
		},
	},
	"third_party_anchor": {
		"label": "Third-party anchor",
		"description": "专家、媒体和平台较早解释辅助驾驶边界，压低未证实归因。",
		"schedule": {
			"incident": 1,
			"claims": 2,
			"expert": 3,
			"technical": 4,
			"empathy": 5,
			"platform": 5,
			"investigation": 7,
		},
	},
}

BACKGROUND_AUTHORS = [
	("acc_auto_media", "Auto Lens 汽车观察", {"auto": 1.0, "ev": 0.8, "smart_driving": 0.8, "background": 0.5}),
	("acc_tech_forum", "智能车技术笔记", {"tech_explanation": 1.0, "smart_driving": 1.0, "ev": 0.8}),
	("acc_consumer_watch", "消费观察员", {"consumer_rights": 1.0, "brand_trust": 0.7, "safety": 0.7}),
	("acc_local_traffic", "高速出行提醒", {"traffic": 1.0, "safety": 0.9, "background": 0.6}),
	("acc_public_discussion", "公共议题速递", {"public_discussion": 1.0, "unverified_claim": 0.5, "empathy_response": 0.5}),
]

SYSTEM_ACCOUNTS = [
	{"account_id": "acc_incident_seed", "display_name": "现场信息汇总", "interests": {"incident_initial": 1.0, "safety": 0.8}},
	{"account_id": "acc_unverified_claims", "display_name": "车圈热议", "interests": {"unverified_claim": 1.0, "auto": 0.6}},
	{"account_id": "acc_xiaomi_official", "display_name": "小米汽车回应", "interests": {"technical_explanation": 1.0, "empathy_response": 0.8, "brand_trust": 1.0}},
	{"account_id": "acc_expert_ev", "display_name": "智能驾驶专家", "interests": {"expert_context": 1.0, "smart_driving": 1.0, "tech_explanation": 0.8}},
	{"account_id": "acc_investigation", "display_name": "调查进展发布", "interests": {"official_investigation": 1.0, "safety": 0.8}},
	{"account_id": "acc_platform_notice", "display_name": "平台治理提示", "interests": {"platform_label": 1.0, "unverified_claim": 0.4}},
]

BACKGROUND_TEXTS = [
	("最近智能电动车辅助驾驶功能讨论升温，很多车主开始关注 NOA 的使用边界。", ["background", "auto", "ev", "smart_driving"]),
	("高速施工路段的临时改道容易让驾驶者紧张，出行前最好确认导航和道路提示。", ["background", "traffic", "safety"]),
	("车主群里最近常有人问 AEB、NOA 和自动驾驶到底有什么区别。", ["background", "auto", "tech_explanation"]),
	("新能源汽车安全话题热度上升，很多潜在购车者会同时看技术测评和事故案例。", ["background", "ev", "safety", "consumer_rights"]),
	("公共事故讨论中，未经确认的视频和截图很容易被当作事实二次传播。", ["background", "public_discussion", "platform_label"]),
	("购车决策里，品牌信任、售后态度和安全解释往往和参数配置一样重要。", ["background", "brand_trust", "consumer_rights"]),
]


def _write_json(path: Path, data: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug(index: int) -> str:
	return f"{int(index):03d}"


def _display_name(profile: dict[str, Any], index: int) -> str:
	specifics = dict((profile.get("sample", {}) or {}).get("specifics", {}) or {})
	occupation = str(specifics.get("occupation", "") or "社交平台用户")
	return f"用户{_slug(index)}-{occupation}"


def _interest_weights(profile: dict[str, Any], rng: random.Random) -> dict[str, float]:
	sample = dict(profile.get("sample", {}) or {})
	weights = {
		"auto": rng.uniform(0.2, 0.85),
		"ev": rng.uniform(0.2, 0.85),
		"smart_driving": rng.uniform(0.15, 0.8),
		"safety": rng.uniform(0.25, 1.0),
		"consumer_rights": rng.uniform(0.15, 0.85),
		"brand_trust": rng.uniform(0.15, 0.85),
		"unverified_claim": rng.uniform(0.1, 0.75),
		"technical_explanation": rng.uniform(0.1, 0.85),
		"empathy_response": rng.uniform(0.1, 0.85),
		"expert_context": rng.uniform(0.1, 0.75),
	}
	media_style = str(sample.get("media_style", "") or "")
	platform = str(sample.get("platform_archetype", "") or "")
	occupation = str(sample.get("occupation_domain", "") or "")
	practical = [str(x.get("id", "")) for x in list(sample.get("practical_interests", []) or []) if isinstance(x, dict)]
	aspirational = [str(x.get("id", "")) for x in list(sample.get("aspirational_interests", []) or []) if isinstance(x, dict)]
	high_cost = [str(x.get("id", "")) for x in list(sample.get("high_cost_consumption_interests", []) or []) if isinstance(x, dict)]
	if media_style in {"news_commentary", "longform_reader"}:
		weights["technical_explanation"] += 0.25
		weights["expert_context"] += 0.2
		weights["unverified_claim"] -= 0.08
	if media_style in {"short_video_scroller", "visual_lifestyle"}:
		weights["unverified_claim"] += 0.2
		weights["empathy_response"] += 0.12
	if platform == "public_discussion":
		weights["consumer_rights"] += 0.2
		weights["brand_trust"] += 0.15
	if platform == "interest_community":
		weights["smart_driving"] += 0.18
		weights["expert_context"] += 0.12
	if occupation in {"technical", "creative_media"}:
		weights["technical_explanation"] += 0.15
		weights["smart_driving"] += 0.12
	if "premium_tech" in aspirational:
		weights["smart_driving"] += 0.2
		weights["ev"] += 0.15
	if "luxury_cars_watching" in aspirational or "luxury_car_purchase_planning" in high_cost:
		weights["auto"] += 0.25
		weights["brand_trust"] += 0.18
	if "motorsport" in aspirational:
		weights["auto"] += 0.15
	if "diy_repairs" in practical:
		weights["technical_explanation"] += 0.12
	return {k: round(min(1.0, max(0.05, float(v))), 2) for k, v in weights.items()}


def _activity_model(profile: dict[str, Any], rng: random.Random) -> dict[str, Any]:
	sample = dict(profile.get("sample", {}) or {})
	platform = str(sample.get("platform_archetype", "") or "")
	media = str(sample.get("media_style", "") or "")
	social = str(sample.get("social_style", "") or "")
	base = {
		"short_video_mass": 0.74,
		"public_discussion": 0.72,
		"private_social": 0.56,
		"lifestyle_discovery": 0.58,
		"interest_community": 0.60,
	}.get(platform, 0.58)
	if media == "quiet_low_media":
		base -= 0.22
	if media in {"news_commentary", "short_video_scroller"}:
		base += 0.12
	if social == "outgoing_connector":
		base += 0.1
	if social == "reserved_close_circle":
		base -= 0.08
	base += rng.uniform(-0.1, 0.1)
	expression = 0.25 + rng.uniform(0.0, 0.35)
	if social in {"outgoing_connector", "online_first"}:
		expression += 0.2
	if media == "quiet_low_media":
		expression -= 0.15
	routine = 0.66 + rng.uniform(-0.18, 0.18)
	if media == "quiet_low_media":
		routine += 0.12
	return {
		"base_activity_rate": round(min(0.95, max(0.08, base)), 2),
		"active_hours": [],
		"event_reaction_sensitivity": round(rng.uniform(0.3, 0.95), 2),
		"expression_opportunity_rate": round(min(0.95, max(0.05, expression)), 2),
		"routine_browse_rate": round(min(0.95, max(0.1, routine)), 2),
	}


def _agent_template() -> dict[str, Any]:
	return {
		"name": "Generated SU7 Crisis Agent",
		"components": {
			"TagComponent": {"tags": ["character", "agent", "social_crisis_participant"]},
			"AgentSetting": {
				"agent_name": "Generated SU7 Crisis Agent",
				"personality_summary": "A generated social-platform participant.",
				"common_knowledge_summary": "You follow social platform discussions about a serious smart EV accident. Make decisions only from your carried phone context and memories. Do not claim responsibility or technical facts that you cannot see.",
			},
			"AgentControlComponent": {},
			"MemoryComponent": {
				"short_term_queue": [],
				"short_term_max_entries": 14,
				"mid_term_prep_queue": [],
				"mid_term_prep_max_entries": 24,
				"mid_term_queue": [],
				"mid_term_max_entries": 12,
			},
			"StatusComponent": {"statuses": [], "expire_at_tick": {}},
			"ContainerComponent": {"slots": {"inventory": {"capacity_volume": 5, "capacity_count": 4, "accepted_tags": []}}},
			"DecisionArbiterComponent": {"rules": []},
			"SocialBehaviorComponent": {
				"base_activity_rate": 0.55,
				"active_hours": [],
				"event_reaction_sensitivity": 0.6,
				"expression_opportunity_rate": 0.35,
				"routine_browse_rate": 0.75,
			},
		},
	}


def _phone_template() -> dict[str, Any]:
	return {
		"name": "Generated SU7 Crisis Phone",
		"components": {
			"TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
			"DescriptionComponent": {
				"description": "A phone logged into a generated social account.",
				"base_description": "A phone.",
				"observed_description": "A phone showing a social media app.",
			},
			"ScreenComponent": {
				"runtime_id": "social",
				"account_id": "",
				"app": "social_platform",
				"view": "blank",
				"title": "",
				"feed_items": [],
				"current_post": None,
				"selected_post_id": "",
				"cursor": 0,
				"updated_tick": 0,
			},
		},
	}


def _event_posts(strategy: str) -> list[dict[str, Any]]:
	spec = STRATEGIES[strategy]
	s = dict(spec["schedule"])
	posts: list[dict[str, Any]] = [
		{
			"account_id": "acc_incident_seed",
			"post_id": "post_su7_incident_001",
			"text": "今晚看到一则高速严重事故消息：一辆智能电动车在施工改道路段发生碰撞并起火，伤亡情况令人揪心。具体原因还在调查。",
			"tags": ["incident_initial", "auto", "ev", "safety", "su7_event"],
			"tick": s["incident"],
		},
		{
			"account_id": "acc_unverified_claims",
			"post_id": "post_su7_unverified_001",
			"text": "有人说这次事故可能和辅助驾驶没识别施工隔离有关，也有人在问 AEB 为什么没有避免碰撞。现在各种说法都有，先观望。",
			"tags": ["unverified_claim", "smart_driving", "aeb", "su7_event"],
			"tick": s["claims"],
		},
		{
			"account_id": "acc_unverified_claims",
			"post_id": "post_su7_unverified_002",
			"text": "车门、起火、接管时机这些细节现在网上传得很乱。没有完整调查前，很多判断其实都是猜测。",
			"tags": ["unverified_claim", "safety", "public_discussion", "su7_event"],
			"tick": s["claims"] + 1,
		},
		{
			"account_id": "acc_xiaomi_official",
			"post_id": "post_su7_technical_001",
			"text": "关于事故车辆运行状态：企业已成立专项组并配合警方调查，已提交车辆行驶数据和系统运行信息。辅助驾驶不等于自动驾驶，具体责任需以调查结论为准。",
			"tags": ["technical_explanation", "brand_trust", "smart_driving", "su7_event"],
			"tick": s["technical"],
		},
		{
			"account_id": "acc_xiaomi_official",
			"post_id": "post_su7_empathy_001",
			"text": "对事故中逝去的生命深感痛心。我们会持续配合调查、与家属保持沟通，并在权威结论基础上回应社会关切。",
			"tags": ["empathy_response", "brand_trust", "su7_event"],
			"tick": s["empathy"],
		},
		{
			"account_id": "acc_expert_ev",
			"post_id": "post_su7_expert_001",
			"text": "从公共讨论角度看，NOA、AEB、人驾接管和施工改道路段是不同问题。辅助驾驶的边界应被讲清楚，但事故原因仍需等待完整调查。",
			"tags": ["expert_context", "technical_explanation", "smart_driving", "su7_event"],
			"tick": s["expert"],
		},
		{
			"account_id": "acc_investigation",
			"post_id": "post_su7_investigation_001",
			"text": "事故调查仍在进行。请以权威调查信息为准，不传播未经核实的事故责任判断、车门状态或起火原因。",
			"tags": ["official_investigation", "safety", "su7_event"],
			"tick": s["investigation"],
		},
		{
			"account_id": "acc_platform_notice",
			"post_id": "post_su7_platform_001",
			"text": "平台提示：涉及事故责任、伤亡细节和技术故障的内容请标注来源。未经证实的归因判断可能误导公众。",
			"tags": ["platform_label", "unverified_claim", "su7_event"],
			"tick": s["platform"],
		},
	]
	return posts


def build_dataset(count: int, seed: str, strategy: str) -> dict[str, Any]:
	if strategy not in STRATEGIES:
		raise ValueError(f"unknown strategy: {strategy}")
	rng = random.Random(f"{seed}|{strategy}")
	profiles = generate_social_profiles(count=count, seed=seed, include_debug=False)
	entities = {
		"SU7GeneratedAgent": _agent_template(),
		"SU7GeneratedPhone": _phone_template(),
	}
	world_entities = []
	nested_entities = []
	accounts = []
	follows = []
	profile_accounts = []
	for idx, profile in enumerate(profiles, start=1):
		slug = _slug(idx)
		agent_id = f"agent_su7_{slug}"
		phone_id = f"phone_su7_{slug}"
		account_id = f"acc_su7_{slug}"
		name = _display_name(profile, idx)
		background = str(profile.get("llm_background_prompt", "") or profile.get("summary_line", "") or "")
		personality = str(profile.get("summary_line", "") or name)
		common = (
			"你正在参与一个智能电动车严重事故后的社交平台讨论环境。"
			"你只应依据手机屏幕、近期记忆和自己的背景做出浏览、打开、评论、转发、点赞或发帖决定。"
			"不要声称已经知道事故责任，不要凭空引用看不到的帖子 ID。"
		)
		world_entities.append(
			{
				"instance_id": agent_id,
				"template_id": "SU7GeneratedAgent",
				"component_overrides": {
					"AgentSetting": {
						"agent_name": name,
						"personality_summary": personality + "\n" + background[:1200],
						"common_knowledge_summary": common,
					},
					"SocialBehaviorComponent": _activity_model(profile, rng),
				},
			}
		)
		nested_entities.append(
			{
				"instance_id": phone_id,
				"template_id": "SU7GeneratedPhone",
				"parent_container": agent_id,
				"component_overrides": {
					"ScreenComponent": {"account_id": account_id},
					"DescriptionComponent": {
						"description": f"A phone logged into {name}'s social account.",
						"observed_description": "A phone showing a social media app.",
					},
				},
			}
		)
		accounts.append(
			{
				"account_id": account_id,
				"display_name": name,
				"bio": str(profile.get("summary_line", "") or ""),
				"interests": _interest_weights(profile, rng),
			}
		)
		profile_accounts.append({"profile_id": str(profile.get("profile_id", "")), "account_id": account_id, "agent_id": agent_id, "phone_id": phone_id})

	static_accounts = [*SYSTEM_ACCOUNTS]
	for aid, display, interests in BACKGROUND_AUTHORS:
		static_accounts.append({"account_id": aid, "display_name": display, "interests": interests})

	follow_targets = [x["account_id"] for x in static_accounts]
	for account in accounts:
		aid = str(account["account_id"])
		for target in follow_targets:
			follows.append({"follower_id": aid, "followee_id": target, "tick": 0})
		for other in rng.sample([str(x["account_id"]) for x in accounts if x["account_id"] != aid], k=min(8, max(0, len(accounts) - 1))):
			follows.append({"follower_id": aid, "followee_id": other, "tick": 0})

	posts = []
	for idx, (text, tags) in enumerate(BACKGROUND_TEXTS, start=1):
		author_id = BACKGROUND_AUTHORS[(idx - 1) % len(BACKGROUND_AUTHORS)][0]
		posts.append({"account_id": author_id, "post_id": f"post_su7_background_{idx:03d}", "text": text, "tags": tags, "tick": 0})
	posts.extend(_event_posts(strategy))

	world = {
		"world_state": {"current_tick": 0},
		"locations": [
			{
				"location_id": "su7_public_discussion_room",
				"location_name": "SU7 Crisis Social Simulation",
				"description": "A virtual room used for 100-agent social-platform simulation of a technical crisis information event.",
				"entities": world_entities,
			}
		],
		"paths": [],
		"entities": nested_entities,
		"environment_scopes": [
			{
				"scope_id": "su7_crisis_env",
				"scope_type": "region",
				"location_ids": ["su7_public_discussion_room"],
				"priority": 0,
				"fields": {"light_level": 2},
				"conditions": [],
			}
		],
	}
	social_seed = {
		"scenario": "su7_crisis",
		"strategy": strategy,
		"event_classes": EVENT_CLASSES,
		"profile_accounts": profile_accounts,
		"accounts": [*accounts, *static_accounts],
		"posts": posts,
		"follows": follows,
	}
	return {"profiles": profiles, "profile_accounts": profile_accounts, "entities": entities, "world": world, "social_seed": social_seed}


def _reactions(max_agents_per_tick: int, max_decision_workers: int) -> dict[str, Any]:
	return {
		"rules": [
			{
				"id": "su7_world_tick_social_activity_gate",
				"on_event": "WorldTickAdvanced",
				"bundle": {
					"effects": [
						{
							"effect": "SocialActivityGateTick",
							"max_agents_per_tick": int(max_agents_per_tick),
							"max_actions_per_agent": 1,
							"default_screen_context_window_ticks": 2,
							"decision_mode": "parallel_decide_serial_commit",
							"max_decision_workers": int(max_decision_workers),
						}
					]
				},
			},
			{
				"id": "su7_world_tick_environment_condition",
				"on_event": "WorldTickAdvanced",
				"bundle": {"effects": [{"effect": "EnvironmentConditionTick"}]},
			},
			{
				"id": "su7_advance_tick_status",
				"on_event": "AdvanceTick",
				"condition": {"type": "has_component", "target": "event_entity", "component": "StatusComponent"},
				"bundle": {"effects": [{"effect": "StatusTick"}]},
			},
		]
	}


def _config(strategy: str, max_ticks: int) -> dict[str, Any]:
	run_name = f"su7_crisis_100agent_{strategy}"
	return {
		"packages": [{"path": "Packages/SU7Crisis", "world": True}],
		"env": {
			"USE_LLM": "1",
			"LOG_LEVEL": "warn",
			"LOG_CATEGORIES": "system,executor,interaction,checkpoint,llm",
			"MAX_TICKS": str(int(max_ticks)),
			"CHECKPOINT_DIR": f"checkpoints/{run_name}",
			"CHECKPOINT_EVERY_TICK": "1",
			"CHECKPOINT_SNAPSHOT_INTERVAL_TICKS": "5",
			"WORKFLOW_CONTRACT_ON_ERROR": "degrade_to_noop",
			"WORKFLOW_VIEW_PROFILE": "social_platform",
			"EXTERNAL_RUNTIMES_JSON": json.dumps(
				{
					"social": {
						"type": "sqlite_social_platform",
						"db_path": f"checkpoints/{run_name}/social.sqlite3",
						"reset_db": True,
						"seed_json": "Packages/SU7Crisis/Data/social_seed.json",
					}
				},
				ensure_ascii=False,
				separators=(",", ":"),
			),
		}
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate a 100-agent SU7 technical-crisis social simulation dataset.")
	parser.add_argument("--count", type=int, default=100, help="Number of generated social agents.")
	parser.add_argument("--seed", default="kern-su7-crisis-100-v1", help="Deterministic generation seed.")
	parser.add_argument("--strategy", choices=sorted(STRATEGIES.keys()), default="empathy_first", help="Crisis response strategy schedule.")
	parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Package Data directory to overwrite.")
	parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH), help="Runtime config path to write.")
	parser.add_argument("--max-ticks", type=int, default=12, help="MAX_TICKS for the generated runtime config.")
	parser.add_argument("--max-agents-per-tick", type=int, default=100, help="SocialActivityGateTick max_agents_per_tick.")
	parser.add_argument("--max-decision-workers", type=int, default=30, help="Parallel LLM decision workers.")
	args = parser.parse_args()

	output_dir = Path(args.output_dir)
	if not output_dir.is_absolute():
		output_dir = ROOT / output_dir
	config_path = Path(args.config_path)
	if not config_path.is_absolute():
		config_path = ROOT / config_path

	data = build_dataset(max(0, int(args.count)), str(args.seed), str(args.strategy))
	_write_json(output_dir / "Entities" / "generated_agents.json", data["entities"])
	_write_json(output_dir / "World.json", data["world"])
	_write_json(output_dir / "social_seed.json", data["social_seed"])
	_write_json(
		output_dir / "profiles.json",
		{"seed": str(args.seed), "count": int(args.count), "strategy": str(args.strategy), "profile_accounts": data["profile_accounts"], "profiles": data["profiles"]},
	)
	_write_json(output_dir / "Reactions.json", _reactions(int(args.max_agents_per_tick), int(args.max_decision_workers)))
	_write_json(
		output_dir / "scenario_meta.json",
		{
			"scenario": "su7_crisis",
			"strategy": str(args.strategy),
			"strategy_spec": STRATEGIES[str(args.strategy)],
			"event_classes": EVENT_CLASSES,
			"generated_files": ["World.json", "Entities/generated_agents.json", "social_seed.json", "profiles.json", "Reactions.json"],
		},
	)
	_write_json(config_path, _config(str(args.strategy), int(args.max_ticks)))
	print(f"wrote {int(args.count)} generated SU7 crisis agents to {output_dir}")
	print(f"wrote runtime config to {config_path}")


if __name__ == "__main__":
	main()
