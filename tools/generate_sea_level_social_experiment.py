from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import tempfile
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
STUDY_SCHEMA = "sea_level_social_study.v1"
PROFILE_SCHEMA = "social_profile.v4"
SCHEDULE_SCHEMA = "social_activation_schedule.v1"
MANIFEST_SCHEMA = "sea_level_social_generation.v1"
BIG_FIVE_FIELDS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
BACKGROUND_POST_COUNT = 200

SCIENCE_EXPANSION = {
	"climate_risk": ("climate_risk", "sea_level", "extreme_weather"),
	"environment": ("environment", "ecology", "climate_risk"),
	"public_health": ("public_health", "health_risk"),
	"technology_society": ("technology", "technology_society"),
}
PRACTICAL_MAPPING = {
	"home_cooking": "cooking",
	"walking_hiking": "fitness",
	"casual_fitness": "fitness",
	"gaming": "gaming",
	"crafts": "crafts",
	"community_events": "community",
	"reading": "reading",
	"photography": "photography",
	"gardening": "gardening",
	"parent_child": "parenting",
}
ASPIRATIONAL_MAPPING = {
	"travel_watching": "travel",
	"premium_tech_watching": "premium_tech",
	"home_design_watching": "home_design",
	"career_learning": "career_learning",
	"financial_learning": "financial_learning",
	"culture_art": "culture_art",
}


