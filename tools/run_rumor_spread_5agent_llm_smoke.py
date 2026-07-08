from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
	sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
	sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.runtime import KernRuntime


BASE_RUN_DIR = ROOT / "checkpoints" / "rumor_spread_5agent_llm_smoke"
RUN_DIR = BASE_RUN_DIR
GENERATED_DIR = RUN_DIR / "generated_data"
GENERATED_DATA_DIR = GENERATED_DIR / "Data" / "RumorSpread5Agent"


AGENTS: list[dict[str, Any]] = [
	{
		"entity_id": "agent_student_high_media",
		"phone_id": "phone_student_high_media",
		"account_id": "acc_student_high_media",
		"display_name": "Student High Media",
		"role": "student",
		"personality": "A flexible-time student who checks social media frequently and reacts quickly to campus health and safety discussions.",
		"knowledge": "You follow campus, local health, and social-platform discussions. You should make social media decisions from your phone context.",
		"interests": {"campus": 1.0, "health": 0.9, "rumor": 0.8, "local": 0.4},
		"behavior": {"base_activity_rate": 0.95, "active_hours": [], "event_reaction_sensitivity": 0.8, "expression_opportunity_rate": 0.6, "routine_browse_rate": 0.8},
	},
	{
		"entity_id": "agent_worker_low_media",
		"phone_id": "phone_worker_low_media",
		"account_id": "acc_worker_low_media",
		"display_name": "Worker Low Media",
		"role": "worker",
		"personality": "A busy worker who browses less often and is cautious about reposting unverified claims.",
		"knowledge": "You follow local notices and health updates when you have time. You prefer checking context before sharing uncertain claims.",
		"interests": {"local": 1.0, "health": 0.7, "clarification": 0.8, "rumor": 0.3},
		"behavior": {"base_activity_rate": 0.55, "active_hours": [], "event_reaction_sensitivity": 0.45, "expression_opportunity_rate": 0.25, "routine_browse_rate": 0.65},
	},
	{
		"entity_id": "agent_extrovert_commenter",
		"phone_id": "phone_extrovert_commenter",
		"account_id": "acc_extrovert_commenter",
		"display_name": "Extrovert Commenter",
		"role": "outgoing user",
		"personality": "An outgoing platform user who enjoys joining conversations but still decides actions from available evidence.",
		"knowledge": "You often comment on public discussions. Your identity affects how often you engage, while the actual action depends on context.",
		"interests": {"local": 0.8, "campus": 0.7, "health": 0.8, "rumor": 0.6},
		"behavior": {"base_activity_rate": 0.9, "active_hours": [], "event_reaction_sensitivity": 0.65, "expression_opportunity_rate": 0.85, "routine_browse_rate": 0.55},
	},
	{
		"entity_id": "agent_cautious_parent",
		"phone_id": "phone_cautious_parent",
		"account_id": "acc_cautious_parent",
		"display_name": "Cautious Parent",
		"role": "parent",
		"personality": "A cautious parent who worries about health and safety but dislikes spreading uncertain information.",
		"knowledge": "You care about school and health notices. You may seek official or reliable sources before reacting strongly.",
		"interests": {"health": 1.0, "campus": 0.9, "clarification": 0.9, "rumor": 0.5},
		"behavior": {"base_activity_rate": 0.75, "active_hours": [], "event_reaction_sensitivity": 0.75, "expression_opportunity_rate": 0.45, "routine_browse_rate": 0.7},
	},
	{
		"entity_id": "agent_quiet_observer",
		"phone_id": "phone_quiet_observer",
		"account_id": "acc_quiet_observer",
		"display_name": "Quiet Observer",
		"role": "quiet observer",
		"personality": "A quiet user who mostly reads posts and rarely comments unless the context is important.",
		"knowledge": "You use social media mainly to observe local information and official updates.",
		"interests": {"local": 0.7, "health": 0.7, "clarification": 0.8, "rumor": 0.2},
		"behavior": {"base_activity_rate": 0.45, "active_hours": [], "event_reaction_sensitivity": 0.35, "expression_opportunity_rate": 0.15, "routine_browse_rate": 0.85},
	},
]


