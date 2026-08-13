from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from KERN.external_runtimes.social_profile_seed import (
	DEFAULT_CONFIG_PATH,
	GENERATOR_VERSION,
	SCHEMA_VERSION,
	SCIENCE_VIDEO_CONFIG_PATH,
	GenerationSpec,
	ProfileGenerationError,
	default_generation_spec,
	generate_social_profiles,
	validate_population,
	validate_profile,
)
from tools.generate_social_agent_backgrounds import _normalize_generated, _prompt, _source_card
from tools.generate_social_profiles import main as generate_profiles_main
from tools.social_profile_report import build_report_data


class SocialProfileV4Tests(unittest.TestCase):
	def test_same_seed_and_spec_generate_identical_profiles(self) -> None:
		a = generate_social_profiles(50, "same")
		b = generate_social_profiles(50, "same")
		c = generate_social_profiles(50, "different")
		self.assertEqual(a, b)
		self.assertNotEqual(a, c)

	def test_population_uses_exact_lifecycle_quotas(self) -> None:
		profiles = generate_social_profiles(100, "quotas")
		lifecycles = Counter(profile["demographics"]["lifecycle_stage"] for profile in profiles)
		self.assertEqual(lifecycles, Counter({"early_career": 22, "mid_career": 22, "family_formation": 20, "student": 14, "late_career": 12, "retired": 10}))

	def test_profile_has_single_source_of_facts_v2_shape(self) -> None:
		profile = generate_social_profiles(1, "shape")[0]
		self.assertEqual(profile["schema_version"], SCHEMA_VERSION)
		self.assertEqual(profile["provenance"]["generator_version"], GENERATOR_VERSION)
		self.assertIn(profile["demographics"]["gender"], {"female", "male"})
		for section in ("demographics", "education", "occupation", "household", "socioeconomic", "personality", "interests"):
			self.assertIsInstance(profile[section], dict)
		self.assertNotIn("platform_behavior", profile)
		for retired_key in ("sample", "specifics", "display", "audience_preset", "debug"):
			self.assertNotIn(retired_key, profile)
		self.assertEqual(validate_profile(profile), [])

	def test_many_seeds_never_emit_hard_contract_violations(self) -> None:
		spec = default_generation_spec()
		for seed in range(10):
			profiles = generate_social_profiles(500, seed, spec=spec)
			self.assertEqual(validate_population(profiles, spec), [])

	def test_lifecycle_education_occupation_and_children_are_coherent(self) -> None:
		profiles = generate_social_profiles(2000, "lifecycle-contract")
		program_priors = {
			"vocational": {"middle_school", "high_school"},
			"associate": {"middle_school", "high_school", "vocational"},
			"bachelor": {"middle_school", "high_school", "vocational", "associate"},
			"master": {"bachelor"},
			"doctorate": {"master"},
		}
		for profile in profiles:
			demographics = profile["demographics"]
			education = profile["education"]
			occupation = profile["occupation"]
			household = profile["household"]
			if demographics["lifecycle_stage"] == "student":
				self.assertEqual(education["current_status"], "enrolled")
				self.assertIn(education["highest_completed"], program_priors[education["current_program"]])
				self.assertEqual(occupation["status"], "student")
				self.assertEqual(household["children"], "none")
			else:
				self.assertNotEqual(occupation["status"], "student")
			age = demographics["age"]
			minimum_age = {"none": 18, "preschool": 22, "school_age": 27, "adult": 40}[household["children"]]
			self.assertGreaterEqual(age, minimum_age)

	def test_science_video_config_shapes_only_background_facts(self) -> None:
		spec = GenerationSpec.from_path(SCIENCE_VIDEO_CONFIG_PATH)
		profiles = generate_social_profiles(100, "science", spec=spec)
		for profile in profiles:
			self.assertIn(profile["demographics"]["lifecycle_stage"], {"early_career", "family_formation", "mid_career", "late_career"})
			self.assertIn(profile["education"]["highest_completed"], {"bachelor", "master", "doctorate"})
			self.assertEqual(len(profile["interests"]["science_topics"]), 2)
			self.assertNotIn("platform_behavior", profile)
		self.assertEqual(validate_population(profiles, spec), [])

	def test_high_education_high_cognition_population_contract(self) -> None:
		config_path = DEFAULT_CONFIG_PATH.parent / "high_education_high_cognition.json"
		spec = GenerationSpec.from_path(config_path)
		profiles = generate_social_profiles(300, "high-education-contract", spec=spec)
		self.assertTrue(all(profile["education"]["highest_completed"] in {"bachelor", "master", "doctorate"} for profile in profiles))
		self.assertTrue(any(profile["education"]["highest_completed"] == "doctorate" for profile in profiles))
		self.assertTrue(all("platform_behavior" not in profile for profile in profiles))
		self.assertGreater(sum(profile["personality"]["openness"] for profile in profiles) / len(profiles), 0.62)
		self.assertGreater(sum(profile["personality"]["conscientiousness"] for profile in profiles) / len(profiles), 0.62)
		self.assertEqual(validate_population(profiles, spec), [])

	def test_advanced_degrees_have_configured_field_continuity(self) -> None:
		profiles = generate_social_profiles(4000, "education-continuity")
		transitions = [
			(previous["field"], current["field"])
			for profile in profiles
			for previous, current in zip(profile["education"]["history"], profile["education"]["history"][1:])
		]
		self.assertTrue(transitions)
		self.assertGreater(sum(before == after for before, after in transitions) / len(transitions), 0.65)
		self.assertTrue(any(before != after for before, after in transitions))

	def test_high_cost_interest_requires_financial_capacity(self) -> None:
		profiles = generate_social_profiles(2000, "high-cost")
		high_cost = [profile for profile in profiles if profile["interests"]["high_cost"]]
		self.assertTrue(high_cost)
		self.assertTrue(all(profile["socioeconomic"]["economic_pressure"] in {"comfortable", "affluent"} for profile in high_cost))

	def test_audit_explains_candidates_and_soft_rules_without_changing_facts(self) -> None:
		plain = generate_social_profiles(100, "audit", include_audit=False)
		audited = generate_social_profiles(100, "audit", include_audit=True)
		self.assertEqual([{k: v for k, v in p.items() if k != "audit"} for p in audited], plain)
		steps = [step for profile in audited for step in profile["audit"]["sampling_steps"]]
		self.assertTrue(all(step.get("selected") is not None for step in steps))
		self.assertTrue(any(rule["rule_id"].startswith("occupation.") for step in steps for rule in step.get("soft_rules", [])))
		self.assertTrue(any("eligible_weights" in step for step in steps))

	def test_validator_rejects_mutated_invalid_facts(self) -> None:
		profile = deepcopy(generate_social_profiles(100, "mutation")[0])
		profile["demographics"]["age_band"] = "55+"
		self.assertIn("age_band is not derived from age", validate_profile(profile))
		profile = deepcopy(next(item for item in generate_social_profiles(100, "student-mutation") if item["demographics"]["lifecycle_stage"] == "student"))
		profile["household"]["children"] = "adult"
		issues = validate_profile(profile)
		self.assertIn("student lifecycle cannot have dependent children in this population contract", issues)
		profile = deepcopy(next(item for item in generate_social_profiles(500, "education-mutation") if item["education"]["highest_completed"] == "master"))
		profile["education"]["description"] = "与轨迹冲突的硕士描述"
		self.assertIn("education description is not derived from education history", validate_profile(profile))

	def test_invalid_config_keys_and_values_fail_loudly(self) -> None:
		config = deepcopy(default_generation_spec().config)
		config["unexpected"] = True
		with self.assertRaises(ProfileGenerationError):
			GenerationSpec.from_dict(config)
		config = deepcopy(default_generation_spec().config)
		config["dimensions"]["education.highest_completed"]["allowed"] = ["invented_level"]
		with self.assertRaises(ProfileGenerationError):
			GenerationSpec.from_dict(config)

	def test_every_stochastic_dimension_can_be_shaped_by_population_config(self) -> None:
		config = deepcopy(default_generation_spec().config)
		config["population_id"] = "fully_shaped_test_population"
		config["lifecycle_age_ranges"]["early_career"] = [28, 30]
		config["age_sampling"]["early_career"] = {"mode": "weighted", "weights": {"28": 0.0, "29": 0.0, "30": 1.0}}
		dimensions = config["dimensions"]
		dimensions["demographics.lifecycle_stage"]["weights"] = {"student": 0, "early_career": 1, "family_formation": 0, "mid_career": 0, "late_career": 0, "retired": 0}
		forced = {
			"demographics.gender": "female",
			"education.highest_completed": "bachelor",
			"education.current_status": "not_enrolled",
			"occupation.status": "employed",
			"occupation.domain": "technical",
			"household.partnership": "single",
			"household.children": "none",
			"household.elder_support": "none",
			"household.family_burden": "light",
			"socioeconomic.housing": "solo_rental",
			"socioeconomic.economic_pressure": "manageable",
			"socioeconomic.consumption_style": "budget_optimizer",
		}
		for field, value in forced.items():
			dimensions[field]["allowed"] = [value]
		for trait in config["personality"].values():
			trait.update({"alpha": 100.0, "beta": 1.0})
		config["education_pathways"]["field_weights"] = {
			key: float(key == "computer_science")
			for key in config["education_pathways"]["field_weights"]
		}
		config["details"]["occupation_descriptions"]["technical"] = {
			key: float(key == "数据分析师")
			for key in config["details"]["occupation_descriptions"]["technical"]
		}
		config["interests"]["practical"]["count_weights"] = {"1": 1.0}
		config["interests"]["aspirational"]["count_weights"] = {"1": 1.0}
		for kind, selected in (("practical", "reading"), ("aspirational", "career_learning")):
			config["interests"][kind]["item_weights"] = {key: float(key == selected) for key in config["interests"][kind]["item_weights"]}
		spec = GenerationSpec.from_dict(config)
		profiles = generate_social_profiles(50, "fully-configured", spec=spec)
		self.assertTrue(all(profile["demographics"]["age"] == 30 for profile in profiles))
		self.assertTrue(all(profile["demographics"]["lifecycle_stage"] == "early_career" for profile in profiles))
		for field, expected in forced.items():
			section, key = field.split(".", 1)
			self.assertTrue(all(profile[section][key] == expected for profile in profiles), field)
		self.assertTrue(all(profile["interests"]["practical"][0]["id"] == "reading" for profile in profiles))
		self.assertTrue(all(profile["interests"]["aspirational"][0]["id"] == "career_learning" for profile in profiles))
		self.assertTrue(all(profile["education"]["description"] == "计算机与信息技术方向本科毕业" for profile in profiles))
		self.assertTrue(all(profile["occupation"]["description"] == "数据分析师" for profile in profiles))
		self.assertGreater(sum(profile["personality"]["openness"] for profile in profiles) / len(profiles), 0.9)
		self.assertEqual(validate_population(profiles, spec), [])

	def test_report_is_a_release_gate_and_contains_background_dimensions(self) -> None:
		profiles = generate_social_profiles(100, "report")
		data = build_report_data("report", profiles, spec=default_generation_spec())
		self.assertEqual(data["release_gate"], {"status": "passed", "hard_violation_count": 0})
		for field in ("lifecycle_stage", "gender", "education_completed", "occupation_domain", "economic_pressure"):
			self.assertIn(field, data["distributions"])
		for retired in ("information_posture", "interaction_style", "platform_archetype"):
			self.assertNotIn(retired, data["distributions"])
		self.assertEqual(set(data["personality_means"]), {"openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"})
		self.assertEqual(len(data["samples"]), 100)

	def test_source_card_has_only_validated_facts_and_grounding_contract(self) -> None:
		profile = generate_social_profiles(1, "card")[0]
		card = _source_card(profile)
		fact_ids = [fact["fact_id"] for fact in card["facts"]]
		self.assertEqual(card["schema_version"], "social_profile_source_card.v5")
		self.assertIn("demographics.gender", fact_ids)
		self.assertIn("personality.openness", fact_ids)
		self.assertTrue(any(fact_id.startswith("interests.practical.") for fact_id in fact_ids))
		self.assertNotIn("platform_behavior", fact_ids)
		self.assertNotIn("generated_name", json.dumps(card, ensure_ascii=False))
		prompt = _prompt(card)
		self.assertIn("可以加入合理且低影响的衔接性细节", prompt[0]["content"])
		self.assertIn("第一人称口吻", prompt[0]["content"])
		self.assertIn("每个 fact_id 对应的元素都必须", prompt[1]["content"])
		self.assertIn("合并或模糊类别", prompt[1]["content"])
		self.assertIn("罕见、非典型", prompt[1]["content"])
		self.assertIn("没有自己的子女但陪伴亲友或社区儿童", prompt[1]["content"])
		self.assertNotIn("generated_name", json.dumps(prompt, ensure_ascii=False))
		generated = {
			"profile_id": card["profile_id"],
			"natural_language_background": "我用第一人称表达全部画像元素。",
			"covered_fact_ids": fact_ids,
			"logic_issue_explanation": None,
		}
		normalized = _normalize_generated(card, generated)
		self.assertEqual(normalized["covered_fact_ids"], fact_ids)
		self.assertNotIn("generated_name", normalized)
		self.assertIsNone(normalized["logic_issue_explanation"])
		normalized = _normalize_generated(card, {**generated, "narrative_note": "合理扩写"})
		self.assertEqual(normalized["model_extras"], {"narrative_note": "合理扩写"})
		normalized = _normalize_generated(card, {**generated, "generated_name": "模型自发生成的姓名"})
		self.assertEqual(normalized["model_extras"], {"generated_name": "模型自发生成的姓名"})
		with_logic_issue = _normalize_generated(card, {**generated, "logic_issue_explanation": "两项事实无法同时成立。"})
		self.assertEqual(with_logic_issue["logic_issue_explanation"], "两项事实无法同时成立。")
		with self.assertRaises(ValueError):
			_normalize_generated(card, {**generated, "covered_fact_ids": fact_ids[:-1]})
		with self.assertRaises(ValueError):
			_normalize_generated(card, {**generated, "natural_language_background": "这是第三人称背景。"})

	def test_cli_writes_utf8_v2_population_envelope(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			out_path = Path(td) / "profiles.json"
			argv = list(sys.argv)
			try:
				sys.argv = ["generate_social_profiles.py", "--count", "20", "--seed", "cli-v2", "--config", str(DEFAULT_CONFIG_PATH), "--include-audit", "--output", str(out_path)]
				generate_profiles_main()
			finally:
				sys.argv = argv
			data = json.loads(out_path.read_text(encoding="utf-8"))
			self.assertEqual(data["schema_version"], SCHEMA_VERSION)
			self.assertEqual(data["generation"]["generator_version"], GENERATOR_VERSION)
			self.assertEqual(data["generation"]["population_id"], "general_chinese_social_adults")
			self.assertEqual(data["generation"]["config_sha256"], default_generation_spec().config_sha256)
			self.assertIn("resolved_config", data["generation"])
			self.assertEqual(data["generation"]["count"], 20)
			self.assertEqual(len(data["profiles"]), 20)
			self.assertIn("audit", data["profiles"][0])


if __name__ == "__main__":
	unittest.main()