def _load_json(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(value, dict):
		raise ValueError(f"JSON root must be an object: {path}")
	return value


def _write_json(path: Path, value: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
		json.dump(value, handle, ensure_ascii=False, indent=2)
		handle.write("\n")
		temporary = Path(handle.name)
	temporary.replace(path)


def _sha256(value: Any) -> str:
	raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def _rng(seed: str, *parts: str) -> random.Random:
	digest = hashlib.sha256("\x1f".join((seed, *parts)).encode("utf-8")).digest()
	return random.Random(int.from_bytes(digest[:16], "big"))


def _exact(raw: Any, expected: set[str], label: str) -> dict[str, Any]:
	if not isinstance(raw, dict) or set(raw) != expected:
		raise ValueError(f"{label} must contain exactly {sorted(expected)}")
	return raw


def _positive_int(value: Any, label: str) -> int:
	if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
		raise ValueError(f"{label} must be a positive integer")
	return value


def load_study_config(path: Path) -> dict[str, Any]:
	config = _load_json(path)
	_exact(
		config,
		{"schema_version", "study_id", "study_seed", "population", "simulation", "platform", "network", "activation", "interest_mapping", "conditions"},
		"study config",
	)
	if config["schema_version"] != STUDY_SCHEMA:
		raise ValueError(f"study config schema_version must be {STUDY_SCHEMA}")
	for field in ("study_id", "study_seed"):
		if not isinstance(config[field], str) or not config[field].strip() or config[field] != config[field].strip():
			raise ValueError(f"study config {field} must be a non-blank trimmed string")
	population = _exact(config["population"], {"count", "profiles_path", "backgrounds_path"}, "population")
	if _positive_int(population["count"], "population.count") != 300:
		raise ValueError("sea-level study population.count must be 300")
	_exact(config["simulation"], {"tick_count", "feed_limit", "max_actions_per_turn", "max_replans_per_turn"}, "simulation")
	_positive_int(config["simulation"]["tick_count"], "simulation.tick_count")
	if config["simulation"]["feed_limit"] != 8:
		raise ValueError("simulation.feed_limit must be 8 for the current social feed runtime")
	_exact(config["platform"], {"runtime_id", "institution_account_id", "institution_display_name", "background_posts_path"}, "platform")
	network = _exact(
		config["network"],
		{"min_out_degree", "max_out_degree", "target_mean_out_degree", "out_degree_stddev", "extraversion_adjustment", "institution_initial_followers", "popularity_sigma", "interest_similarity_boost", "lifecycle_similarity_boost", "triangle_closure_boost"},
		"network",
	)
	if not (1 <= int(network["min_out_degree"]) <= int(network["target_mean_out_degree"]) <= int(network["max_out_degree"])):
		raise ValueError("network out-degree bounds are invalid")
	activation = _exact(config["activation"], {"gap_intercept", "individual_intercept_stddev", "gap_noise_stddev", "max_active_per_tick", "coefficients"}, "activation")
	coefficients = _exact(activation["coefficients"], set(BIG_FIVE_FIELDS), "activation.coefficients")
	for key, value in {**network, **{key: value for key, value in activation.items() if key != "coefficients"}, **coefficients}.items():
		if key not in {"min_out_degree", "max_out_degree", "target_mean_out_degree", "institution_initial_followers", "max_active_per_tick"} and (isinstance(value, bool) or not isinstance(value, (int, float))):
			raise ValueError(f"numeric study setting is invalid: {key}")
	interest_mapping = _exact(config["interest_mapping"], {"version", "weights"}, "interest_mapping")
	if interest_mapping["version"] != "social_interest_mapping.v1":
		raise ValueError("interest_mapping.version must be social_interest_mapping.v1")
	_exact(interest_mapping["weights"], {"science_topics", "practical", "aspirational", "general_knowledge"}, "interest_mapping.weights")
	conditions = config["conditions"]
	if not isinstance(conditions, list) or len(conditions) != 2:
		raise ValueError("study config must define exactly two conditions")
	condition_ids = []
	for index, condition in enumerate(conditions):
		_exact(condition, {"condition_id", "post_id", "text", "ranking_topics", "display_hashtags"}, f"conditions[{index}]")
		condition_ids.append(condition["condition_id"])
		for field in ("ranking_topics", "display_hashtags"):
			if not isinstance(condition[field], list) or not condition[field] or len(set(condition[field])) != len(condition[field]):
				raise ValueError(f"conditions[{index}].{field} must be a non-empty unique array")
	if set(condition_ids) != {"sea_level_consequence_focus", "sea_level_solution_focus"}:
		raise ValueError("study conditions must be the frozen consequence and solution pair")
	if conditions[0]["ranking_topics"] != conditions[1]["ranking_topics"]:
		raise ValueError("paired experimental posts must use identical ranking_topics")
	if conditions[0]["post_id"] != conditions[1]["post_id"]:
		raise ValueError("paired experimental posts must use the same stable post_id")
	return config


def load_population(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str], Path, Path]:
	profile_path = (ROOT / config["population"]["profiles_path"]).resolve()
	background_path = (ROOT / config["population"]["backgrounds_path"]).resolve()
	population = _load_json(profile_path)
	if population.get("schema_version") != PROFILE_SCHEMA:
		raise ValueError(f"population input must use {PROFILE_SCHEMA}")
	profiles = population.get("profiles")
	if not isinstance(profiles, list) or len(profiles) != int(config["population"]["count"]):
		raise ValueError("population input count does not match study config")
	by_id: dict[str, dict[str, Any]] = {}
	for profile in profiles:
		if not isinstance(profile, dict):
			raise ValueError("population profile must be an object")
		profile_id = str(profile.get("profile_id", ""))
		if not profile_id or profile_id in by_id:
			raise ValueError("population profile_id must be unique and non-blank")
		personality = profile.get("personality")
		if not isinstance(personality, dict) or set(personality) != set(BIG_FIVE_FIELDS):
			raise ValueError(f"profile {profile_id} must contain exactly five personality dimensions")
		if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1 for value in personality.values()):
			raise ValueError(f"profile {profile_id} has an invalid personality value")
		by_id[profile_id] = profile
	backgrounds: dict[str, str] = {}
	for line_number, line in enumerate(background_path.read_text(encoding="utf-8").splitlines(), start=1):
		if not line.strip():
			continue
		row = json.loads(line)
		if not isinstance(row, dict) or row.get("status") != "ok" or not isinstance(row.get("generated"), dict):
			raise ValueError(f"background row {line_number} is not a successful generation")
		profile_id = str(row.get("profile_id", ""))
		generated = row["generated"]
		if generated.get("profile_id") != profile_id:
			raise ValueError(f"background row {line_number} changed profile_id")
		text = generated.get("natural_language_background")
		if not isinstance(text, str) or not text.strip() or "我" not in text:
			raise ValueError(f"background row {line_number} must contain a first-person background")
		if profile_id in backgrounds:
			raise ValueError(f"duplicate background profile_id: {profile_id}")
		backgrounds[profile_id] = text.strip()
	if set(backgrounds) != set(by_id):
		raise ValueError("background profile IDs do not exactly match population profile IDs")
	return [by_id[key] for key in sorted(by_id)], backgrounds, profile_path, background_path


