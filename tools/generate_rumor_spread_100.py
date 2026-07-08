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


DEFAULT_OUTPUT_DIR = ROOT / "Data" / "RumorSpread" / "generated_100"
DEFAULT_CONFIG_PATH = ROOT / "runtime_config.rumor_spread.100agent.smoke.json"

BACKGROUND_AUTHORS = [
	("acc_background", "Campus Chatter", {"campus": 1.0, "local": 0.8}),
	("acc_food_updates", "食堂小黑板", {"food": 1.0, "campus": 0.7}),
	("acc_local_transit", "周边通勤提醒", {"local": 1.0, "traffic": 0.9}),
	("acc_club_events", "活动日历", {"campus": 0.8, "events": 1.0}),
	("acc_health_life", "健康生活角", {"health": 1.0, "local": 0.5}),
	("acc_library_notice", "图书馆小广播", {"campus": 0.9, "notice": 0.7}),
	("acc_dorm_life", "宿舍生活圈", {"campus": 0.7, "local": 0.7}),
	("acc_city_services", "城市服务提醒", {"local": 0.9, "traffic": 0.5, "notice": 0.6}),
]

BACKGROUND_TEXTS = [
	("今天校园周边人流比较多，大家通勤注意时间。", ["background", "campus", "local"]),
	("二楼窗口今天新增热汤，午饭高峰可能需要多排几分钟。", ["background", "food", "campus"]),
	("东门外施工路段还在围挡，骑车经过最好提前绕一下。", ["background", "traffic", "local"]),
	("今晚自习室旁边有社团招新咨询，路过的同学可以看看。", ["background", "events", "campus"]),
	("天气转热，外出和运动后记得及时补水，别等口渴才喝。", ["background", "health", "local"]),
	("图书馆一层临时座位已经开放，上午人少一些。", ["background", "campus", "local"]),
	("便利店冰柜补货了，但收银台排队比较长。", ["background", "food", "local"]),
	("周末志愿活动报名快截止了，想参加的人记得看通知。", ["background", "events", "campus"]),
	("傍晚公交班次可能会比较挤，赶时间的话可以提前出门。", ["background", "traffic", "local"]),
	("早上自习室空调温度有点低，久坐的人可以带件薄外套。", ["background", "campus", "local"]),
	("校医院提醒最近肠胃不适咨询变多，饮食和饮水都注意卫生。", ["background", "health", "campus"]),
	("食堂今晚部分窗口提前半小时收档，别太晚过去。", ["background", "food", "campus"]),
	("社团活动报名表今晚会再开放一次，之前错过的人可以补填。", ["background", "events", "campus"]),
	("西门外共享单车数量比平时少，下午可能需要多走几分钟。", ["background", "traffic", "local"]),
	("今天楼下公告栏换了新通知，路过可以顺手看一眼。", ["background", "campus", "notice"]),
	("最近天气闷热，运动前后最好分次补水，不要一次喝太急。", ["background", "health", "local"]),
	("便利店今天补了常温瓶装水，靠近门口的货架还有不少。", ["background", "food", "campus", "health"]),
	("今晚活动日历更新了两个讲座，一个关于公共安全，一个关于校园生活。", ["background", "events", "campus", "local"]),
	("宿舍区晚间维修会有短暂停水通知，具体楼栋看公告栏。", ["background", "campus", "notice"]),
	("体育馆下午有校队训练，普通预约名额会少一点。", ["background", "events", "campus"]),
	("南门外小吃街今天检查燃气设备，部分店铺开门晚。", ["background", "food", "local"]),
	("周边公交站牌更新了临时路线图，别按旧图等车。", ["background", "traffic", "local"]),
	("图书馆借阅系统上午维护过，现在已经恢复。", ["background", "campus", "notice"]),
	("今天空气湿度高，长时间户外活动注意休息。", ["background", "health", "local"]),
	("学生服务中心排队人数偏多，能线上办的事项建议线上处理。", ["background", "campus", "notice"]),
	("晚间自习室预约取消的人不少，想补位可以多刷一下。", ["background", "campus", "local"]),
	("附近超市瓶装水在做促销，但热门规格卖得比较快。", ["background", "food", "local", "health"]),
	("社区门口临停车辆较多，骑车和步行都注意避让。", ["background", "traffic", "local"]),
]

