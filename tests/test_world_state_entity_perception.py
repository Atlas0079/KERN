import unittest
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.data.builder import build_world_state
from KERN.data.loader import load_data_bundle
from app import _cfg_get, _load_runtime_config


def _load_camping_smoke_world_and_bundle():
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
	ws = build_world_state(bundle.world, bundle.entity_templates, bundle.recipes, named_bundles=bundle.named_bundles).world_state
	return ws, bundle


class WorldStateEntityPerceptionTests(unittest.TestCase):
	def test_world_state_entity_is_hidden_from_passive_agent_perception(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()

		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		all_ids = {str(x.get("id", "")) for x in view.get("entities", []) if isinstance(x, dict)}
		self.assertIn("weather_01", all_ids)

		perception = build_agent_perception(view, "camper_organizer")
		visible_ids = {str(x.get("id", "")) for x in perception.get("entities", []) if isinstance(x, dict)}
		self.assertNotIn("weather_01", visible_ids)
		self.assertIn("campfire_01", visible_ids)

	def test_passive_perception_uses_base_description(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()
		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		perception = build_agent_perception(view, "camper_organizer")
		entities_by_id = {str(x.get("id", "")): x for x in perception.get("entities", []) if isinstance(x, dict)}

		self.assertEqual(entities_by_id["campfire_01"].get("description"), "营地火堆。")

	def test_observe_is_the_entity_observation_recipe(self):
		_ws, bundle = _load_camping_smoke_world_and_bundle()
		verbs = {str(x.get("verb", "")) for x in bundle.recipes.values() if isinstance(x, dict)}

		self.assertIn("Observe", verbs)
		self.assertNotIn("InspectEntity", verbs)

	def test_query_entity_recipes_recipe_and_description_field_exist(self):
		ws, bundle = _load_camping_smoke_world_and_bundle()
		verbs = {str(x.get("verb", "")) for x in bundle.recipes.values() if isinstance(x, dict)}
		self.assertIn("QueryEntityRecipes", verbs)

		wood = ws.get_entity_by_id("initial_wood_01")
		self.assertIsNotNone(wood)
		desc = wood.get_component("DescriptionComponent")
		self.assertIn("LightCampfire", desc.recipe_description)


if __name__ == "__main__":
	unittest.main()