def _interest_ids(profile: dict[str, Any], category: str) -> list[str]:
	raw = (profile.get("interests") or {}).get(category)
	if not isinstance(raw, list):
		raise ValueError(f"profile {profile['profile_id']} interests.{category} must be an array")
	ids: list[str] = []
	for item in raw:
		if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
			raise ValueError(f"profile {profile['profile_id']} has invalid interests.{category}")
		ids.append(item["id"])
	return ids


def project_interests(profile: dict[str, Any], weights: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
	projected: dict[str, float] = {"general_knowledge": float(weights["general_knowledge"])}
	sources: dict[str, list[str]] = {"general_knowledge": ["universal_baseline"]}

	def assign(topic: str, weight: float, source: str) -> None:
		if topic not in projected or weight > projected[topic]:
			projected[topic] = weight
		sources.setdefault(topic, []).append(source)

	for source_id in _interest_ids(profile, "science_topics"):
		for topic in SCIENCE_EXPANSION.get(source_id, (source_id,)):
			assign(topic, float(weights["science_topics"]), f"interests.science_topics:{source_id}")
	for source_id in _interest_ids(profile, "practical"):
		if source_id not in PRACTICAL_MAPPING:
			raise ValueError(f"unsupported practical interest: {source_id}")
		assign(PRACTICAL_MAPPING[source_id], float(weights["practical"]), f"interests.practical:{source_id}")
	for source_id in _interest_ids(profile, "aspirational"):
		if source_id not in ASPIRATIONAL_MAPPING:
			raise ValueError(f"unsupported aspirational interest: {source_id}")
		assign(ASPIRATIONAL_MAPPING[source_id], float(weights["aspirational"]), f"interests.aspirational:{source_id}")
	provenance = [
		{"topic": topic, "weight": projected[topic], "sources": sorted(set(sources[topic])), "mapping_version": "social_interest_mapping.v1"}
		for topic in sorted(projected)
	]
	return {topic: projected[topic] for topic in sorted(projected)}, provenance


def _weighted_sample(rng: random.Random, candidates: list[str], count: int, score: Callable[[str], float]) -> list[str]:
	remaining = list(candidates)
	selected: list[str] = []
	for _ in range(min(count, len(remaining))):
		weights = [max(0.000001, float(score(candidate))) for candidate in remaining]
		threshold = rng.random() * sum(weights)
		cumulative = 0.0
		chosen_index = len(remaining) - 1
		for index, weight in enumerate(weights):
			cumulative += weight
			if threshold <= cumulative:
				chosen_index = index
				break
		selected.append(remaining.pop(chosen_index))
	return selected


def generate_network(profiles: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	seed = config["study_seed"]
	network = config["network"]
	accounts = [f"account_{index:03d}" for index in range(1, len(profiles) + 1)]
	profile_by_account = dict(zip(accounts, profiles))
	interests = {
		account: set().union(*(_interest_ids(profile, category) for category in ("science_topics", "practical", "aspirational")))
		for account, profile in profile_by_account.items()
	}
	lifecycle = {account: str((profile.get("demographics") or {}).get("lifecycle_stage", "")) for account, profile in profile_by_account.items()}
	popularity = {account: _rng(seed, "popularity", account).lognormvariate(0.0, float(network["popularity_sigma"])) for account in accounts}
	target_degrees: dict[str, int] = {}
	for account, profile in profile_by_account.items():
		personality = profile["personality"]
		draw = _rng(seed, "out_degree", account).gauss(float(network["target_mean_out_degree"]), float(network["out_degree_stddev"]))
		draw += float(network["extraversion_adjustment"]) * (float(personality["extraversion"]) - 0.5)
		target_degrees[account] = max(int(network["min_out_degree"]), min(int(network["max_out_degree"]), round(draw)))

	def base_score(source: str, target: str) -> float:
		union = interests[source] | interests[target]
		similarity = len(interests[source] & interests[target]) / len(union) if union else 0.0
		life_match = 1.0 if lifecycle[source] == lifecycle[target] else 0.0
		return popularity[target] * (1.0 + float(network["interest_similarity_boost"]) * similarity) * (1.0 + float(network["lifecycle_similarity_boost"]) * life_match)

	base_adjacency: dict[str, set[str]] = {}
	for source in accounts:
		candidates = [target for target in accounts if target != source]
		base_adjacency[source] = set(_weighted_sample(_rng(seed, "base_network", source), candidates, target_degrees[source], lambda target: base_score(source, target)))
	institution_followers = set(_weighted_sample(_rng(seed, "institution_followers"), accounts, int(network["institution_initial_followers"]), lambda target: 1.0))
	final_adjacency: dict[str, set[str]] = {}
	for source in accounts:
		ordinary_count = target_degrees[source] - (1 if source in institution_followers else 0)
		candidates = [target for target in accounts if target != source]

		def closure_score(target: str) -> float:
			mutual_neighbors = sum(1 for neighbor in base_adjacency[source] if target in base_adjacency.get(neighbor, set()) or neighbor in base_adjacency.get(target, set()))
			return base_score(source, target) * (1.0 + float(network["triangle_closure_boost"]) * mutual_neighbors)

		selected = set(_weighted_sample(_rng(seed, "final_network", source), candidates, ordinary_count, closure_score))
		if source in institution_followers:
			selected.add(config["platform"]["institution_account_id"])
		final_adjacency[source] = selected
	follows = [
		{"follower_id": source, "followee_id": target, "tick": 0}
		for source in accounts
		for target in sorted(final_adjacency[source])
	]
	_validate_follows(follows, set(accounts) | {config["platform"]["institution_account_id"]})
	metrics = _network_metrics(accounts, final_adjacency, institution_followers)
	metrics["target_degree_mean"] = statistics.mean(target_degrees.values())
	metrics["target_degree_min"] = min(target_degrees.values())
	metrics["target_degree_max"] = max(target_degrees.values())
	return follows, metrics


def _validate_follows(follows: list[dict[str, Any]], account_ids: set[str]) -> None:
	edges = [(row["follower_id"], row["followee_id"]) for row in follows]
	if len(edges) != len(set(edges)):
		raise ValueError("generated network contains duplicate edges")
	if any(source == target for source, target in edges):
		raise ValueError("generated network contains self follows")
	if any(source not in account_ids or target not in account_ids for source, target in edges):
		raise ValueError("generated network contains a missing endpoint")


def _network_metrics(accounts: list[str], adjacency: dict[str, set[str]], institution_followers: set[str]) -> dict[str, Any]:
	degrees = [len(adjacency[account]) for account in accounts]
	indegrees = Counter(target for targets in adjacency.values() for target in targets)
	undirected: dict[str, set[str]] = defaultdict(set)
	for source, targets in adjacency.items():
		for target in targets:
			undirected[source].add(target)
			undirected[target].add(source)
	remaining = set(accounts)
	largest = 0
	while remaining:
		start = min(remaining)
		queue = deque([start])
		visited = {start}
		while queue:
			current = queue.popleft()
			for neighbor in undirected[current]:
				if neighbor in remaining and neighbor not in visited:
					visited.add(neighbor)
					queue.append(neighbor)
		remaining.difference_update(visited)
		largest = max(largest, len(visited))
	clustering: list[float] = []
	for account in accounts:
		neighbors = sorted(undirected[account] & set(accounts))
		if len(neighbors) < 2:
			clustering.append(0.0)
			continue
		links = sum(1 for index, left in enumerate(neighbors) for right in neighbors[index + 1 :] if right in undirected[left])
		clustering.append(2.0 * links / (len(neighbors) * (len(neighbors) - 1)))
	return {
		"edge_count": sum(degrees),
		"out_degree_mean": statistics.mean(degrees),
		"out_degree_min": min(degrees),
		"out_degree_max": max(degrees),
		"in_degree_max": max(indegrees.values()),
		"largest_weak_component_agents": largest,
		"mean_undirected_clustering": statistics.mean(clustering),
		"institution_initial_followers": len(institution_followers),
	}


def generate_activation_schedule(profiles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
	activation = config["activation"]
	tick_count = int(config["simulation"]["tick_count"])
	# KernRuntime advances world time before TurnScheduler grants active turns,
	# so a fresh 100-step run exposes workflow ticks 1..100 (never tick 0).
	active_by_tick: dict[str, list[str]] = {str(tick): [] for tick in range(1, tick_count + 1)}
	agent_rows: list[dict[str, Any]] = []
	for index, profile in enumerate(profiles, start=1):
		actor_id = f"agent_{index:03d}"
		rng = _rng(config["study_seed"], "activation", actor_id)
		individual = rng.gauss(0.0, float(activation["individual_intercept_stddev"]))
		personality = profile["personality"]

		def next_gap() -> int:
			log_gap = float(activation["gap_intercept"]) + individual + rng.gauss(0.0, float(activation["gap_noise_stddev"]))
			for field_name, coefficient in activation["coefficients"].items():
				log_gap += float(coefficient) * (float(personality[field_name]) - 0.5)
			return max(1, round(math.exp(log_gap)))

		first_gap = next_gap()
		tick = 1 + rng.randrange(first_gap)
		active_ticks: list[int] = []
		while tick <= tick_count:
			active_ticks.append(tick)
			active_by_tick[str(tick)].append(actor_id)
			tick += next_gap()
		agent_rows.append({"actor_id": actor_id, "active_ticks": active_ticks, "individual_random_intercept": individual})
	for actor_ids in active_by_tick.values():
		actor_ids.sort()
	counts = [len(active_by_tick[str(tick)]) for tick in range(1, tick_count + 1)]
	if max(counts) > int(activation["max_active_per_tick"]):
		raise ValueError(f"activation schedule exceeds max_active_per_tick: {max(counts)}")
	schedule = {
		"schema_version": SCHEDULE_SCHEMA,
		"study_seed": config["study_seed"],
		"tick_count": tick_count,
		"algorithm": "heterogeneous_log_gap.v1",
		"parameters": activation,
		"active_by_tick": active_by_tick,
		"agents": agent_rows,
		"summary": {
			"mean_active_per_tick": statistics.mean(counts),
			"mean_active_fraction": statistics.mean(counts) / len(profiles),
			"max_active_per_tick": max(counts),
			"agents_active_at_least_once": sum(bool(row["active_ticks"]) for row in agent_rows),
		},
	}
	schedule["fingerprint"] = _sha256(schedule)
	return schedule


def _entity_templates() -> dict[str, Any]:
	return {
		"SocialExperimentAgent": {
			"name": "Social Experiment Agent",
			"components": {
				"TagComponent": {"tags": ["character", "agent", "social_experiment_agent"]},
				"AgentSetting": {"agent_name": "匿名实验参与者", "personality_summary": "社交实验身份由专用身份组件提供。", "common_knowledge_summary": "你可以在安排的传播轮次打开自己的社交平台。"},
				"PerceptionComponent": {},
				"ContainerComponent": {"slots": {"inventory": {"capacity_count": 1, "accepted_tags": ["social_media_terminal"]}}},
				"AgentControlComponent": {"provider_id": "social_platform"},
				"AgentWakePolicyComponent": {"rules": [{"type": "NoActiveTask", "priority": 1}]},
				"MemoryComponent": {"short_term_queue": [], "short_term_max_entries": 20, "mid_term_queue": [], "mid_term_max_entries": 20},
				"sea_level_social_experiment:SocialIdentityComponent": {
					"profile_id": "template_profile",
					"natural_language_background": "我是社交实验的模板参与者。",
					"big_five": {field_name: 0.5 for field_name in BIG_FIVE_FIELDS},
				},
			},
		},
		"SocialExperimentPhone": {
			"name": "Social Experiment Phone",
			"components": {
				"TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
				"social_propagation:ScreenComponent": {"runtime_id": "social_platform", "account_id": "template_account", "app": "social_platform", "view": "blank"},
			},
		},
	}


def build_world(profiles: list[dict[str, Any]], backgrounds: dict[str, str], schedule: dict[str, Any], manifest_fingerprint: str) -> dict[str, Any]:
	locations: list[dict[str, Any]] = []
	phones: list[dict[str, Any]] = []
	for index, profile in enumerate(profiles, start=1):
		actor_id = f"agent_{index:03d}"
		account_id = f"account_{index:03d}"
		profile_id = profile["profile_id"]
		locations.append(
			{
				"location_id": f"private_social_context_{index:03d}",
				"location_name": f"Private Social Context {index:03d}",
				"description": "A private virtual context for one experimental Agent.",
				"entities": [
					{
						"instance_id": actor_id,
						"template_id": "SocialExperimentAgent",
						"component_overrides": {
							"sea_level_social_experiment:SocialIdentityComponent": {
								"profile_id": profile_id,
								"natural_language_background": backgrounds[profile_id],
								"big_five": {field_name: float(profile["personality"][field_name]) for field_name in BIG_FIVE_FIELDS},
							}
						},
					}
				],
			}
		)
		phones.append(
			{
				"instance_id": f"phone_{index:03d}",
				"template_id": "SocialExperimentPhone",
				"parent_container": actor_id,
				"component_overrides": {"social_propagation:ScreenComponent": {"account_id": account_id}},
			}
		)
	return {
		"world_state": {"current_tick": 0},
		"study": {"study_id": "sea_level_narrative_propagation", "activation_schedule_fingerprint": schedule["fingerprint"], "generation_manifest_fingerprint": manifest_fingerprint},
		"locations": locations,
		"paths": [],
		"entities": phones,
		"environment_scopes": [],
	}


def _load_background_posts(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	payload = _load_json(path)
	allowed = {"schema_version", "generation", "publishers", "posts"}
	if not isinstance(payload, dict) or set(payload).difference(allowed) or not {"schema_version", "publishers", "posts"} <= set(payload):
		raise ValueError("background posts catalog has invalid fields")
	if payload["schema_version"] != "social_background_posts.v1":
		raise ValueError("unsupported background posts schema")
	if not isinstance(payload["publishers"], list) or not isinstance(payload["posts"], list) or len(payload["posts"]) != BACKGROUND_POST_COUNT:
		raise ValueError(f"background catalog must contain publishers and exactly {BACKGROUND_POST_COUNT} posts")
	publisher_ids = {item["account_id"] for item in payload["publishers"]}
	posts: list[dict[str, Any]] = []
	for index, raw in enumerate(payload["posts"]):
		_exact(raw, {"post_id", "account_id", "text", "ranking_topics", "display_hashtags"}, f"background posts[{index}]")
		if raw["account_id"] not in publisher_ids:
			raise ValueError(f"background posts[{index}] has an unknown publisher")
		if not raw["ranking_topics"] or not raw["display_hashtags"] or len(set(raw["ranking_topics"])) != len(raw["ranking_topics"]):
			raise ValueError(f"background posts[{index}] has invalid topics or hashtags")
		posts.append({**raw, "condition_id": "background", "tick": 0})
	return list(payload["publishers"]), posts


def generate(config_path: Path, package_root: Path) -> dict[str, Any]:
	config = load_study_config(config_path)
	profiles, backgrounds, profile_path, background_path = load_population(config)
	weights = config["interest_mapping"]["weights"]
	projections: dict[str, list[dict[str, Any]]] = {}
	accounts: list[dict[str, Any]] = []
	bindings: dict[str, dict[str, str]] = {}
	for index, profile in enumerate(profiles, start=1):
		actor_id = f"agent_{index:03d}"
		account_id = f"account_{index:03d}"
		interests, provenance = project_interests(profile, weights)
		projections[account_id] = provenance
		accounts.append({"account_id": account_id, "display_name": f"用户{index:03d}", "bio": "", "interests": interests})
		bindings[actor_id] = {"account_id": account_id, "terminal_id": f"phone_{index:03d}", "runtime_id": config["platform"]["runtime_id"], "profile_id": profile["profile_id"]}
	background_catalog_path = (ROOT / config["platform"]["background_posts_path"]).resolve()
	publishers, background_posts = _load_background_posts(background_catalog_path)
	accounts.append({"account_id": config["platform"]["institution_account_id"], "display_name": config["platform"]["institution_display_name"], "bio": "海平面与气候风险科普信息发布账号", "interests": {"climate_risk": 1.0, "sea_level": 1.0}})
	accounts.extend({"account_id": item["account_id"], "display_name": item["display_name"], "bio": "中性背景内容发布账号", "interests": {"general_knowledge": 0.1}} for item in publishers)
	follows, network_metrics = generate_network(profiles, config)
	schedule = generate_activation_schedule(profiles, config)
	condition_seeds: dict[str, dict[str, Any]] = {}
	for condition in config["conditions"]:
		experimental_post = {
			"account_id": config["platform"]["institution_account_id"],
			"post_id": condition["post_id"],
			"text": condition["text"],
			"ranking_topics": condition["ranking_topics"],
			"display_hashtags": condition["display_hashtags"],
			"condition_id": condition["condition_id"],
			"tick": 0,
		}
		condition_seeds[condition["condition_id"]] = {"accounts": accounts, "posts": [*background_posts, experimental_post], "follows": follows}
	manifest_base = {
		"schema_version": MANIFEST_SCHEMA,
		"study_id": config["study_id"],
		"study_seed": config["study_seed"],
		"study_config_sha256": _file_sha256(config_path),
		"profile_input": {"path": profile_path.relative_to(ROOT).as_posix(), "sha256": _file_sha256(profile_path), "count": len(profiles)},
		"background_input": {"path": background_path.relative_to(ROOT).as_posix(), "sha256": _file_sha256(background_path), "count": len(backgrounds)},
		"background_posts_input": {"path": background_catalog_path.relative_to(ROOT).as_posix(), "sha256": _file_sha256(background_catalog_path), "count": len(background_posts)},
		"population_count": len(profiles),
		"account_count": len(accounts),
		"network_metrics": network_metrics,
		"activation_summary": schedule["summary"],
		"activation_schedule_fingerprint": schedule["fingerprint"],
		"interest_mapping_version": config["interest_mapping"]["version"],
		"interest_projections_sha256": _sha256(projections),
		"follows_sha256": _sha256(follows),
		"platform_seed_sha256": {condition_id: _sha256(seed) for condition_id, seed in sorted(condition_seeds.items())},
		"condition_ids": [condition["condition_id"] for condition in config["conditions"]],
	}
	manifest_fingerprint = _sha256(manifest_base)
	manifest = {**manifest_base, "fingerprint": manifest_fingerprint, "interest_projections": projections}
	world = build_world(profiles, backgrounds, schedule, manifest_fingerprint)
	data_root = package_root / "Data"
	_write_json(data_root / "Entities" / "social_entities.json", _entity_templates())
	_write_json(data_root / "World.json", world)
	_write_json(data_root / "Study" / "activation_schedule.json", schedule)
	_write_json(data_root / "Study" / "actor_bindings.json", {"schema_version": "social_actor_bindings.v1", "bindings": bindings})
	_write_json(data_root / "Study" / "generation_manifest.json", manifest)
	for condition_id, seed in condition_seeds.items():
		_write_json(data_root / "Platform" / f"social_seed.{condition_id}.json", seed)
	return {"manifest": manifest, "schedule": schedule, "world": world}


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate the paired 300-Agent sea-level social experiment package.")
	parser.add_argument("--study-config", default="Packages/SeaLevelSocialExperiment/Study/study_config.v1.json")
	parser.add_argument("--package-root", default="Packages/SeaLevelSocialExperiment")
	args = parser.parse_args()
	config_path = (ROOT / args.study_config).resolve()
	package_root = (ROOT / args.package_root).resolve()
	result = generate(config_path, package_root)
	print(
		json.dumps(
			{
				"population_count": result["manifest"]["population_count"],
				"network": result["manifest"]["network_metrics"],
				"activation": result["schedule"]["summary"],
				"manifest_fingerprint": result["manifest"]["fingerprint"],
			},
			ensure_ascii=False,
			indent=2,
		)
	)


if __name__ == "__main__":
	main()
