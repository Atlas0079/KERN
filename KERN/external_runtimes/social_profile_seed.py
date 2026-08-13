from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
from functools import cache, cached_property
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "social_profile.v4"
GENERATOR_VERSION = "social_profile_generator.v4"
CONFIG_SCHEMA_VERSION = "social_profile_generation.v3"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "Packages" / "SocialPropagation" / "ProfileConfigs" / "general.json"
SCIENCE_VIDEO_CONFIG_PATH = Path(__file__).resolve().parents[2] / "Packages" / "SocialPropagation" / "ProfileConfigs" / "science_video.json"


class ProfileGenerationError(ValueError):
	"""Raised when the configured profile contract cannot produce a valid value."""


@dataclass(frozen=True)
class GenerationSpec:
	config: Mapping[str, Any]
	source_path: str = ""

	def __post_init__(self) -> None:
		_validate_generation_config(self.config)

	@classmethod
	def from_path(cls, path: str | Path) -> "GenerationSpec":
		resolved_path = Path(path).resolve()
		return cls(config=_load_generation_config(resolved_path), source_path=str(resolved_path))

	@classmethod
	def from_dict(cls, config: Mapping[str, Any]) -> "GenerationSpec":
		return cls(config=deepcopy(dict(config)))

	@property
	def population_id(self) -> str:
		return str(self.config["population_id"])

	@property
	def rule_set(self) -> str:
		return str(self.config["rule_set"])

	@cached_property
	def config_sha256(self) -> str:
		raw = json.dumps(self.config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
		return hashlib.sha256(raw).hexdigest()

	@property
	def age_ranges(self) -> Mapping[str, list[int]]:
		return self.config["lifecycle_age_ranges"]

	def dimension(self, field: str) -> Mapping[str, Any]:
		return self.config["dimensions"][field]

	def weights(self, field: str) -> dict[str, float]:
		return {str(key): float(value) for key, value in self.dimension(field)["weights"].items()}

	def allowed(self, field: str) -> set[str]:
		dimension = self.dimension(field)
		return set(map(str, dimension.get("allowed", _dimension_catalogs()[field])))

	@property
	def lifecycles(self) -> Mapping[str, float]:
		return self.weights("demographics.lifecycle_stage")

LIFECYCLE_RANGES: dict[str, tuple[int, int]] = {
	"student": (18, 26),
	"early_career": (20, 34),
	"family_formation": (24, 39),
	"mid_career": (35, 49),
	"late_career": (50, 59),
	"retired": (60, 72),
}
LIFECYCLE_LABELS = {
	"student": "在校学习阶段",
	"early_career": "职业起步阶段",
	"family_formation": "家庭形成阶段",
	"mid_career": "职业中期",
	"late_career": "职业后期",
	"retired": "退休阶段",
}
GENDER_LABELS = {"female": "女性", "male": "男性"}
AGE_BANDS: dict[str, tuple[int, int]] = {
	"18-24": (18, 24),
	"25-34": (25, 34),
	"35-44": (35, 44),
	"45-54": (45, 54),
	"55+": (55, 72),
}
EDUCATION_LEVELS: dict[str, dict[str, Any]] = {
	"middle_school": {"min_age": 18, "label": "初中及以下"},
	"high_school": {"min_age": 18, "label": "高中"},
	"vocational": {"min_age": 18, "label": "职业教育"},
	"associate": {"min_age": 20, "label": "大专"},
	"bachelor": {"min_age": 22, "label": "本科"},
	"master": {"min_age": 24, "label": "硕士"},
	"doctorate": {"min_age": 28, "label": "博士"},
}
EDUCATION_WEIGHTS = {
	"middle_school": 0.07,
	"high_school": 0.17,
	"vocational": 0.15,
	"associate": 0.20,
	"bachelor": 0.32,
	"master": 0.08,
	"doctorate": 0.01,
}

EDUCATION_FIELDS = {
	"computer_science": "计算机与信息技术",
	"engineering": "工程与制造",
	"finance_economics": "财经与经济",
	"humanities_social_science": "人文与社会科学",
	"education": "教育",
	"health_life_science": "健康与生命科学",
	"arts_design": "艺术与设计",
}
EDUCATION_HISTORY_LEVELS = {
	"middle_school": ("middle_school",),
	"high_school": ("high_school",),
	"vocational": ("vocational",),
	"associate": ("associate",),
	"bachelor": ("bachelor",),
	"master": ("bachelor", "master"),
	"doctorate": ("bachelor", "master", "doctorate"),
}

OCCUPATION_TITLES: dict[str, tuple[str, ...]] = {
	"student": ("中职学生", "大专生", "本科生", "硕士生", "博士生"),
	"service_retail": ("便利店店员", "商场导购", "咖啡店店长", "餐饮服务员", "客服专员"),
	"gig_flexible": ("外卖骑手", "网约车司机", "自由接单设计师", "兼职家教", "平台接单维修工"),
	"office_admin": ("行政助理", "人事专员", "运营专员", "财务文员", "项目协调员"),
	"technical": ("后端开发工程师", "数据分析师", "测试工程师", "机械维修技术员", "网络运维"),
	"creative_media": ("短视频剪辑师", "平面设计师", "摄影助理", "自媒体编辑", "直播运营"),
	"care_education": ("幼儿园老师", "社区社工", "养老护理员", "培训机构老师", "托育中心助教"),
	"trades_manual": ("水电维修工", "木工", "厨师", "仓库叉车工", "装修工"),
	"small_business": ("小餐馆老板", "社区杂货铺店主", "网店店主", "花店经营者", "修车铺合伙人"),
	"between_jobs": ("刚离职正在找工作", "合同到期正在求职", "照顾家人后准备重返职场"),
	"retired": ("退休工人", "退休教师", "退休护士", "半退休个体经营者"),
}
OCCUPATION_WEIGHTS = {
	"service_retail": 0.14,
	"gig_flexible": 0.09,
	"office_admin": 0.15,
	"technical": 0.14,
	"creative_media": 0.09,
	"care_education": 0.11,
	"trades_manual": 0.11,
	"small_business": 0.10,
	"between_jobs": 0.07,
}

CONSUMPTION_LABELS = {
	"budget_optimizer": "消费前会认真比价",
	"value_practical": "重视耐用和实用",
	"experience_spender": "愿意为体验安排预算",
	"status_aware": "在意品牌和社交观感",
	"saver_investor": "习惯储蓄并规划现金流",
	"impulse_treats": "偶尔用小额消费缓解压力",
}
HOUSING_LABELS = {
	"with_parents": "与父母或长辈同住",
	"shared_rental": "与他人合租",
	"solo_rental": "独自租房",
	"partner_family_home": "与伴侣或配偶共同居住",
	"owned_home": "居住在自有住房",
	"temporary": "目前住在临时或过渡住所",
}
ECONOMIC_LABELS = {
	"severe": "压力很重",
	"tight": "比较紧张",
	"manageable": "基本可控",
	"comfortable": "较为宽裕",
	"affluent": "十分宽裕",
}
OCCUPATION_STATUS_LABELS = {"student": "在校学习", "employed": "稳定就业", "flexible": "灵活就业", "unemployed": "正在求职", "retired": "已经退休"}
PARTNERSHIP_LABELS = {"single": "单身", "partnered": "有稳定伴侣", "married": "已婚", "divorced_or_widowed": "离异或丧偶"}
CHILDREN_LABELS = {"none": "没有子女", "preschool": "有学龄前子女", "school_age": "有学龄子女", "adult": "有成年子女"}
ELDER_SUPPORT_LABELS = {"none": "没有固定长辈支持负担", "occasional": "偶尔照应或补贴长辈", "substantial": "承担较多长辈照护或支持"}
FAMILY_BURDEN_LABELS = {"light": "家庭责任较轻", "moderate": "家庭责任中等", "heavy": "家庭责任较重"}

PRACTICAL_INTERESTS = {
	"home_cooking": ("日常做饭", "研究家常食谱"),
	"walking_hiking": ("散步和近郊徒步", "周末逛公园"),
	"casual_fitness": ("低门槛健身", "跟练居家运动"),
	"gaming": ("玩手机或电脑游戏", "研究游戏攻略"),
	"crafts": ("做手工", "修理日常小物件"),
	"community_events": ("参加社区活动", "关注邻里事务"),
	"reading": ("阅读小说和非虚构作品", "逛书店或图书馆"),
	"photography": ("用手机拍照", "整理生活影像"),
	"gardening": ("养花种菜", "研究植物养护"),
	"parent_child": ("陪伴孩子阅读和活动", "寻找亲子活动"),
}
ASPIRATIONAL_INTERESTS = {
	"travel_watching": ("关注旅行内容", "收藏目的地攻略"),
	"premium_tech_watching": ("关注高端电子产品", "观看新品测评"),
	"home_design_watching": ("关注家居设计", "收藏装修案例"),
	"career_learning": ("关注职业成长", "收藏课程和经验帖"),
	"financial_learning": ("学习基础理财知识", "关注长期储蓄方法"),
	"culture_art": ("关注展览与文化内容", "观看艺术纪录片"),
}
HIGH_COST_INTERESTS = {
	"frequent_travel": ("有稳定的跨省或出境旅行计划", "每年安排多次长途旅行"),
	"premium_technology": ("会持续购买高端电子产品", "有明确的旗舰设备换新计划"),
	"collecting": ("持续投入收藏爱好", "为收藏项目预留固定预算"),
}
SCIENCE_TOPICS = {
	"climate_risk": ("气候风险与极端天气", "关注极端天气的成因和影响"),
	"public_health": ("公共健康科普", "关注公共健康解释"),
	"technology_society": ("技术与社会", "关注新技术如何影响日常生活"),
	"environment": ("环境与生态", "关注环境变化和生态保护"),
}


def _deep_merge_config(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
	replace_mapping_keys = {"weights", "count_weights", "item_weights", "inclusion_probability_by_economic_pressure", "multipliers", "replace_weights", "replace_values", "when"}
	result = deepcopy(dict(base))
	for key, value in override.items():
		if key == "extends":
			continue
		if key in replace_mapping_keys:
			result[key] = deepcopy(value)
		elif isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
			result[key] = _deep_merge_config(result[key], value)
		else:
			result[key] = deepcopy(value)
	return result


def _load_generation_config(path: Path, chain: tuple[Path, ...] = ()) -> dict[str, Any]:
	if path in chain:
		raise ProfileGenerationError(f"generation config inheritance cycle: {[str(item) for item in chain + (path,)]}")
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise ProfileGenerationError(f"cannot load generation config {path}: {exc}") from exc
	if not isinstance(raw, dict):
		raise ProfileGenerationError(f"generation config must be a JSON object: {path}")
	if raw.get("schema_version") != CONFIG_SCHEMA_VERSION:
		raise ProfileGenerationError(f"generation config {path} must use {CONFIG_SCHEMA_VERSION}")
	parent_name = raw.get("extends")
	if parent_name is None:
		return deepcopy(raw)
	if not isinstance(parent_name, str) or not parent_name.strip():
		raise ProfileGenerationError(f"generation config extends must be a non-empty relative path: {path}")
	parent_path = (path.parent / parent_name).resolve()
	if parent_path.parent != path.parent.resolve():
		raise ProfileGenerationError("generation config extends must stay in the same directory")
	base = _load_generation_config(parent_path, chain + (path,))
	return _deep_merge_config(base, raw)


@cache
def _dimension_catalogs() -> dict[str, set[str]]:
	return {
		"demographics.lifecycle_stage": set(LIFECYCLE_RANGES),
		"demographics.gender": set(GENDER_LABELS),
		"education.highest_completed": set(EDUCATION_LEVELS),
		"education.current_program": {"vocational", "associate", "bachelor", "master", "doctorate"},
		"education.current_status": {"not_enrolled", "continuing_education"},
		"occupation.status": set(OCCUPATION_STATUS_LABELS) - {"student"},
		"occupation.domain": set(OCCUPATION_WEIGHTS),
		"household.partnership": set(PARTNERSHIP_LABELS),
		"household.children": set(CHILDREN_LABELS),
		"household.elder_support": set(ELDER_SUPPORT_LABELS),
		"household.family_burden": set(FAMILY_BURDEN_LABELS),
		"socioeconomic.housing": set(HOUSING_LABELS),
		"socioeconomic.economic_pressure": set(ECONOMIC_LABELS),
		"socioeconomic.consumption_style": set(CONSUMPTION_LABELS),
	}


def _validate_weights(name: str, weights: Any, catalog: set[str], *, exact: bool = False) -> None:
	if not isinstance(weights, Mapping) or not weights:
		raise ProfileGenerationError(f"{name} must be a non-empty weights object")
	keys = set(map(str, weights))
	if not keys <= catalog or (exact and keys != catalog):
		raise ProfileGenerationError(f"{name} keys differ from catalog: keys={sorted(keys)} catalog={sorted(catalog)}")
	try:
		values = [float(value) for value in weights.values()]
	except (TypeError, ValueError) as exc:
		raise ProfileGenerationError(f"{name} weights must be numeric") from exc
	if any(value < 0 or not math.isfinite(value) for value in values) or sum(values) <= 0:
		raise ProfileGenerationError(f"{name} weights must be finite, non-negative, and have a positive total")


def _validate_generation_config(config: Mapping[str, Any]) -> None:
	required_top = {"schema_version", "population_id", "rule_set", "lifecycle_age_ranges", "age_sampling", "dimensions", "education_pathways", "personality", "details", "interests"}
	if set(config) != required_top:
		raise ProfileGenerationError(f"generation config keys must be exactly {sorted(required_top)}")
	if config.get("schema_version") != CONFIG_SCHEMA_VERSION:
		raise ProfileGenerationError(f"generation config must use {CONFIG_SCHEMA_VERSION}")
	if not str(config.get("population_id", "")).strip():
		raise ProfileGenerationError("population_id cannot be empty")
	if config.get("rule_set") != "china_adult_social.v1":
		raise ProfileGenerationError("unsupported rule_set; expected china_adult_social.v1")
	age_ranges = config.get("lifecycle_age_ranges")
	if not isinstance(age_ranges, Mapping) or set(age_ranges) != set(LIFECYCLE_RANGES):
		raise ProfileGenerationError("lifecycle_age_ranges must define every lifecycle")
	for lifecycle, raw_range in age_ranges.items():
		if not isinstance(raw_range, list) or len(raw_range) != 2:
			raise ProfileGenerationError(f"age range for {lifecycle} must be [min, max]")
		low, high = map(int, raw_range)
		if low < 18 or high > 72 or low > high:
			raise ProfileGenerationError(f"invalid age range for {lifecycle}: {raw_range}")
	age_sampling = config.get("age_sampling")
	if not isinstance(age_sampling, Mapping) or set(age_sampling) != set(LIFECYCLE_RANGES):
		raise ProfileGenerationError("age_sampling must configure every lifecycle")
	for lifecycle, settings in age_sampling.items():
		if not isinstance(settings, Mapping) or settings.get("mode") not in {"uniform", "weighted"}:
			raise ProfileGenerationError(f"age_sampling.{lifecycle} must use uniform or weighted mode")
		if settings["mode"] == "uniform" and set(settings) != {"mode"}:
			raise ProfileGenerationError(f"uniform age_sampling.{lifecycle} only accepts mode")
		if settings["mode"] == "weighted":
			if set(settings) != {"mode", "weights"}:
				raise ProfileGenerationError(f"weighted age_sampling.{lifecycle} requires mode and weights")
			low, high = map(int, age_ranges[lifecycle])
			_validate_weights(f"age_sampling.{lifecycle}.weights", settings["weights"], {str(age) for age in range(low, high + 1)})
	dimensions = config.get("dimensions")
	catalogs = _dimension_catalogs()
	if not isinstance(dimensions, Mapping) or set(dimensions) != set(catalogs):
		raise ProfileGenerationError(f"dimensions must be exactly {sorted(catalogs)}")
	condition_operators = {"in", "not_in", "gte", "lte", "gt", "lt"}
	for field, catalog in catalogs.items():
		dimension = dimensions[field]
		if not isinstance(dimension, Mapping) or not set(dimension) <= {"weights", "allowed", "rules"} or "weights" not in dimension:
			raise ProfileGenerationError(f"dimension {field} has invalid keys")
		_validate_weights(f"dimensions.{field}.weights", dimension["weights"], catalog)
		allowed = dimension.get("allowed")
		if allowed is not None and (not isinstance(allowed, list) or not set(map(str, allowed)) <= catalog or not allowed):
			raise ProfileGenerationError(f"dimensions.{field}.allowed must be a non-empty subset of its catalog")
		for rule in dimension.get("rules", []):
			if not isinstance(rule, Mapping) or not {"rule_id", "reason", "when"} <= set(rule) or len(set(rule) & {"multipliers", "replace_weights", "replace_values"}) != 1:
				raise ProfileGenerationError(f"dimension {field} has an invalid rule")
			if not str(rule["rule_id"]).strip() or not str(rule["reason"]).strip() or not isinstance(rule["when"], Mapping):
				raise ProfileGenerationError(f"dimension {field} rule metadata is invalid")
			for condition in rule["when"].values():
				if isinstance(condition, Mapping) and (len(condition) != 1 or not set(condition) <= condition_operators):
					raise ProfileGenerationError(f"dimension {field} rule uses an unsupported condition")
			operation = next(key for key in ("multipliers", "replace_weights", "replace_values") if key in rule)
			_validate_weights(f"rule {rule['rule_id']} {operation}", rule[operation], catalog)
	pathways = config.get("education_pathways")
	if not isinstance(pathways, Mapping) or set(pathways) != {"field_weights", "transition_weights", "related_fields"}:
		raise ProfileGenerationError("education_pathways must configure field_weights, transition_weights, and related_fields")
	_validate_weights("education_pathways.field_weights", pathways["field_weights"], set(EDUCATION_FIELDS), exact=True)
	transition_catalog = {"same", "related", "different"}
	if not isinstance(pathways["transition_weights"], Mapping) or set(pathways["transition_weights"]) != {"master", "doctorate"}:
		raise ProfileGenerationError("education_pathways.transition_weights must configure master and doctorate")
	for level, weights in pathways["transition_weights"].items():
		_validate_weights(f"education_pathways.transition_weights.{level}", weights, transition_catalog, exact=True)
	related_fields = pathways["related_fields"]
	if not isinstance(related_fields, Mapping) or set(related_fields) != set(EDUCATION_FIELDS):
		raise ProfileGenerationError("education_pathways.related_fields must cover every education field")
	for field, related in related_fields.items():
		if not isinstance(related, list) or not related or field in related or not set(map(str, related)) <= set(EDUCATION_FIELDS):
			raise ProfileGenerationError(f"education_pathways.related_fields.{field} must be a non-empty list of other declared fields")
	personality = config.get("personality")
	traits = {"openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"}
	if not isinstance(personality, Mapping) or set(personality) != traits:
		raise ProfileGenerationError("personality must configure all five traits")
	for trait, params in personality.items():
		if not isinstance(params, Mapping) or set(params) != {"alpha", "beta"} or float(params["alpha"]) <= 0 or float(params["beta"]) <= 0:
			raise ProfileGenerationError(f"personality.{trait} requires positive alpha and beta")
	details = config.get("details")
	if not isinstance(details, Mapping) or set(details) != {"occupation_descriptions"}:
		raise ProfileGenerationError("details must configure occupation_descriptions")
	occupation_details = details["occupation_descriptions"]
	if not isinstance(occupation_details, Mapping) or set(occupation_details) != set(OCCUPATION_TITLES):
		raise ProfileGenerationError("occupation description weights must cover every occupation domain")
	for domain, titles in OCCUPATION_TITLES.items():
		_validate_weights(f"details.occupation_descriptions.{domain}", occupation_details[domain], set(titles), exact=True)
	interests = config.get("interests")
	interest_catalogs = {"practical": PRACTICAL_INTERESTS, "aspirational": ASPIRATIONAL_INTERESTS, "high_cost": HIGH_COST_INTERESTS, "science_topics": SCIENCE_TOPICS}
	if not isinstance(interests, Mapping) or set(interests) != set(interest_catalogs):
		raise ProfileGenerationError("interests must configure practical, aspirational, high_cost, and science_topics")
	for kind, catalog in interest_catalogs.items():
		settings = interests[kind]
		expected_keys = {"count_weights", "item_weights"} | ({"inclusion_probability_by_economic_pressure"} if kind == "high_cost" else set())
		if not isinstance(settings, Mapping) or set(settings) != expected_keys:
			raise ProfileGenerationError(f"interests.{kind} keys must be exactly {sorted(expected_keys)}")
		_validate_weights(f"interests.{kind}.item_weights", settings["item_weights"], set(catalog), exact=True)
		count_weights = settings["count_weights"]
		if not isinstance(count_weights, Mapping) or not count_weights:
			raise ProfileGenerationError(f"interests.{kind}.count_weights must be non-empty")
		for count, weight in count_weights.items():
			if not str(count).isdigit() or int(count) < 0 or int(count) > len(catalog) or float(weight) < 0:
				raise ProfileGenerationError(f"interests.{kind} has an invalid count weight")
		if sum(float(value) for value in count_weights.values()) <= 0:
			raise ProfileGenerationError(f"interests.{kind}.count_weights requires a positive total")
		if kind == "high_cost":
			probabilities = settings["inclusion_probability_by_economic_pressure"]
			if not isinstance(probabilities, Mapping) or set(probabilities) != set(ECONOMIC_LABELS) or any(not 0 <= float(value) <= 1 for value in probabilities.values()):
				raise ProfileGenerationError("high-cost inclusion probabilities must cover every economic-pressure value and stay within [0, 1]")


def default_generation_spec() -> GenerationSpec:
	return GenerationSpec.from_path(DEFAULT_CONFIG_PATH)


def _age_band(age: int) -> str:
	for name, (low, high) in AGE_BANDS.items():
		if low <= age <= high:
			return name
	raise ProfileGenerationError(f"age outside supported range: {age}")


def _stable_seed(seed: int | str | None) -> int:
	if isinstance(seed, int):
		return seed
	return int.from_bytes(hashlib.sha256(str(seed).encode("utf-8")).digest()[:8], "big")


def _allocate_targets(count: int, weights: Mapping[str, float]) -> list[str]:
	if count < 0:
		raise ProfileGenerationError("count cannot be negative")
	total = sum(float(value) for value in weights.values())
	if total <= 0:
		raise ProfileGenerationError("target weights require a positive total")
	exact = {key: count * float(value) / total for key, value in weights.items()}
	allocated = {key: math.floor(value) for key, value in exact.items()}
	remaining = count - sum(allocated.values())
	order = sorted(weights, key=lambda key: (-(exact[key] - allocated[key]), key))
	for key in order[:remaining]:
		allocated[key] += 1
	return [key for key in weights for _ in range(allocated[key])]


def _choice(rng: random.Random, field: str, weights: Mapping[str, float], audit: list[dict[str, Any]], rules: Iterable[tuple[str, str]] = ()) -> str:
	eligible = {str(key): float(value) for key, value in weights.items() if float(value) > 0}
	if not eligible:
		raise ProfileGenerationError(f"{field} has no eligible candidates")
	total = sum(eligible.values())
	point = rng.random() * total
	running = 0.0
	selected = next(reversed(eligible))
	for key, value in eligible.items():
		running += value
		if point < running:
			selected = key
			break
	audit.append(
		{
			"field": field,
			"eligible_weights": {key: round(value, 6) for key, value in eligible.items()},
			"selected": selected,
			"soft_rules": [{"rule_id": rule_id, "reason": reason} for rule_id, reason in rules],
		}
	)
	return selected


def _multiply(weights: Mapping[str, float], multipliers: Mapping[str, float]) -> dict[str, float]:
	return {key: float(value) * float(multipliers.get(key, 1.0)) for key, value in weights.items()}


def _sample_items(rng: random.Random, pool: Mapping[str, tuple[str, str]], count: int, mode: str, weights: Mapping[str, float], audit: list[dict[str, Any]]) -> list[dict[str, str]]:
	remaining = {key: float(weights[key]) for key in pool}
	selected: list[str] = []
	for _ in range(count):
		choice = _choice(rng, f"interests.{mode}.item", remaining, audit)
		selected.append(choice)
		del remaining[choice]
	return [{"id": key, "label": pool[key][0], "expression": pool[key][1], "mode": mode} for key in selected]


def _condition_matches(actual: Any, condition: Any) -> bool:
	if not isinstance(condition, Mapping):
		return actual == condition
	operator, expected = next(iter(condition.items()))
	if operator == "in":
		return actual in expected
	if operator == "not_in":
		return actual not in expected
	if operator == "gte":
		return actual >= expected
	if operator == "lte":
		return actual <= expected
	if operator == "gt":
		return actual > expected
	if operator == "lt":
		return actual < expected
	raise ProfileGenerationError(f"unsupported condition operator: {operator}")


def _configured_weights(spec: GenerationSpec, field: str, context: Mapping[str, Any], hard_allowed: set[str] | None = None) -> tuple[dict[str, float], list[tuple[str, str]]]:
	dimension = spec.dimension(field)
	weights = spec.weights(field)
	applied: list[tuple[str, str]] = []
	for rule in dimension.get("rules", []):
		if not all(key in context and _condition_matches(context[key], condition) for key, condition in rule["when"].items()):
			continue
		if "replace_weights" in rule:
			weights = {str(key): float(value) for key, value in rule["replace_weights"].items()}
		elif "replace_values" in rule:
			weights.update({str(key): float(value) for key, value in rule["replace_values"].items()})
		else:
			weights = _multiply(weights, rule["multipliers"])
		applied.append((str(rule["rule_id"]), str(rule["reason"])))
	allowed = spec.allowed(field)
	if hard_allowed is not None:
		allowed &= set(hard_allowed)
	return {key: value for key, value in weights.items() if key in allowed}, applied


class SocialProfileSampler:
	def __init__(self, seed: int | str | None = None, spec: GenerationSpec | None = None) -> None:
		self.seed = seed
		self.spec = spec or default_generation_spec()
		self.rng = random.Random(_stable_seed(seed))

	def _next_education_field(self, previous: str, level: str, audit: list[dict[str, Any]]) -> str:
		pathways = self.spec.config["education_pathways"]
		transition = _choice(self.rng, f"education.history.{level}.transition", pathways["transition_weights"][level], audit)
		if transition == "same":
			field = previous
		elif transition == "related":
			field = _choice(
				self.rng,
				f"education.history.{level}.field",
				{value: pathways["field_weights"][value] for value in pathways["related_fields"][previous]},
				audit,
			)
		else:
			excluded = {previous, *pathways["related_fields"][previous]}
			field = _choice(
				self.rng,
				f"education.history.{level}.field",
				{value: weight for value, weight in pathways["field_weights"].items() if value not in excluded},
				audit,
			)
		audit.append({"field": f"education.history.{level}.continuity", "previous": previous, "transition": transition, "selected": field})
		return field

	def _education_history(self, highest_completed: str, audit: list[dict[str, Any]]) -> list[dict[str, str]]:
		levels = EDUCATION_HISTORY_LEVELS[highest_completed]
		if highest_completed in {"middle_school", "high_school"}:
			return [{"level": highest_completed, "level_label": EDUCATION_LEVELS[highest_completed]["label"], "field": "general", "field_label": "通识教育"}]
		field = _choice(self.rng, f"education.history.{levels[0]}.field", self.spec.config["education_pathways"]["field_weights"], audit)
		history: list[dict[str, str]] = []
		for position, level in enumerate(levels):
			if position:
				field = self._next_education_field(field, level, audit)
			history.append({"level": level, "level_label": str(EDUCATION_LEVELS[level]["label"]), "field": field, "field_label": EDUCATION_FIELDS[field]})
		return history

	def _current_program_field(self, history: list[dict[str, str]], current_program: str, audit: list[dict[str, Any]]) -> str:
		if current_program in {"master", "doctorate"}:
			return self._next_education_field(history[-1]["field"], current_program, audit)
		return _choice(self.rng, f"education.current_program.{current_program}.field", self.spec.config["education_pathways"]["field_weights"], audit)

	@staticmethod
	def _education_description(history: list[dict[str, str]]) -> str:
		last = history[-1]
		if last["field"] == "general":
			return "完成初中及以下教育" if last["level"] == "middle_school" else "高中毕业"
		return f"{last['field_label']}方向{last['level_label']}毕业"

	def sample_profile(self, index: int, *, lifecycle_stage: str, include_audit: bool = False) -> dict[str, Any]:
		audit: list[dict[str, Any]] = []
		if lifecycle_stage not in self.spec.allowed("demographics.lifecycle_stage"):
			raise ProfileGenerationError(f"lifecycle {lifecycle_stage} is forbidden by population config {self.spec.population_id}")

		low, high = map(int, self.spec.age_ranges[lifecycle_stage])
		allowed_education = self.spec.allowed("education.highest_completed")
		low = max(low, min(int(EDUCATION_LEVELS[level]["min_age"]) for level in allowed_education))
		age_settings = self.spec.config["age_sampling"][lifecycle_stage]
		if age_settings["mode"] == "uniform":
			age = self.rng.randint(low, high)
			audit.append({"field": "demographics.age", "eligible_range": [low, high], "selected": age, "configured_mode": "uniform", "hard_rules": [f"config.lifecycle_age_ranges.{lifecycle_stage}", "education.minimum_completion_age"]})
		else:
			age_weights = {key: value for key, value in age_settings["weights"].items() if low <= int(key) <= high}
			age = int(_choice(self.rng, "demographics.age", age_weights, audit))
		context: dict[str, Any] = {"age": age, "lifecycle_stage": lifecycle_stage}
		gender_weights, rules = _configured_weights(self.spec, "demographics.gender", context)
		gender = _choice(self.rng, "demographics.gender", gender_weights, audit, rules)
		context["gender"] = gender

		education_hard_allowed = {
			level for level, data in EDUCATION_LEVELS.items()
			if age >= int(data["min_age"]) and (lifecycle_stage != "student" or level != "doctorate")
		}
		education_weights, rules = _configured_weights(self.spec, "education.highest_completed", context, education_hard_allowed)
		education_level = _choice(self.rng, "education.highest_completed", education_weights, audit, rules)
		context["education_level"] = education_level

		if lifecycle_stage == "student":
			program_priors = {
				"vocational": {"middle_school", "high_school"},
				"associate": {"middle_school", "high_school", "vocational"},
				"bachelor": {"middle_school", "high_school", "vocational", "associate"},
				"master": {"bachelor"},
				"doctorate": {"master"},
			}
			program_allowed = {program for program, priors in program_priors.items() if education_level in priors and age >= int(EDUCATION_LEVELS[education_level]["min_age"])}
			enrollment_options, rules = _configured_weights(self.spec, "education.current_program", context, program_allowed)
			current_program = _choice(self.rng, "education.current_program", enrollment_options, audit, rules)
			current_status = "enrolled"
		else:
			status_weights, rules = _configured_weights(self.spec, "education.current_status", context)
			current_status = _choice(self.rng, "education.current_status", status_weights, audit, rules)
			current_program = education_level if current_status == "continuing_education" else None

		education_history = self._education_history(education_level, audit)
		current_program_field = self._current_program_field(education_history, str(current_program), audit) if current_program else None
		education_description = self._education_description(education_history)

		if lifecycle_stage == "student":
			occupation_status = "student"
			occupation_domain = "student"
			student_titles = {
				"vocational": "中职学生",
				"associate": "大专生",
				"bachelor": "本科生",
				"master": "硕士生",
				"doctorate": "博士生",
			}
			student_title = student_titles[str(current_program)]
			occupation_title = _choice(self.rng, "occupation.description", {student_title: self.spec.config["details"]["occupation_descriptions"]["student"][student_title]}, audit)
			audit.append({"field": "occupation.status", "eligible_values": ["student"], "selected": "student", "hard_rules": ["occupation.student_lifecycle"]})
		else:
			status_weights, rules = _configured_weights(self.spec, "occupation.status", context)
			occupation_status = _choice(self.rng, "occupation.status", status_weights, audit, rules)
			if occupation_status == "retired":
				occupation_domain = "retired"
			elif occupation_status == "unemployed":
				occupation_domain = "between_jobs"
			else:
				domain_weights, rules = _configured_weights(self.spec, "occupation.domain", context, set(OCCUPATION_TITLES) - {"student", "retired", "between_jobs"})
				occupation_domain = _choice(self.rng, "occupation.domain", domain_weights, audit, rules)
			occupation_title = _choice(self.rng, "occupation.description", self.spec.config["details"]["occupation_descriptions"][occupation_domain], audit)
		context["occupation_status"] = occupation_status

		partnership_weights, rules = _configured_weights(self.spec, "household.partnership", context)
		partnership = _choice(self.rng, "household.partnership", partnership_weights, audit, rules)
		context["partnership"] = partnership
		children_allowed = {"none"}
		if lifecycle_stage != "student":
			if age >= 22:
				children_allowed.add("preschool")
			if age >= 27:
				children_allowed.add("school_age")
			if age >= 40:
				children_allowed.add("adult")
		children_weights, rules = _configured_weights(self.spec, "household.children", context, children_allowed)
		children = _choice(self.rng, "household.children", children_weights, audit, rules)
		context["children"] = children
		elder_weights, rules = _configured_weights(self.spec, "household.elder_support", context)
		elder_support = _choice(self.rng, "household.elder_support", elder_weights, audit, rules)
		context["elder_support"] = elder_support
		context["has_dependents"] = children != "none" or elder_support == "substantial"
		burden_weights, rules = _configured_weights(self.spec, "household.family_burden", context)
		family_burden = _choice(self.rng, "household.family_burden", burden_weights, audit, rules)

		housing_weights, rules = _configured_weights(self.spec, "socioeconomic.housing", context)
		housing = _choice(self.rng, "socioeconomic.housing", housing_weights, audit, rules)

		economic_weights, rules = _configured_weights(self.spec, "socioeconomic.economic_pressure", context)
		economic_pressure = _choice(self.rng, "socioeconomic.economic_pressure", economic_weights, audit, rules)
		context["economic_pressure"] = economic_pressure

		personality = {
			trait: round(self.rng.betavariate(float(params["alpha"]), float(params["beta"])), 1)
			for trait, params in self.spec.config["personality"].items()
		}
		consumption_weights, rules = _configured_weights(self.spec, "socioeconomic.consumption_style", context)
		consumption_style = _choice(self.rng, "socioeconomic.consumption_style", consumption_weights, audit, rules)

		def interest_count(kind: str) -> int:
			settings = self.spec.config["interests"][kind]
			return int(_choice(self.rng, f"interests.{kind}.count", settings["count_weights"], audit))

		practical_settings = self.spec.config["interests"]["practical"]
		aspirational_settings = self.spec.config["interests"]["aspirational"]
		practical_count = interest_count("practical")
		aspirational_count = interest_count("aspirational")
		interests = {
			"practical": _sample_items(self.rng, PRACTICAL_INTERESTS, practical_count, "practiced", practical_settings["item_weights"], audit),
			"aspirational": _sample_items(self.rng, ASPIRATIONAL_INTERESTS, aspirational_count, "observed_or_aspired", aspirational_settings["item_weights"], audit),
			"high_cost": [],
			"science_topics": [],
		}
		high_cost_settings = self.spec.config["interests"]["high_cost"]
		inclusion_probability = float(high_cost_settings["inclusion_probability_by_economic_pressure"][economic_pressure])
		included = self.rng.random() < inclusion_probability
		audit.append({"field": "interests.high_cost.included", "probability": inclusion_probability, "selected": included})
		if included:
			high_cost_count = interest_count("high_cost")
			interests["high_cost"] = _sample_items(self.rng, HIGH_COST_INTERESTS, high_cost_count, "practiced_or_planned", high_cost_settings["item_weights"], audit)
		science_settings = self.spec.config["interests"]["science_topics"]
		science_count = interest_count("science_topics")
		interests["science_topics"] = _sample_items(self.rng, SCIENCE_TOPICS, science_count, "followed_topic", science_settings["item_weights"], audit)

		profile: dict[str, Any] = {
			"schema_version": SCHEMA_VERSION,
			"profile_id": f"social_profile_{index:03d}",
			"provenance": {"generator_version": GENERATOR_VERSION, "seed": str(self.seed), "population_id": self.spec.population_id, "rule_set": self.spec.rule_set, "config_sha256": self.spec.config_sha256, "index": index},
			"demographics": {"age": age, "age_band": _age_band(age), "lifecycle_stage": lifecycle_stage, "gender": gender, "gender_label": GENDER_LABELS[gender]},
			"education": {
				"highest_completed": education_level,
				"highest_completed_label": str(EDUCATION_LEVELS[education_level]["label"]),
				"description": education_description,
				"history": education_history,
				"current_status": current_status,
				"current_program": current_program,
				"current_program_field": current_program_field,
			},
			"occupation": {"status": occupation_status, "domain": occupation_domain, "description": occupation_title},
			"household": {"partnership": partnership, "children": children, "elder_support": elder_support, "family_burden": family_burden},
			"socioeconomic": {
				"economic_pressure": economic_pressure,
				"housing": housing,
				"housing_description": HOUSING_LABELS[housing],
				"consumption_style": consumption_style,
				"consumption_description": CONSUMPTION_LABELS[consumption_style],
			},
			"personality": personality,
			"interests": interests,
		}
		profile["summary_line"] = f"{age}岁，{education_description}，{occupation_title}，经济状况{ECONOMIC_LABELS[economic_pressure]}。"
		violations = validate_profile(profile, self.spec)
		if violations:
			raise ProfileGenerationError(f"generated invalid {profile['profile_id']}: {'; '.join(violations)}")
		if include_audit:
			profile["audit"] = {"sampling_steps": audit, "validation": "passed"}
		return profile


def validate_profile(profile: Mapping[str, Any], spec: GenerationSpec | None = None) -> list[str]:
	violations: list[str] = []
	if profile.get("schema_version") != SCHEMA_VERSION:
		violations.append(f"schema_version must be {SCHEMA_VERSION}")
	try:
		demographics = dict(profile["demographics"])
		education = dict(profile["education"])
		occupation = dict(profile["occupation"])
		household = dict(profile["household"])
		socioeconomic = dict(profile["socioeconomic"])
		interests = dict(profile["interests"])
	except (KeyError, TypeError, ValueError):
		return violations + ["required profile sections are missing or invalid"]
	age = int(demographics.get("age", -1))
	lifecycle = str(demographics.get("lifecycle_stage", ""))
	age_ranges = spec.age_ranges if spec is not None else LIFECYCLE_RANGES
	if lifecycle not in age_ranges or not (int(age_ranges[lifecycle][0]) <= age <= int(age_ranges[lifecycle][1])):
		violations.append("age is outside lifecycle range")
	if age < 18 or age > 72 or demographics.get("age_band") != _age_band(age):
		violations.append("age_band is not derived from age")
	gender = str(demographics.get("gender", ""))
	if gender not in GENDER_LABELS or demographics.get("gender_label") != GENDER_LABELS.get(gender):
		violations.append("gender is unknown or mislabeled")
	level = str(education.get("highest_completed", ""))
	if level not in EDUCATION_LEVELS:
		violations.append("unknown education level")
	else:
		if age < int(EDUCATION_LEVELS[level]["min_age"]):
			violations.append("education completion is impossible at this age")
	history = education.get("history")
	if level in EDUCATION_HISTORY_LEVELS:
		expected_levels = list(EDUCATION_HISTORY_LEVELS[level])
		if not isinstance(history, list) or [item.get("level") for item in history if isinstance(item, Mapping)] != expected_levels or len(history) != len(expected_levels):
			violations.append("education history does not match highest completed level")
		else:
			for item in history:
				stage = str(item.get("level", ""))
				field = str(item.get("field", ""))
				if item.get("level_label") != EDUCATION_LEVELS[stage]["label"]:
					violations.append("education history level label does not match level")
				if stage in {"middle_school", "high_school"}:
					if field != "general" or item.get("field_label") != "通识教育":
						violations.append("secondary education history must use the general field")
				elif field not in EDUCATION_FIELDS or item.get("field_label") != EDUCATION_FIELDS.get(field):
					violations.append("education history field is unknown or mislabeled")
			if education.get("description") != SocialProfileSampler._education_description(history):
				violations.append("education description is not derived from education history")
	if education.get("current_status") not in {"enrolled", "not_enrolled", "continuing_education"}:
		violations.append("unknown current education status")
	if lifecycle == "student":
		if education.get("current_status") != "enrolled" or not education.get("current_program"):
			violations.append("student lifecycle requires an enrolled education program")
		program_priors = {
			"vocational": {"middle_school", "high_school"},
			"associate": {"middle_school", "high_school", "vocational"},
			"bachelor": {"middle_school", "high_school", "vocational", "associate"},
			"master": {"bachelor"},
			"doctorate": {"master"},
		}
		program = str(education.get("current_program", ""))
		if program not in program_priors or level not in program_priors[program]:
			violations.append("current education program does not follow completed education")
		if occupation.get("status") != "student" or occupation.get("domain") != "student":
			violations.append("student lifecycle requires student occupation")
		if household.get("children") != "none":
			violations.append("student lifecycle cannot have dependent children in this population contract")
	elif occupation.get("status") == "student" or occupation.get("domain") == "student":
		violations.append("student occupation requires student lifecycle")
	elif education.get("current_status") == "enrolled":
		violations.append("enrolled education requires student lifecycle")
	elif education.get("current_status") == "not_enrolled" and education.get("current_program") is not None:
		violations.append("not-enrolled education cannot have a current program")
	elif education.get("current_status") == "continuing_education" and education.get("current_program") != level:
		violations.append("continuing education program must match its declared level")
	current_program = education.get("current_program")
	current_field = education.get("current_program_field")
	if current_program is None and current_field is not None:
		violations.append("education without a current program cannot have a current field")
	elif current_program is not None and current_field not in EDUCATION_FIELDS:
		violations.append("current education program requires a declared education field")
	occupation_status = str(occupation.get("status", ""))
	occupation_domain = str(occupation.get("domain", ""))
	if occupation_status not in OCCUPATION_STATUS_LABELS:
		violations.append("unknown occupation status")
	if occupation_domain not in OCCUPATION_TITLES:
		violations.append("unknown occupation domain")
	elif occupation.get("description") not in OCCUPATION_TITLES[occupation_domain]:
		violations.append("occupation description does not belong to its domain")
	if (occupation_status == "retired") != (occupation_domain == "retired"):
		violations.append("retired status and occupation domain must agree")
	if (occupation_status == "unemployed") != (occupation_domain == "between_jobs"):
		violations.append("unemployed status and between-jobs domain must agree")
	children = household.get("children")
	if household.get("partnership") not in PARTNERSHIP_LABELS:
		violations.append("unknown partnership value")
	if children not in CHILDREN_LABELS:
		violations.append("unknown children value")
	if household.get("elder_support") not in ELDER_SUPPORT_LABELS:
		violations.append("unknown elder-support value")
	if household.get("family_burden") not in FAMILY_BURDEN_LABELS:
		violations.append("unknown family-burden value")
	if children == "preschool" and age < 22:
		violations.append("preschool children require age 22+")
	if children == "school_age" and age < 27:
		violations.append("school-age children require age 27+")
	if children == "adult" and age < 40:
		violations.append("adult children require age 40+")
	if socioeconomic.get("economic_pressure") in {"severe", "tight"} and list(interests.get("high_cost", []) or []):
		violations.append("high-cost practiced interests require manageable or better finances")
	if socioeconomic.get("economic_pressure") not in ECONOMIC_LABELS:
		violations.append("unknown economic-pressure value")
	housing = str(socioeconomic.get("housing", ""))
	if housing not in HOUSING_LABELS or socioeconomic.get("housing_description") != HOUSING_LABELS.get(housing):
		violations.append("housing description must match housing value")
	consumption = str(socioeconomic.get("consumption_style", ""))
	if consumption not in CONSUMPTION_LABELS or socioeconomic.get("consumption_description") != CONSUMPTION_LABELS.get(consumption):
		violations.append("consumption description must match consumption style")
	trait_names = {"openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"}
	personality = dict(profile.get("personality", {}))
	if set(personality) != trait_names:
		violations.append("personality must contain exactly the five declared traits")
	for trait, value in personality.items():
		if trait not in trait_names or not (0.0 <= float(value) <= 1.0):
			violations.append(f"invalid personality trait: {trait}")
	interest_contract = {
		"practical": (PRACTICAL_INTERESTS, "practiced"),
		"aspirational": (ASPIRATIONAL_INTERESTS, "observed_or_aspired"),
		"high_cost": (HIGH_COST_INTERESTS, "practiced_or_planned"),
		"science_topics": (SCIENCE_TOPICS, "followed_topic"),
	}
	for kind, (pool, expected_mode) in interest_contract.items():
		items = interests.get(kind)
		if not isinstance(items, list):
			violations.append(f"interests.{kind} must be a list")
			continue
		seen: set[str] = set()
		for item in items:
			if not isinstance(item, Mapping):
				violations.append(f"interests.{kind} contains a non-object")
				continue
			item_id = str(item.get("id", ""))
			if item_id in seen:
				violations.append(f"interests.{kind} contains duplicate IDs")
			seen.add(item_id)
			if item_id not in pool or item.get("label") != pool.get(item_id, (None, None))[0] or item.get("expression") != pool.get(item_id, (None, None))[1] or item.get("mode") != expected_mode:
				violations.append(f"interests.{kind} item does not match its declared catalog entry")
	provenance = profile.get("provenance", {})
	if not isinstance(provenance, Mapping) or provenance.get("generator_version") != GENERATOR_VERSION or not str(provenance.get("population_id", "")):
		violations.append("profile provenance is missing generator or population identity")
	if spec is not None:
		if provenance.get("population_id") != spec.population_id or provenance.get("rule_set") != spec.rule_set or provenance.get("config_sha256") != spec.config_sha256:
			violations.append("profile provenance differs from generation config")
		configured_values = {
			"demographics.lifecycle_stage": lifecycle,
			"demographics.gender": gender,
			"education.highest_completed": level,
			"education.current_status": education.get("current_status"),
			"occupation.status": occupation_status,
			"occupation.domain": occupation_domain,
			"household.partnership": household.get("partnership"),
			"household.children": children,
			"household.elder_support": household.get("elder_support"),
			"household.family_burden": household.get("family_burden"),
			"socioeconomic.housing": housing,
			"socioeconomic.economic_pressure": socioeconomic.get("economic_pressure"),
			"socioeconomic.consumption_style": consumption,
		}
		for field, value in configured_values.items():
			if value is not None and value not in spec.allowed(field) and not (field == "education.current_status" and value == "enrolled") and not (field == "occupation.status" and value == "student") and not (field == "occupation.domain" and value in {"student", "retired"}):
				violations.append(f"{field} value is forbidden by generation config")
		if education.get("current_status") == "enrolled" and education.get("current_program") not in spec.allowed("education.current_program"):
			violations.append("education.current_program value is forbidden by generation config")
		for kind in ("practical", "aspirational", "science_topics"):
			allowed_counts = {int(value) for value, weight in spec.config["interests"][kind]["count_weights"].items() if float(weight) > 0}
			if len(interests.get(kind, [])) not in allowed_counts:
				violations.append(f"interests.{kind} count is forbidden by generation config")
		allowed_high_cost_counts = {0} | {int(value) for value, weight in spec.config["interests"]["high_cost"]["count_weights"].items() if float(weight) > 0}
		if len(interests.get("high_cost", [])) not in allowed_high_cost_counts:
			violations.append("interests.high_cost count is forbidden by generation config")
	expected_summary = None
	if age in range(18, 73) and education.get("description") and occupation.get("description") and socioeconomic.get("economic_pressure") in ECONOMIC_LABELS:
		expected_summary = f"{age}岁，{education['description']}，{occupation['description']}，经济状况{ECONOMIC_LABELS[socioeconomic['economic_pressure']]}。"
	if profile.get("summary_line") != expected_summary:
		violations.append("summary_line is not the deterministic projection of profile facts")
	return violations


def validate_population(profiles: list[Mapping[str, Any]], spec: GenerationSpec) -> list[str]:
	violations: list[str] = []
	ids = [str(profile.get("profile_id", "")) for profile in profiles]
	if len(ids) != len(set(ids)) or any(not value for value in ids):
		violations.append("profile IDs must be non-empty and unique")
	for profile in profiles:
		for issue in validate_profile(profile, spec):
			violations.append(f"{profile.get('profile_id', '<unknown>')}: {issue}")
	expected_lifecycles = Counter(_allocate_targets(len(profiles), _effective_lifecycle_targets(spec)))
	actual_lifecycles = Counter(str(profile["demographics"]["lifecycle_stage"]) for profile in profiles)
	if actual_lifecycles != expected_lifecycles:
		violations.append(f"lifecycle quotas differ: expected={dict(expected_lifecycles)} actual={dict(actual_lifecycles)}")
	return violations


def _effective_lifecycle_targets(spec: GenerationSpec) -> dict[str, float]:
	allowed = spec.allowed("demographics.lifecycle_stage")
	return {key: float(value) for key, value in spec.lifecycles.items() if key in allowed and float(value) > 0}


def lifecycle_targets_for(spec: GenerationSpec) -> dict[str, float]:
	return _effective_lifecycle_targets(spec)


def generate_social_profiles(
	count: int = 100,
	seed: int | str | None = None,
	*,
	include_audit: bool = False,
	spec: GenerationSpec | None = None,
) -> list[dict[str, Any]]:
	resolved_spec = spec or default_generation_spec()
	sampler = SocialProfileSampler(seed=seed, spec=resolved_spec)
	lifecycles = _allocate_targets(count, _effective_lifecycle_targets(resolved_spec))
	sampler.rng.shuffle(lifecycles)
	profiles = [
		sampler.sample_profile(index, lifecycle_stage=lifecycle, include_audit=include_audit)
		for index, lifecycle in enumerate(lifecycles, start=1)
	]
	violations = validate_population(profiles, resolved_spec)
	if violations:
		raise ProfileGenerationError("population validation failed: " + "; ".join(violations))
	return profiles
