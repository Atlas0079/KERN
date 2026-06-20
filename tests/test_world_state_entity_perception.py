import unittest
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.data.builder import build_world_state
from KERN.data.loader import load_data_bundle
from KERN.models.components import CustomComponent
from default_orchestrator import _cfg_get, _load_runtime_config


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


def _load_companion_smoke_world_and_bundle():
	project_root = Path(__file__).resolve().parents[1]
	bundle = load_data_bundle(
		project_root,
		recipes_jsons=["Recipes.json", "CompanionRobot/Recipes.json"],
		reactions_jsons=["Reactions.json", "CompanionRobot/Reactions.json"],
		entities_dirs=["Entities", "CompanionRobot/Entities"],
		world_json="CompanionRobot/World.json",
		bundles_jsons=["Bundles.json"],
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
		self.assertEqual(entities_by_id["campfire_01"].get("perception_level"), "base")

	def test_condition_based_perception_uses_matched_description_level(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()
		campfire = ws.get_entity_by_id("campfire_01")
		self.assertIsNotNone(campfire)
		campfire.add_component(
			"PerceptionProfileComponent",
			CustomComponent(
				data={
					"default_level": "base",
					"default_description": "base",
					"levels": [
						{
							"id": "lit_observed",
							"condition": {
								"type": "has_status",
								"target": "target",
								"status_id": "lit",
							},
							"description": "observed",
						}
					],
				}
			),
		)

		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		perception = build_agent_perception(view, "camper_organizer")
		entities_by_id = {str(x.get("id", "")): x for x in perception.get("entities", []) if isinstance(x, dict)}
		self.assertEqual(entities_by_id["campfire_01"].get("description"), "营地火堆。")
		self.assertEqual(entities_by_id["campfire_01"].get("perception_level"), "base")

		status_comp = campfire.get_component("StatusComponent")
		status_comp.statuses.append("lit")

		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		perception = build_agent_perception(view, "camper_organizer")
		entities_by_id = {str(x.get("id", "")): x for x in perception.get("entities", []) if isinstance(x, dict)}
		self.assertEqual(
			entities_by_id["campfire_01"].get("description"),
			"营地火堆。点燃后可用于取暖和烹饪；熄灭时不能发挥这些作用，需要燃料重新点火。",
		)
		self.assertEqual(entities_by_id["campfire_01"].get("perception_level"), "lit_observed")

	def test_facility_templates_are_not_portable_items(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()
		for entity_id in ("camp_storage", "campfire_01", "shelter_01"):
			ent = ws.get_entity_by_id(entity_id)
			self.assertIsNotNone(ent)
			self.assertTrue(ent.has_tag("facility"))
			self.assertFalse(ent.has_tag("item"))

	def test_dark_location_blocks_passive_entity_perception(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()
		loc = ws.get_location_by_id("camp_main")
		self.assertIsNotNone(loc)
		loc.light_level = 0

		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		perception = build_agent_perception(view, "camper_organizer")

		self.assertEqual(perception.get("entities"), [])
		self.assertTrue(perception.get("perception_blocked_by_darkness"))
		self.assertEqual(perception.get("location", {}).get("light_level"), 0)
		self.assertGreater(len(perception.get("reachable_locations", [])), 0)

	def test_agent_perception_includes_own_vitals(self):
		ws, _bundle = _load_camping_smoke_world_and_bundle()
		view = build_full_ws_view(ws, "camper_organizer", "test", {})
		perception = build_agent_perception(view, "camper_organizer")

		self.assertEqual(
			perception.get("vitals"),
			{
				"hp": 100.0,
				"max_hp": 100.0,
				"energy": 70.0,
				"max_energy": 100.0,
				"nutrition": 70.0,
				"max_nutrition": 100.0,
				"stress": 0.0,
				"max_stress": 100.0,
			},
		)

	def test_kindergarten_child_vitals_include_stress_value(self):
		ws, _bundle = _load_companion_smoke_world_and_bundle()
		view = build_full_ws_view(ws, "child_doudou", "test", {})
		perception = build_agent_perception(view, "child_doudou")

		self.assertEqual(
			perception.get("vitals"),
			{
				"hp": 100.0,
				"max_hp": 100.0,
				"energy": 72.0,
				"max_energy": 100.0,
				"nutrition": 100.0,
				"max_nutrition": 100.0,
				"stress": 18.0,
				"max_stress": 100.0,
			},
		)

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