RUMOR_POSTS = [
	("post_rumor_seed_001", "有人说学校附近的饮水机不安全，很多人已经在转了，大家最好先别喝。", 1),
	("post_rumor_seed_002", "刚看到群里有人提醒，宿舍楼饮水机可能有问题，虽然还没确认但先囤点水比较稳。", 2),
	("post_rumor_seed_003", "听说校医院今天问饮水问题的人突然变多，不知道是不是和饮水机传闻有关。", 4),
]

CLARIFICATION_POSTS = [
	("post_clarification_001", "关于饮水机安全的相关说法正在核实，请以官方检测公告为准，不要传播未经确认的信息。", 3),
	("post_clarification_002", "后勤部门已安排抽检，暂未发现异常。请大家不要把未核实截图当作事实扩散。", 6),
	("post_clarification_003", "检测结果会统一发布；如果发现设备异常，请通过服务平台提交具体位置和照片。", 9),
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
		"local": rng.uniform(0.35, 1.0),
		"health": rng.uniform(0.25, 1.0),
		"campus": rng.uniform(0.25, 1.0),
		"rumor": rng.uniform(0.15, 0.9),
		"clarification": rng.uniform(0.15, 0.9),
	}
	media_style = str(sample.get("media_style", "") or "")
	platform = str(sample.get("platform_archetype", "") or "")
	if media_style in {"news_commentary", "longform_reader"}:
		weights["clarification"] += 0.25
		weights["notice"] = 0.7
	if media_style in {"short_video_scroller", "visual_lifestyle"}:
		weights["rumor"] += 0.2
	if platform in {"public_discussion", "interest_community"}:
		weights["campus"] += 0.2
	if platform == "private_social":
		weights["local"] += 0.2
	for item in list(sample.get("practical_interests", []) or []) + list(sample.get("aspirational_interests", []) or []):
		if not isinstance(item, dict):
			continue
		iid = str(item.get("id", "") or "")
		if iid in {"home_cooking"}:
			weights["food"] = max(weights.get("food", 0.0), 0.65)
		if iid in {"casual_fitness", "walking_hiking"}:
			weights["health"] += 0.15
		if iid in {"volunteering"}:
			weights["events"] = max(weights.get("events", 0.0), 0.7)
	return {k: round(min(1.0, max(0.05, float(v))), 2) for k, v in weights.items()}


def _activity_model(profile: dict[str, Any], rng: random.Random) -> dict[str, Any]:
	sample = dict(profile.get("sample", {}) or {})
	platform = str(sample.get("platform_archetype", "") or "")
	media = str(sample.get("media_style", "") or "")
	social = str(sample.get("social_style", "") or "")
	base = {
		"short_video_mass": 0.72,
		"public_discussion": 0.68,
		"private_social": 0.56,
		"lifestyle_discovery": 0.58,
		"interest_community": 0.52,
	}.get(platform, 0.55)
	if media == "quiet_low_media":
		base -= 0.22
	if media in {"news_commentary", "short_video_scroller"}:
		base += 0.12
	if social == "outgoing_connector":
		base += 0.12
	if social == "reserved_close_circle":
		base -= 0.08
	base += rng.uniform(-0.12, 0.12)
	expression = 0.25 + rng.uniform(0.0, 0.35)
	if social == "outgoing_connector":
		expression += 0.25
	if media == "quiet_low_media":
		expression -= 0.15
	routine = 0.65 + rng.uniform(-0.2, 0.2)
	if media == "quiet_low_media":
		routine += 0.15
	return {
		"base_activity_rate": round(min(0.95, max(0.08, base)), 2),
		"active_hours": [],
		"event_reaction_sensitivity": round(rng.uniform(0.25, 0.9), 2),
		"expression_opportunity_rate": round(min(0.95, max(0.05, expression)), 2),
		"routine_browse_rate": round(min(0.95, max(0.1, routine)), 2),
	}