def _write_json(path: Path, data: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configure_run_dir(run_name: str = "") -> None:
	global RUN_DIR, GENERATED_DIR, GENERATED_DATA_DIR
	name = str(run_name or "").strip()
	if name:
		safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name)
		RUN_DIR = ROOT / "checkpoints" / safe
	else:
		RUN_DIR = BASE_RUN_DIR
	GENERATED_DIR = RUN_DIR / "generated_data"
	GENERATED_DATA_DIR = GENERATED_DIR / "Data" / "RumorSpread5Agent"


def _copy_shared_data() -> None:
	if GENERATED_DIR.exists():
		shutil.rmtree(GENERATED_DIR, ignore_errors=True)
	GENERATED_DATA_DIR.mkdir(parents=True, exist_ok=True)
	shutil.copy2(ROOT / "Data" / "RumorSpread" / "Recipes.json", GENERATED_DATA_DIR / "Recipes.json")
	shutil.copy2(ROOT / "Data" / "RumorSpread" / "Reactions.json", GENERATED_DATA_DIR / "Reactions.json")
	shutil.copy2(ROOT / "Data" / "Bundles.json", GENERATED_DIR / "Data" / "Bundles.json")


def _build_entities() -> dict[str, Any]:
	out: dict[str, Any] = {}
	for spec in AGENTS:
		agent_template = f"Rumor5Agent_{spec['role'].replace(' ', '_')}"
		phone_template = f"Rumor5Phone_{spec['role'].replace(' ', '_')}"
		out[agent_template] = {
			"name": str(spec["display_name"]),
			"components": {
				"TagComponent": {"tags": ["character", "agent", "rumor_participant"]},
				"AgentSetting": {
					"agent_name": str(spec["display_name"]),
					"personality_summary": str(spec["personality"]),
					"common_knowledge_summary": str(spec["knowledge"]),
				},
				"AgentControlComponent": {"provider_id": "social_llm"},
				"MemoryComponent": {"short_term_queue": [], "short_term_max_entries": 12, "mid_term_prep_queue": [], "mid_term_prep_max_entries": 20, "mid_term_queue": [], "mid_term_max_entries": 10},
				"StatusComponent": {"statuses": [], "expire_at_tick": {}},
				"ContainerComponent": {"slots": {"inventory": {"capacity_volume": 5, "capacity_count": 4, "accepted_tags": []}}},
				"DecisionArbiterComponent": {"rules": []},
				"SocialBehaviorComponent": dict(spec["behavior"]),
			},
		}
		out[phone_template] = {
			"name": f"{spec['display_name']} Phone",
			"components": {
				"TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
				"DescriptionComponent": {
					"description": f"A phone logged into {spec['display_name']}'s social account.",
					"base_description": "A phone.",
					"observed_description": "A phone showing a social media app.",
				},
				"ScreenComponent": {
					"runtime_id": "social",
					"account_id": str(spec["account_id"]),
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
	return out


def _build_world() -> dict[str, Any]:
	location_entities: list[dict[str, str]] = []
	nested_entities: list[dict[str, str]] = []
	for spec in AGENTS:
		agent_template = f"Rumor5Agent_{spec['role'].replace(' ', '_')}"
		phone_template = f"Rumor5Phone_{spec['role'].replace(' ', '_')}"
		location_entities.append({"instance_id": str(spec["entity_id"]), "template_id": agent_template})
		nested_entities.append({"instance_id": str(spec["phone_id"]), "template_id": phone_template, "parent_container": str(spec["entity_id"])})
	return {
		"world_state": {"current_tick": 0},
		"locations": [
			{
				"location_id": "rumor_lab_room",
				"location_name": "Shared Study Room",
				"description": "A shared physical room used for a social-platform LLM smoke test.",
				"entities": location_entities,
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


def _build_social_seed() -> dict[str, Any]:
	accounts: list[dict[str, Any]] = []
	for spec in AGENTS:
		accounts.append({"account_id": str(spec["account_id"]), "display_name": str(spec["display_name"]), "interests": dict(spec["interests"])})
	background_accounts = [
		{"account_id": "acc_background", "display_name": "Campus Chatter", "interests": {"campus": 1.0, "local": 0.8}},
		{"account_id": "acc_food_updates", "display_name": "食堂小黑板", "interests": {"food": 1.0, "campus": 0.7}},
		{"account_id": "acc_local_transit", "display_name": "周边通勤提醒", "interests": {"local": 1.0, "traffic": 0.9}},
		{"account_id": "acc_club_events", "display_name": "活动日历", "interests": {"campus": 0.8, "events": 1.0}},
		{"account_id": "acc_health_life", "display_name": "健康生活角", "interests": {"health": 1.0, "local": 0.5}},
	]
	accounts.extend(
		[
			{"account_id": "acc_seed", "display_name": "本地生活观察", "interests": {"local": 1.0, "rumor": 1.0}},
			{"account_id": "acc_official", "display_name": "校务通知", "interests": {"clarification": 1.0, "health": 1.0, "campus": 1.0}},
			*background_accounts,
		]
	)
	follows: list[dict[str, Any]] = []
	for spec in AGENTS:
		for followee_id in ["acc_seed", "acc_official", *[str(x["account_id"]) for x in background_accounts]]:
			follows.append({"follower_id": str(spec["account_id"]), "followee_id": followee_id, "tick": 0})
	return {
		"accounts": accounts,
		"posts": [
			{
				"account_id": "acc_background",
				"post_id": "post_background_001",
				"text": "今天校园周边人流比较多，大家通勤注意时间。",
				"tags": ["background", "campus", "local"],
				"tick": 0,
			},
			{
				"account_id": "acc_food_updates",
				"post_id": "post_background_002",
				"text": "二楼窗口今天新增热汤，午饭高峰可能需要多排几分钟。",
				"tags": ["background", "food", "campus"],
				"tick": 0,
			},
			{
				"account_id": "acc_local_transit",
				"post_id": "post_background_003",
				"text": "东门外施工路段还在围挡，骑车经过最好提前绕一下。",
				"tags": ["background", "traffic", "local"],
				"tick": 0,
			},
			{
				"account_id": "acc_club_events",
				"post_id": "post_background_004",
				"text": "今晚自习室旁边有社团招新咨询，路过的同学可以看看。",
				"tags": ["background", "events", "campus"],
				"tick": 0,
			},
			{
				"account_id": "acc_health_life",
				"post_id": "post_background_005",
				"text": "天气转热，外出和运动后记得及时补水，别等口渴才喝。",
				"tags": ["background", "health", "local"],
				"tick": 0,
			},
			{
				"account_id": "acc_background",
				"post_id": "post_background_006",
				"text": "图书馆一层临时座位已经开放，上午人少一些。",
				"tags": ["background", "campus", "local"],
				"tick": 0,
			},
			{
				"account_id": "acc_food_updates",
				"post_id": "post_background_007",
				"text": "便利店冰柜补货了，但收银台排队比较长。",
				"tags": ["background", "food", "local"],
				"tick": 0,
			},
			{
				"account_id": "acc_club_events",
				"post_id": "post_background_008",
				"text": "周末志愿活动报名快截止了，想参加的人记得看通知。",
				"tags": ["background", "events", "campus"],
				"tick": 0,
			},
			{
				"account_id": "acc_local_transit",
				"post_id": "post_background_009",
				"text": "傍晚公交班次可能会比较挤，赶时间的话可以提前出门。",
				"tags": ["background", "traffic", "local"],
				"tick": 1,
			},
			{
				"account_id": "acc_seed",
				"post_id": "post_rumor_seed_001",
				"text": "有人说学校附近的饮水机不安全，很多人已经在转了，大家最好先别喝。",
				"tags": ["rumor", "health", "campus", "local"],
				"tick": 1,
			},
			{
				"account_id": "acc_official",
				"post_id": "post_clarification_001",
				"text": "关于饮水机安全的相关说法正在核实，请以官方检测公告为准，不要传播未经确认的信息。",
				"tags": ["clarification", "health", "campus", "local"],
				"tick": 3,
			},
		],
		"follows": follows,
	}


def _build_runtime_config(max_ticks: int, db_path: Path) -> dict[str, Any]:
	return {
		"env": {
			"USE_LLM": "1",
			"WORLD_JSON": "RumorSpread5Agent/World.json",
			"RECIPES_JSONS": "RumorSpread5Agent/Recipes.json",
			"REACTIONS_JSONS": "RumorSpread5Agent/Reactions.json",
			"BUNDLES_JSONS": "Bundles.json",
			"ENTITIES_DIRS": "RumorSpread5Agent/Entities",
			"LOG_LEVEL": "warn",
			"LOG_CATEGORIES": "system,executor,interaction,checkpoint,llm",
			"MAX_TICKS": str(int(max_ticks)),
			"CHECKPOINT_DIR": str(RUN_DIR),
			"CHECKPOINT_EVERY_TICK": "1",
			"CHECKPOINT_SNAPSHOT_INTERVAL_TICKS": "1",
			"WORKFLOW_CONTRACT_ON_ERROR": "degrade_to_noop",
			"WORKFLOW_VIEW_PROFILE": "social_platform",
			"EXTERNAL_RUNTIMES_JSON": json.dumps(
				{
					"social": {
						"type": "sqlite_social_platform",
						"db_path": str(db_path),
						"reset_db": True,
						"seed_json": "Data/RumorSpread5Agent/social_seed.json",
					}
				},
				ensure_ascii=False,
			),
		}
	}


def prepare_generated_scene(max_ticks: int) -> Path:
	_copy_shared_data()
	entities_dir = GENERATED_DATA_DIR / "Entities"
	_write_json(entities_dir / "rumor_5agent_entities.json", _build_entities())
	_write_json(GENERATED_DATA_DIR / "World.json", _build_world())
	_write_json(GENERATED_DATA_DIR / "social_seed.json", _build_social_seed())
	config_path = GENERATED_DIR / "runtime_config.rumor_spread.5agent.llm.local.json"
	_write_json(config_path, _build_runtime_config(max_ticks=max_ticks, db_path=RUN_DIR / "social.sqlite3"))
	return config_path


def _load_local_llm_env(config_path: str) -> dict[str, str]:
	raw = str(config_path or "").strip()
	paths: list[Path] = []
	if raw:
		p = Path(raw)
		paths.append(p if p.is_absolute() else ROOT / p)
	else:
		paths.extend(
			[
				ROOT / "runtime_config.deepseek.local.json",
				ROOT / "runtime_config.llm.local.json",
				GENERATED_DIR / "runtime_config.deepseek.local.json",
				GENERATED_DIR / "runtime_config.llm.local.json",
			]
		)
	for path in paths:
		if not path.exists():
			continue
		data = json.loads(path.read_text(encoding="utf-8"))
		env = data.get("env", data) if isinstance(data, dict) else {}
		if not isinstance(env, dict):
			continue
		return {str(k): str(v) for k, v in env.items() if k and v is not None}
	return {}


def _env_value(name: str, local_env: dict[str, str] | None = None) -> str:
	local = dict(local_env or {})
	if name in local:
		return str(local.get(name, "") or "").strip()
	return str(os.environ.get(name, "") or "").strip()


def _deepseek_overrides(model: str, local_env: dict[str, str] | None = None) -> dict[str, str]:
	api_key = _env_value("LLM_API_KEY", local_env) or _env_value("DEEPSEEK_API_KEY", local_env)
	if not api_key:
		raise RuntimeError("LLM_API_KEY or DEEPSEEK_API_KEY is not set in this process environment.")
	return {
		"USE_LLM": "1",
		"LLM_PROVIDER": "openai_compat",
		"LLM_BASE_URL": _env_value("LLM_BASE_URL", local_env) or "https://api.deepseek.com",
		"LLM_API_PREFIX": _env_value("LLM_API_PREFIX", local_env) or "/v1",
		"LLM_API_KEY": api_key,
		"LLM_PLANNER_MODEL": model or _env_value("LLM_PLANNER_MODEL", local_env) or "deepseek-v4-pro",
		"LLM_GROUNDER_MODEL": model or _env_value("LLM_GROUNDER_MODEL", local_env) or "deepseek-v4-pro",
		"LLM_TIMEOUT_SECONDS": _env_value("LLM_TIMEOUT_SECONDS", local_env) or "120",
		"LLM_MAX_RETRIES": _env_value("LLM_MAX_RETRIES", local_env) or "1",
		"LLM_REQUEST_EXTRA_JSON": _env_value("LLM_REQUEST_EXTRA_JSON", local_env) or json.dumps({"thinking": {"type": "disabled"}}, ensure_ascii=False),
	}


def _sqlite_summary(db_path: Path) -> dict[str, Any]:
	if not db_path.exists():
		return {"db_path": str(db_path), "exists": False}
	with sqlite3.connect(str(db_path)) as conn:
		conn.row_factory = sqlite3.Row
		tables = ["accounts", "posts", "exposures", "view_history", "comments", "reposts", "likes", "action_traces", "checkpoint_snapshots"]
		counts = {table: int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] or 0) for table in tables}
		ops = [
			dict(row)
			for row in conn.execute(
				"""
				SELECT operation, tick, COUNT(*) AS count
				FROM action_traces
				GROUP BY operation, tick
				ORDER BY tick, operation
				"""
			).fetchall()
		]
		rumor_exposures = [
			dict(row)
			for row in conn.execute(
				"""
				SELECT e.tick, COUNT(*) AS count
				FROM exposures e
				JOIN post_tags pt ON pt.post_id=e.post_id
				WHERE pt.tag='rumor'
				GROUP BY e.tick
				ORDER BY e.tick
				"""
			).fetchall()
		]
		clarification_exposures = [
			dict(row)
			for row in conn.execute(
				"""
				SELECT e.tick, COUNT(*) AS count
				FROM exposures e
				JOIN post_tags pt ON pt.post_id=e.post_id
				WHERE pt.tag='clarification'
				GROUP BY e.tick
				ORDER BY e.tick
				"""
			).fetchall()
		]
	return {
		"db_path": str(db_path),
		"exists": True,
		"counts": counts,
		"action_traces_by_tick": ops,
		"rumor_exposures_by_tick": rumor_exposures,
		"clarification_exposures_by_tick": clarification_exposures,
	}


def _account_names(db_path: Path) -> dict[str, str]:
	if not db_path.exists():
		return {}
	with sqlite3.connect(str(db_path)) as conn:
		conn.row_factory = sqlite3.Row
		return {str(row["account_id"]): str(row["display_name"]) for row in conn.execute("SELECT account_id, display_name FROM accounts").fetchall()}


def _post_summaries(db_path: Path) -> dict[str, dict[str, Any]]:
	if not db_path.exists():
		return {}
	with sqlite3.connect(str(db_path)) as conn:
		conn.row_factory = sqlite3.Row
		out: dict[str, dict[str, Any]] = {}
		for row in conn.execute("SELECT post_id, author_id, text, created_tick, like_count, comment_count, repost_count FROM posts").fetchall():
			out[str(row["post_id"])] = dict(row)
		return out


def _short_text(value: Any, limit: int = 90) -> str:
	text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
	if len(text) <= int(limit):
		return text
	return text[: max(0, int(limit) - 1)] + "..."


def _event_from_record(record: dict[str, Any]) -> dict[str, Any]:
	if isinstance(record.get("event", None), dict):
		return dict(record.get("event", {}) or {})
	return dict(record or {})


def _actor_label(actor_id: str) -> str:
	for spec in AGENTS:
		if str(spec.get("entity_id", "")) == str(actor_id):
			return f"{spec['display_name']} ({actor_id})"
	return str(actor_id or "<system>")


def _format_feed_items(items: list[Any], *, limit: int = 8) -> list[str]:
	lines: list[str] = []
	for idx, raw in enumerate(list(items or [])[: int(limit)]):
		if not isinstance(raw, dict):
			continue
		author = str(raw.get("author_display_name", "") or raw.get("author_id", "") or "").strip()
		summary = _short_text(raw.get("summary", raw.get("text", "")), 80)
		why = str(raw.get("why_visible", "") or "").strip()
		why_text = f" [{why}]" if why else ""
		lines.append(f"    slot {idx}: {author}: {summary}{why_text}")
	return lines


def _format_social_event(ev: dict[str, Any], *, account_names: dict[str, str], posts: dict[str, dict[str, Any]]) -> list[str]:
	etype = str(ev.get("type", "") or "")
	account_id = str(ev.get("account_id", "") or "")
	account = account_names.get(account_id, account_id)
	if etype == "SocialFeedObserved":
		lines = [f"  result: {account} refreshed feed ({len(list(ev.get('items', []) or []))} visible posts)"]
		lines.extend(_format_feed_items(list(ev.get("items", []) or [])))
		return lines
	if etype == "SocialPostObserved":
		post = dict(ev.get("post", {}) or {}) if isinstance(ev.get("post", {}), dict) else {}
		author = str(post.get("author_display_name", "") or post.get("author_id", "") or "").strip()
		text = _short_text(post.get("text", ""), 120)
		metrics = dict(post.get("metrics", {}) or {}) if isinstance(post.get("metrics", {}), dict) else {}
		return [
			f"  result: {account} opened post by {author}: {text}",
			f"    metrics: likes={metrics.get('likes', 0)}, comments={metrics.get('comments', 0)}, reposts={metrics.get('reposts', 0)}",
		]
	if etype == "SocialPostCreated":
		text = _short_text(ev.get("text", ""), 140)
		post_id = str(ev.get("post_id", "") or "")
		return [f"  result: {account} created post {post_id}: {text}"]
	if etype == "SocialPostInteracted":
		action = str(ev.get("action", "") or "")
		post_id = str(ev.get("post_id", "") or "")
		post = posts.get(post_id, {})
		target_author = account_names.get(str(post.get("author_id", "") or ""), str(post.get("author_id", "") or ""))
		target_text = _short_text(post.get("text", ""), 80)
		detail = dict(ev.get("detail", {}) or {}) if isinstance(ev.get("detail", {}), dict) else {}
		if action == "comment":
			return [f"  result: {account} commented on {target_author}'s post: {_short_text(detail.get('text', ''), 140)}"]
		if action == "repost":
			return [f"  result: {account} reposted {target_author}'s post ({target_text}) note={_short_text(detail.get('text', ''), 100)}"]
		if action in {"like", "unlike"}:
			return [f"  result: {account} {action}d {target_author}'s post: {target_text}"]
		return [f"  result: {account} interacted with {target_author}'s post: {action}"]
	if etype == "SocialActivityOpportunityGranted":
		return [
			f"  gate: granted {_actor_label(str(ev.get('entity_id', '') or ''))} "
			f"opportunity={ev.get('opportunity_type')} p={float(ev.get('probability', 0) or 0):.3f} roll={float(ev.get('roll', 0) or 0):.3f}"
		]
	if etype == "SocialActivityGateEvaluated":
		selected = [_actor_label(str(x)) for x in list(ev.get("selected_agent_ids", []) or [])]
		return [f"  gate summary: selected={len(selected)}/{int(ev.get('candidate_count', 0) or 0)} {selected}; skipped={dict(ev.get('skipped', {}) or {})}"]
	return []


def _format_interaction(item: dict[str, Any]) -> str:
	actor = _actor_label(str(item.get("actor_id", "") or ""))
	verb = str(item.get("verb", "") or "")
	if verb.startswith("Reaction"):
		return ""
	status = str(item.get("status", "") or "")
	params = item.get("parameters", {}) if isinstance(item.get("parameters", {}), dict) else {}
	text = str(params.get("text", "") or "").strip()
	text_part = f" text={_short_text(text, 120)}" if text else ""
	target = str(item.get("target_name", "") or item.get("target_id", "") or "")
	return f"  action: {actor} -> {verb} on {target} [{status}]{text_part}"


def _print_tick_stream(tick: int, interactions: list[dict[str, Any]], events: list[dict[str, Any]], db_path: Path) -> None:
	print(f"\n=== tick {tick} ===", flush=True)
	action_lines = [_format_interaction(item) for item in interactions]
	action_lines = [line for line in action_lines if line]
	if action_lines:
		for line in action_lines:
			print(line, flush=True)
	else:
		print("  action: no agent command executed", flush=True)
	account_names = _account_names(db_path)
	posts = _post_summaries(db_path)
	for record in events:
		ev = _event_from_record(record)
		for line in _format_social_event(ev, account_names=account_names, posts=posts):
			print(line, flush=True)


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
	counts: dict[str, int] = {}
	selected_by_tick: list[dict[str, Any]] = []
	for record in events:
		ev = dict(record.get("event", {}) or {}) if isinstance(record.get("event", {}), dict) else dict(record)
		etype = str(ev.get("type", "") or "")
		counts[etype] = counts.get(etype, 0) + 1
		if etype == "SocialActivityGateEvaluated":
			selected_by_tick.append(
				{
					"tick": int(ev.get("tick", 0) or 0),
					"candidate_count": int(ev.get("candidate_count", 0) or 0),
					"selected_count": int(ev.get("selected_count", 0) or 0),
					"selected_agent_ids": list(ev.get("selected_agent_ids", []) or []),
					"skipped": dict(ev.get("skipped", {}) or {}),
				}
			)
	return {"event_type_counts": counts, "gate_by_tick": selected_by_tick}


def _perception_summary(runtime: KernRuntime, actor_id: str) -> dict[str, Any]:
	view = build_full_ws_view(runtime.world_state, actor_id, "post_run_inspection", {"grounder": True})
	view["workflow_view_profile"] = dict(runtime.workflow_view_profile or {})
	perception = build_agent_perception(view, actor_id)
	return {
		"actor_id": actor_id,
		"visible_entity_count": len(list(perception.get("entities", []) or [])),
		"reachable_location_count": len(list(perception.get("reachable_locations", []) or [])),
		"inventory_ids": [str(x.get("id", "")) for x in list(perception.get("inventory", []) or []) if isinstance(x, dict)],
		"screen_context_count": len(list(perception.get("operable_screen_contexts", []) or [])),
	}


def _build_runtime(max_ticks: int, model: str, llm_config: str, run_name: str) -> tuple[KernRuntime, Path]:
	configure_run_dir(run_name)
	config_path = prepare_generated_scene(max_ticks)
	local_env = _load_local_llm_env(llm_config)
	overrides = _deepseek_overrides(model, local_env)
	runtime = KernRuntime.from_config(GENERATED_DIR, config_path.name, validate=True, configure_logging=True, overrides=overrides)
	runtime.action_providers["social_llm"] = runtime.action_provider
	return runtime, config_path


def run_smoke(max_ticks: int, model: str, llm_config: str = "", run_name: str = "", skip_run: bool = False, stream: bool = False) -> dict[str, Any]:
	configure_run_dir(run_name)
	if skip_run:
		config_path = prepare_generated_scene(max_ticks)
		return {"config_path": str(config_path), "generated_only": True}
	runtime, config_path = _build_runtime(max_ticks, model, llm_config, run_name)
	db_path = RUN_DIR / "social.sqlite3"
	if stream:
		runtime.is_running = True
		runtime.record_initial_state()
		events: list[dict[str, Any]] = []
		while runtime.is_running and runtime.world_state.game_time.total_ticks < int(max_ticks):
			start_interaction_seq = int(getattr(runtime.world_state, "_interaction_seq", 0) or 0)
			start_event_seq = int(getattr(runtime.world_state, "_event_seq", 0) or 0)
			started = time.monotonic()
			tick_events = runtime.step_and_record()
			elapsed = time.monotonic() - started
			events.extend(tick_events)
			new_interactions = [
				dict(x)
				for x in list(getattr(runtime.world_state, "interaction_log", []) or [])
				if int(x.get("seq", 0) or 0) > start_interaction_seq
			]
			new_events = [
				dict(x)
				for x in list(getattr(runtime.world_state, "event_log", []) or [])
				if int(x.get("seq", 0) or 0) > start_event_seq
			]
			_print_tick_stream(int(runtime.world_state.game_time.total_ticks), new_interactions, new_events, db_path)
			print(f"  tick elapsed: {elapsed:.1f}s", flush=True)
	else:
		events = runtime.run_configured()
	return {
		"config_path": str(config_path),
		"run_dir": str(RUN_DIR),
		"ticks": int(runtime.world_state.game_time.total_ticks),
		"llm_provider_registered": "social_llm" in runtime.action_providers,
		"perception_check": _perception_summary(runtime, "agent_student_high_media"),
		"events": _event_summary(events),
		"sqlite": _sqlite_summary(db_path),
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Run a five-agent RumorSpread LLM smoke test with a DeepSeek-compatible API.")
	parser.add_argument("--max-ticks", type=int, default=5, help="Number of runtime ticks to run.")
	parser.add_argument("--model", default="deepseek-v4-pro", help="Planner and grounder model name.")
	parser.add_argument("--llm-config", default="", help="Optional gitignored runtime_config*.local*.json file containing LLM env values.")
	parser.add_argument("--run-name", default="", help="Optional checkpoint/sqlite directory name under checkpoints/.")
	parser.add_argument("--skip-run", action="store_true", help="Only generate the temporary scene/config.")
	parser.add_argument("--stream", action="store_true", help="Print each tick's selected agents, commands, and social results as the run progresses.")
	parser.add_argument("--quiet-summary", action="store_true", help="Do not print the final JSON summary.")
	args = parser.parse_args()

	try:
		report = run_smoke(
			max_ticks=max(1, int(args.max_ticks or 1)),
			model=str(args.model or "deepseek-v4-pro"),
			llm_config=str(args.llm_config or ""),
			run_name=str(args.run_name or ""),
			skip_run=bool(args.skip_run),
			stream=bool(args.stream),
		)
	except RuntimeError as exc:
		print(json.dumps({"ok": False, "error": str(exc), "hint": "Set LLM_API_KEY or DEEPSEEK_API_KEY in this shell, then rerun."}, ensure_ascii=False, indent=2))
		raise SystemExit(2)
	if not bool(args.quiet_summary):
		print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
