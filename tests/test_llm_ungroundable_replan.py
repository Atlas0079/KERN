import unittest
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.llm_action_provider import LLMActionProvider
from KERN.agent_workflow.runtime import _decision_to_outcome
from KERN.data.builder import build_world_state
from KERN.data.loader import load_data_bundle
from KERN.interaction.engine import InteractionEngine
from app import _cfg_get, _load_runtime_config


class FakeLLM:
	def __init__(self) -> None:
		self.planner_prompts: list[str] = []
		self.grounder_prompts: list[str] = []
		self.grounder_calls = 0

	def planner_text(self, messages, temperature=0.4, max_tokens=None):
		self.planner_prompts.append(str(messages[-1]["content"]))
		if len(self.planner_prompts) == 1:
			return "THOUGHT: 我需要改善补给。\nINTENT: 喝一口清水来恢复营养。"
		return "THOUGHT: 喝水无法落地，需要换成可执行动作。\nINTENT: 打开公共储物箱查看可用食物。"

	def grounder_text(self, messages, temperature=0.4, max_tokens=None):
		self.grounder_calls += 1
		self.grounder_prompts.append(str(messages[-1]["content"]))
		if self.grounder_calls == 1:
			return '{"type":"ungroundable","reason":"当前可用动词中没有 DrinkWater，CleanWater 不能直接恢复营养。"}'
		return '[{"verb":"OpenContainer","target_id":"camp_storage","parameters":{}}]'


def _load_camping_world():
	project_root = Path(__file__).resolve().parents[1]
	cfg, _cfg_path = _load_runtime_config(project_root, "runtime_config.camping.smoke.json")
	bundle = load_data_bundle(
		project_root,
		recipes_jsons=[x.strip() for x in _cfg_get(cfg, "RECIPES_JSONS", "Recipes.json").split(",") if x.strip()],
		reactions_jsons=[x.strip() for x in _cfg_get(cfg, "REACTIONS_JSONS", "Reactions.json").split(",") if x.strip()],
		entities_dirs=[x.strip() for x in _cfg_get(cfg, "ENTITIES_DIRS", "Entities").split(",") if x.strip()],
		world_json=_cfg_get(cfg, "WORLD_JSON", "World.json"),
		bundles_jsons=[x.strip() for x in _cfg_get(cfg, "BUNDLES_JSONS", "Bundles.json").split(",") if x.strip()],
	)
	result = build_world_state(bundle.world, bundle.entity_templates, bundle.recipes, named_bundles=bundle.named_bundles)
	return result.world_state, bundle


class UngroundableReplanTests(unittest.TestCase):
	def test_grounder_ungroundable_replans_and_persists_memory_note(self):
		ws, bundle = _load_camping_world()
		fake_llm = FakeLLM()
		provider = LLMActionProvider(llm=fake_llm)
		ws_view = {"full_ws_view": build_full_ws_view(ws, "camper_organizer", "test", {})}

		decision = provider.decide(ws_view, bundle.recipes, "camper_organizer", "test")

		self.assertEqual(fake_llm.grounder_calls, 2)
		self.assertIn("动作落地失败", fake_llm.planner_prompts[1])
		self.assertEqual(decision["type"], "apply_commands")
		self.assertEqual(decision["commands"][0]["verb"], "OpenContainer")
		self.assertEqual(len(decision["meta"].get("memory_notes", [])), 1)

		def execute(bundle_data, context):
			from KERN.executor.executor import WorldExecutor

			executor = WorldExecutor(entity_templates=bundle.entity_templates)
			return executor.execute_bundle(ws, bundle_data, context)

		ws.services = {"execute": execute, "interaction_engine": InteractionEngine(recipe_db=bundle.recipes)}
		outcome = _decision_to_outcome(ws, "camper_organizer", "test", decision)

		self.assertEqual(outcome["type"], "apply_operations")
		self.assertTrue(any(str(x.get("narrative", "")) for x in ws.interaction_log if str(x.get("verb", "")) == "OpenContainer"))
		mem = ws.get_entity_by_id("camper_organizer").get_component("MemoryComponent")
		self.assertTrue(any("DrinkWater" in str(x.get("content", "")) for x in mem.short_term_queue))


if __name__ == "__main__":
	unittest.main()