def _agent_template() -> dict[str, Any]:
	return {
		"name": "Generated Rumor Agent",
		"components": {
			"TagComponent": {"tags": ["character", "agent", "rumor_participant"]},
			"AgentSetting": {
				"agent_name": "Generated Rumor Agent",
				"personality_summary": "A generated social-platform participant.",
				"common_knowledge_summary": "You follow local, health, and social-platform discussions. Make social media decisions only from your carried phone context.",
			},
			"AgentControlComponent": {},
			"MemoryComponent": {
				"short_term_queue": [],
				"short_term_max_entries": 12,
				"mid_term_prep_queue": [],
				"mid_term_prep_max_entries": 20,
				"mid_term_queue": [],
				"mid_term_max_entries": 10,
			},
			"StatusComponent": {"statuses": [], "expire_at_tick": {}},
			"ContainerComponent": {"slots": {"inventory": {"capacity_volume": 5, "capacity_count": 4, "accepted_tags": []}}},
			"DecisionArbiterComponent": {"rules": []},
			"SocialBehaviorComponent": {
				"base_activity_rate": 0.5,
				"active_hours": [],
				"event_reaction_sensitivity": 0.5,
				"expression_opportunity_rate": 0.3,
				"routine_browse_rate": 0.75,
			},
		},
	}


