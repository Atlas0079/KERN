from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.external_runtimes.social_profile_seed import generate_social_profiles
from tools.generate_social_profiles import main as generate_profiles_main
from tools.social_profile_report import build_report_data


class SocialProfileSeedTests(unittest.TestCase):
	def test_same_seed_generates_same_profiles(self) -> None:
		a = generate_social_profiles(count=5, seed="same")
		b = generate_social_profiles(count=5, seed="same")
		c = generate_social_profiles(count=5, seed="different")

		self.assertEqual(a, b)
		self.assertNotEqual(a, c)

	def test_profile_has_expected_fields_and_big_five_range(self) -> None:
		profile = generate_social_profiles(count=1, seed="shape")[0]

		for key in [
			"profile_id",
			"sample",
			"display",
			"summary_line",
			"llm_background_prompt",
		]:
			self.assertIn(key, profile)
		self.assertNotIn("debug", profile)
		self.assertFalse(any(str(k).endswith("_weights") for k in profile.keys()))

		sample = profile["sample"]
		for key in [
			"platform_archetype",
			"age_band",
			"education",
			"occupation_domain",
			"economic_status",
			"living_situation",
			"social_style",
			"media_style",
			"consumption_style",
			"practical_interests",
			"aspirational_interests",
			"high_cost_consumption_interests",
			"family_profile",
			"big_five",
			"specifics",
		]:
			self.assertIn(key, sample)
		family = sample["family_profile"]
		for key in ["marital_status", "children_status", "parent_support", "family_burden", "labels"]:
			self.assertIn(key, family)
		for key in ["marital_status", "children_status", "parent_support", "family_burden"]:
			self.assertTrue(str(family["labels"].get(key, "")).strip())
		specifics = sample["specifics"]
		self.assertIn("age", specifics)
		self.assertIsInstance(specifics["age"], int)
		age_ranges = {
			"18-24": (18, 24),
			"25-34": (25, 34),
			"35-44": (35, 44),
			"45-54": (45, 54),
			"55+": (55, 72),
		}
		lo, hi = age_ranges[sample["age_band"]]
		self.assertGreaterEqual(specifics["age"], lo)
		self.assertLessEqual(specifics["age"], hi)
		for key in ["education", "occupation", "living_situation", "media_habit", "consumption_habit"]:
			self.assertTrue(str(specifics.get(key, "")).strip())
		self.assertEqual(len(specifics["practical_interests"]), len(sample["practical_interests"]))
		self.assertEqual(len(specifics["aspirational_interests"]), len(sample["aspirational_interests"]))
		self.assertEqual(len(specifics["high_cost_consumption_interests"]), len(sample["high_cost_consumption_interests"]))

		self.assertGreaterEqual(len(sample["practical_interests"]), 2)
		self.assertGreaterEqual(len(sample["aspirational_interests"]), 1)
		practical_ids = {x["id"] for x in sample["practical_interests"]}
		aspirational_ids = {x["id"] for x in sample["aspirational_interests"]}
		self.assertTrue(practical_ids.isdisjoint(aspirational_ids))

		for value in sample["big_five"].values():
			self.assertGreaterEqual(value, 0.0)
			self.assertLessEqual(value, 1.0)
			self.assertEqual(value, round(value, 1))
		self.assertIn("经济状态", profile["summary_line"])
		self.assertIn("平台使用倾向", profile["llm_background_prompt"])
		self.assertIn("确定年龄", profile["llm_background_prompt"])
		self.assertIn("具体职业/身份", profile["llm_background_prompt"])
		self.assertIn("社交平台账号", profile["llm_background_prompt"])
		self.assertIn("只输出自然语言正文", profile["llm_background_prompt"])
		self.assertIn("不要使用“姓名：”", profile["llm_background_prompt"])
		self.assertIn("家庭结构", profile["llm_background_prompt"])
		self.assertIn("高成本持续消费/计划兴趣", profile["llm_background_prompt"])
		self.assertIn("职业/身份、家庭关系、兴趣爱好必须保持各自独立", profile["llm_background_prompt"])
		self.assertIn("不能被写成“路边摊小贩”", profile["llm_background_prompt"])

	def test_young_age_can_bias_economic_weights_without_hard_exclusion(self) -> None:
		profiles = generate_social_profiles(count=50, seed="young-bias", include_debug=True)
		young = next(p for p in profiles if p["sample"]["age_band"] == "18-24")
		weights = young["debug"]["weights"]["economic_status"]

		self.assertGreater(weights["tight"], weights["affluent"])
		self.assertGreater(weights["struggling"], weights["affluent"])
		self.assertGreater(weights["affluent"], 0.0)
		self.assertTrue(any(t["field"] == "economic_status" and t["source_value"] == "18-24" for t in young["debug"]["sampling_trace"]))

	def test_platform_archetype_affects_age_and_media_weights(self) -> None:
		profiles = generate_social_profiles(count=100, seed="platform-bias", include_debug=True)
		lifestyle = next(p for p in profiles if p["sample"]["platform_archetype"] == "lifestyle_discovery")
		lifestyle_age_weights = lifestyle["debug"]["weights"]["age_band"]
		lifestyle_media_weights = lifestyle["debug"]["weights"]["media_style"]

		self.assertGreater(lifestyle_age_weights["25-34"], lifestyle_age_weights["55+"])
		self.assertGreater(lifestyle_media_weights["visual_lifestyle"], lifestyle_media_weights["news_commentary"])
		self.assertTrue(any(t["field"] == "age_band" and t["source_field"] == "platform_archetype" for t in lifestyle["debug"]["sampling_trace"]))

	def test_debug_is_opt_in(self) -> None:
		plain = generate_social_profiles(count=1, seed="debug", include_debug=False)[0]
		debug = generate_social_profiles(count=1, seed="debug", include_debug=True)[0]

		self.assertNotIn("debug", plain)
		self.assertIn("debug", debug)
		self.assertEqual(plain["sample"], debug["sample"])
		self.assertIn("economic_status", debug["debug"]["weights"])
		self.assertIn("specific_occupation", debug["debug"]["weights"])
		self.assertIn("specific_living_situation", debug["debug"]["weights"])
		self.assertIn("specific_media_habit", debug["debug"]["weights"])
		self.assertIn("high_cost_consumption_interests", debug["debug"]["weights"])
		self.assertIn("family_marital_status", debug["debug"]["weights"])
		self.assertIn("family_children_status", debug["debug"]["weights"])
		self.assertIn("family_parent_support", debug["debug"]["weights"])
		self.assertIn("family_family_burden", debug["debug"]["weights"])
		self.assertTrue(debug["debug"]["sampling_trace"])

	def test_specific_occupation_weights_follow_background(self) -> None:
		profiles = generate_social_profiles(count=500, seed="specific-job-bias", include_debug=True)
		candidate = next(
			p
			for p in profiles
			if p["sample"]["occupation_domain"] == "service_retail"
			and p["sample"]["education"] in {"bachelor", "graduate"}
			and p["sample"]["economic_status"] in {"comfortable", "affluent"}
		)
		weights = candidate["debug"]["weights"]["specific_occupation"]

		self.assertGreater(weights["咖啡店店长"], weights["便利店店员"])
		self.assertGreater(weights["客服专员"], weights["餐饮服务员"])
		self.assertTrue(any(t["field"] == "specific_occupation" for t in candidate["debug"]["sampling_trace"]))

	def test_specific_values_are_condition_weighted(self) -> None:
		profiles = generate_social_profiles(count=500, seed="specific-value-bias", include_debug=True)
		older = next(p for p in profiles if p["sample"]["age_band"] == "55+" and p["sample"]["living_situation"] == "owned_home")
		living_weights = older["debug"]["weights"]["specific_living_situation"]

		self.assertGreater(living_weights["住在自有老房"], living_weights["住在贷款中的两居室"])
		self.assertTrue(any(t["field"] == "specific_living_situation" for t in older["debug"]["sampling_trace"]))

	def test_high_cost_consumption_is_separate_from_aspirational_interests(self) -> None:
		profiles = generate_social_profiles(count=500, seed="high-cost-separation", include_debug=True)
		tight = [p for p in profiles if p["sample"]["economic_status"] in {"struggling", "tight"}]
		affluent = [p for p in profiles if p["sample"]["economic_status"] == "affluent"]
		tight_high_cost = [p for p in tight if p["sample"]["high_cost_consumption_interests"]]
		affluent_high_cost = [p for p in affluent if p["sample"]["high_cost_consumption_interests"]]
		aspirational_watchers = [
			p
			for p in tight
			if any(str(x.get("id", "")).endswith("_watching") for x in p["sample"]["aspirational_interests"])
		]

		self.assertLessEqual(len(tight_high_cost), max(1, int(len(tight) * 0.08)))
		self.assertGreaterEqual(len(aspirational_watchers), 1)
		self.assertGreaterEqual(len(affluent_high_cost), 1)

	def test_family_rules_bias_implausible_combinations_down(self) -> None:
		profiles = generate_social_profiles(count=500, seed="family-bias", include_debug=True)
		young = next(p for p in profiles if p["sample"]["age_band"] == "18-24")
		young_child_weights = young["debug"]["weights"]["family_children_status"]
		student = next(p for p in profiles if p["sample"]["occupation_domain"] == "student")
		student_marital_weights = student["debug"]["weights"]["family_marital_status"]

		self.assertGreater(young_child_weights["no_children"], young_child_weights["adult_children"])
		self.assertGreater(student_marital_weights["single"], student_marital_weights["married"])
		self.assertTrue(any(t["field"] == "children_status" for t in young["debug"]["sampling_trace"]))
		self.assertTrue(any(t["field"] == "marital_status" for t in student["debug"]["sampling_trace"]))

	def test_report_includes_calibration_data(self) -> None:
		profiles = generate_social_profiles(count=100, seed="report-calibration")
		data = build_report_data("report-calibration", profiles)

		self.assertEqual(data["count"], 100)
		self.assertIn("target_comparison", data)
		self.assertIn("platform_archetype", data["target_comparison"])
		self.assertIn("flag_reason_counts", data)
		self.assertIn("high_cost_consumption_interests", data["distributions"])
		self.assertIn("family_marital_status", data["distributions"])
		self.assertIn("family_children_status", data["distributions"])
		self.assertIn("age_by_children", data["cross_tabs"])
		self.assertEqual(len(data["samples"]), 100)

	def test_cli_writes_utf8_json(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			out_path = Path(td) / "profiles.json"
			import sys

			argv = list(sys.argv)
			try:
				sys.argv = ["generate_social_profiles.py", "--count", "3", "--seed", "cli", "--output", str(out_path)]
				generate_profiles_main()
			finally:
				sys.argv = argv

			data = json.loads(out_path.read_text(encoding="utf-8"))
			self.assertEqual(data["count"], 3)
			self.assertEqual(len(data["profiles"]), 3)
			self.assertIn("自然语言角色背景", data["profiles"][0]["llm_background_prompt"])


if __name__ == "__main__":
	unittest.main()