def _phone_template() -> dict[str, Any]:
	return {
		"name": "Generated Rumor Phone",
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


def build_dataset(count: int, seed: str) -> dict[str, Any]:
	rng = random.Random(seed)
	profiles = generate_social_profiles(count=count, seed=seed, include_debug=False)
	entities = {
		"RumorGeneratedAgent": _agent_template(),
		"RumorGeneratedPhone": _phone_template(),
	}
	world_entities = []
	nested_entities = []
	accounts = []
	follows = []
	for idx, profile in enumerate(profiles, start=1):
		slug = _slug(idx)
		agent_id = f"agent_rumor_{slug}"
		phone_id = f"phone_rumor_{slug}"
		account_id = f"acc_rumor_{slug}"
		name = _display_name(profile, idx)
		background = str(profile.get("llm_background_prompt", "") or profile.get("summary_line", "") or "")
		personality = str(profile.get("summary_line", "") or name)
		common = (
			"你正在参与一个本地校园饮水机传闻的社交平台环境。"
			"你只应依据手机屏幕、近期记忆和自己的背景做出浏览、打开、评论、转发、点赞或发帖决定。"
			"不要凭空引用看不到的帖子 ID。"
		)
		world_entities.append(
			{
				"instance_id": agent_id,
				"template_id": "RumorGeneratedAgent",
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
				"template_id": "RumorGeneratedPhone",
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

	static_accounts = [
		{"account_id": "acc_seed", "display_name": "本地生活观察", "interests": {"local": 1.0, "rumor": 1.0}},
		{"account_id": "acc_official", "display_name": "校务通知", "interests": {"clarification": 1.0, "health": 1.0, "campus": 1.0}},
	]
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
		posts.append({"account_id": author_id, "post_id": f"post_background_{idx:03d}", "text": text, "tags": tags, "tick": 0 if idx <= 24 else 1})
	for post_id, text, tick in RUMOR_POSTS:
		posts.append({"account_id": "acc_seed", "post_id": post_id, "text": text, "tags": ["rumor", "health", "campus", "local"], "tick": tick})
	for post_id, text, tick in CLARIFICATION_POSTS:
		posts.append({"account_id": "acc_official", "post_id": post_id, "text": text, "tags": ["clarification", "health", "campus", "local"], "tick": tick})

	world = {
		"world_state": {"current_tick": 0},
		"locations": [
			{
				"location_id": "rumor_lab_room",
				"location_name": "Shared Study Room",
				"description": "A shared virtual room used for 100-agent social-platform rumor-spread experiments.",
				"entities": world_entities,
			}
		],
		"paths": [],
		"entities": nested_entities,
		"environment_scopes": [
			{
				"scope_id": "rumor_lab_env",
				"scope_type": "region",
				"location_ids": ["rumor_lab_room"],
				"priority": 0,
				"fields": {"light_level": 2},
				"conditions": [],
			}
		],
	}
	social_seed = {"accounts": [*accounts, *static_accounts], "posts": posts, "follows": follows}
	return {"profiles": profiles, "entities": entities, "world": world, "social_seed": social_seed}


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate a 100-agent RumorSpread KERN dataset from social profile samples.")
	parser.add_argument("--count", type=int, default=100, help="Number of generated social agents.")
	parser.add_argument("--seed", default="kern-rumor-spread-100-v1", help="Deterministic generation seed.")
	parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory under Data/RumorSpread by default.")
	parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH), help="Runtime config path to write.")
	parser.add_argument("--max-ticks", type=int, default=20, help="MAX_TICKS for the generated runtime config.")
	parser.add_argument("--max-agents-per-tick", type=int, default=100, help="SocialActivityGateTick max_agents_per_tick override for generated reaction.")
	parser.add_argument("--max-decision-workers", type=int, default=30, help="Parallel LLM decision workers for the generated config.")
	args = parser.parse_args()

	output_dir = Path(args.output_dir)
	if not output_dir.is_absolute():
		output_dir = ROOT / output_dir
	config_path = Path(args.config_path)
	if not config_path.is_absolute():
		config_path = ROOT / config_path

	data = build_dataset(max(0, int(args.count)), str(args.seed))
	_write_json(output_dir / "Entities" / "generated_agents.json", data["entities"])
	_write_json(output_dir / "World.json", data["world"])
	_write_json(output_dir / "social_seed.json", data["social_seed"])
	_write_json(output_dir / "profiles.json", {"seed": str(args.seed), "count": int(args.count), "profiles": data["profiles"]})

	reactions = {
		"rules": [
			{
				"id": "rumor_world_tick_social_activity_gate",
				"on_event": "WorldTickAdvanced",
				"bundle": {
					"effects": [
						{
							"effect": "SocialActivityGateTick",
							"max_agents_per_tick": int(args.max_agents_per_tick),
							"max_actions_per_agent": 1,
							"default_screen_context_window_ticks": 2,
							"decision_mode": "parallel_decide_serial_commit",
							"max_decision_workers": int(args.max_decision_workers),
						}
					]
				},
			},
			{
				"id": "rumor_world_tick_environment_condition",
				"on_event": "WorldTickAdvanced",
				"bundle": {"effects": [{"effect": "EnvironmentConditionTick"}]},
			},
			{
				"id": "rumor_advance_tick_status",
				"on_event": "AdvanceTick",
				"condition": {"type": "has_component", "target": "event_entity", "component": "StatusComponent"},
				"bundle": {"effects": [{"effect": "StatusTick"}]},
			},
		]
	}
	_write_json(output_dir / "Reactions.json", reactions)

	config = {
		"env": {
			"USE_LLM": "1",
			"WORLD_JSON": "RumorSpread/generated_100/World.json",
			"RECIPES_JSONS": "RumorSpread/Recipes.json",
			"REACTIONS_JSONS": "RumorSpread/generated_100/Reactions.json",
			"BUNDLES_JSONS": "Bundles.json",
			"ENTITIES_DIRS": "RumorSpread/generated_100/Entities",
			"LOG_LEVEL": "warn",
			"LOG_CATEGORIES": "system,executor,interaction,checkpoint,llm",
			"MAX_TICKS": str(int(args.max_ticks)),
			"CHECKPOINT_DIR": "checkpoints/rumor_spread_100agent_smoke",
			"CHECKPOINT_EVERY_TICK": "1",
			"CHECKPOINT_SNAPSHOT_INTERVAL_TICKS": "5",
			"WORKFLOW_CONTRACT_ON_ERROR": "degrade_to_noop",
			"WORKFLOW_VIEW_PROFILE": "social_platform",
			"EXTERNAL_RUNTIMES_JSON": json.dumps(
				{
					"social": {
						"type": "sqlite_social_platform",
						"db_path": "checkpoints/rumor_spread_100agent_smoke/social.sqlite3",
						"reset_db": True,
						"seed_json": "Data/RumorSpread/generated_100/social_seed.json",
					}
				},
				ensure_ascii=False,
				separators=(",", ":"),
			),
		}
	}
	_write_json(config_path, config)
	print(f"wrote {int(args.count)} generated agents to {output_dir}")
	print(f"wrote runtime config to {config_path}")


if __name__ == "__main__":
	main()
