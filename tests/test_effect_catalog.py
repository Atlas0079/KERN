from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from KERN.data.loader import load_data_bundle
from KERN.effect_contract import EFFECT_SPECS
from KERN.effects import EffectCatalog, EffectResolutionError, EffectSpec, build_core_effect_catalog
from KERN.executor.executor import WorldExecutor
from KERN.models.world_state import WorldState
from tools.scenario_lint import lint_bundle


def _bind_passthrough(ws, effect_data, context):
	return dict(effect_data), dict(context or {})


def _execute_ping(executor, ws, data, context):
	return [{"type": "PingExecuted"}]


class EffectCatalogTests(unittest.TestCase):
	def test_catalogs_are_isolated(self) -> None:
		first = EffectCatalog()
		second = EffectCatalog()
		first.register(
			EffectSpec(
				effect_id="test:Ping",
				binder=_bind_passthrough,
				handler=_execute_ping,
				origin="scenario",
			)
		)

		self.assertTrue(first.contains("test:Ping"))
		self.assertFalse(second.contains("test:Ping"))

	def test_duplicate_effect_id_is_rejected(self) -> None:
		catalog = EffectCatalog()
		spec = EffectSpec(effect_id="test:Ping", binder=_bind_passthrough, handler=_execute_ping, origin="scenario")
		catalog.register(spec)

		with self.assertRaisesRegex(ValueError, "already registered: test:Ping"):
			catalog.register(spec)

	def test_frozen_catalog_rejects_registration(self) -> None:
		catalog = EffectCatalog()
		catalog.freeze()

		with self.assertRaisesRegex(RuntimeError, "catalog is frozen"):
			catalog.register(EffectSpec(effect_id="test:Ping", binder=_bind_passthrough, handler=_execute_ping))

	def test_effect_id_with_surrounding_whitespace_is_rejected(self) -> None:
		catalog = EffectCatalog()

		with self.assertRaisesRegex(ValueError, "surrounding whitespace"):
			catalog.register(EffectSpec(effect_id=" test:Ping ", binder=_bind_passthrough, handler=_execute_ping))

	def test_import_failure_exposes_effect_and_module(self) -> None:
		catalog = EffectCatalog()
		catalog.register(EffectSpec(effect_id="test:Broken", module="missing.effect.module"))

		with self.assertRaisesRegex(EffectResolutionError, "test:Broken.*binder.*missing.effect.module"):
			catalog.resolve_binder("test:Broken")

	def test_legacy_effect_specs_are_deeply_read_only(self) -> None:
		with self.assertRaises(TypeError):
			EFFECT_SPECS["InvokeBundle"]["module"] = "changed"

	def test_all_core_effects_resolve_binder_and_handler(self) -> None:
		catalog = build_core_effect_catalog()

		self.assertEqual(len(catalog.effect_ids()), 43)
		for effect_id in catalog.effect_ids():
			with self.subTest(effect_id=effect_id):
				self.assertTrue(callable(catalog.resolve_binder(effect_id)))
				self.assertTrue(callable(catalog.resolve_handler(effect_id)))

	def test_executor_uses_its_own_catalog(self) -> None:
		custom_catalog = build_core_effect_catalog()
		custom_catalog.register(
			EffectSpec(
				effect_id="test:Ping",
				binder=_bind_passthrough,
				handler=_execute_ping,
				origin="scenario",
			)
		)
		custom_executor = WorldExecutor(effect_catalog=custom_catalog)
		core_executor = WorldExecutor()

		with self.assertRaisesRegex(RuntimeError, "catalog is frozen"):
			custom_catalog.register(EffectSpec(effect_id="test:Late", binder=_bind_passthrough, handler=_execute_ping))
		self.assertEqual(custom_executor.execute(WorldState(), {"effect": "test:Ping"}, {}), [{"type": "PingExecuted"}])
		unknown = core_executor.execute(WorldState(), {"effect": "test:Ping"}, {})
		self.assertEqual(unknown[0]["code"], "UNKNOWN_EFFECT_TYPE")

	def test_executor_reports_callable_resolution_failure(self) -> None:
		catalog = build_core_effect_catalog()
		catalog.register(EffectSpec(effect_id="test:Broken", module="missing.effect.module", origin="scenario"))
		executor = WorldExecutor(effect_catalog=catalog)

		result = executor.execute(WorldState(), {"effect": "test:Broken"}, {})

		self.assertEqual(result[0]["code"], "EFFECT_BINDER_RESOLUTION_FAILED")
		self.assertIn("missing.effect.module", result[0]["message"])

	def test_lint_uses_the_callers_catalog(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		bundle = load_data_bundle(
			project_root,
			recipes_jsons=["Recipes.json", "Camping/Recipes.json"],
			reactions_jsons=["Reactions.json", "Camping/Reactions.json"],
			entities_dirs=["Entities", "Camping/Entities"],
			world_json="Camping/World.json",
			bundles_jsons=["Bundles.json"],
		)
		bundle.reactions = deepcopy(bundle.reactions)
		bundle.reactions["rules"].append(
			{"id": "custom_ping", "on_event": "AdvanceTick", "bundle": {"effects": [{"effect": "test:Ping"}]}}
		)
		catalog = build_core_effect_catalog()
		catalog.register(
			EffectSpec(
				effect_id="test:Ping",
				binder=_bind_passthrough,
				handler=_execute_ping,
				origin="scenario",
			)
		)

		result = lint_bundle(
			project_root=project_root,
			config_path=project_root / "runtime_config.camping.smoke.json",
			env={},
			bundle=bundle,
			world_json="Camping/World.json",
			recipes_jsons=["Recipes.json", "Camping/Recipes.json"],
			reactions_jsons=["Reactions.json", "Camping/Reactions.json"],
			entities_dirs=["Entities", "Camping/Entities"],
			bundles_jsons=["Bundles.json"],
			effect_catalog=catalog,
		)
		core_result = lint_bundle(
			project_root=project_root,
			config_path=project_root / "runtime_config.camping.smoke.json",
			env={},
			bundle=bundle,
			world_json="Camping/World.json",
			recipes_jsons=["Recipes.json", "Camping/Recipes.json"],
			reactions_jsons=["Reactions.json", "Camping/Reactions.json"],
			entities_dirs=["Entities", "Camping/Entities"],
			bundles_jsons=["Bundles.json"],
			effect_catalog=build_core_effect_catalog(),
		)

		self.assertFalse(any(issue.message == "unknown effect: test:Ping" for issue in result.issues))
		self.assertTrue(any(issue.message == "unknown effect: test:Ping" for issue in core_result.issues))

	def test_scenario_effect_cannot_override_core_effect(self) -> None:
		catalog = build_core_effect_catalog()

		with self.assertRaisesRegex(ValueError, "already registered: AddTag"):
			catalog.register(
				EffectSpec(
					effect_id="AddTag",
					binder=_bind_passthrough,
					handler=_execute_ping,
					origin="scenario",
				)
			)


if __name__ == "__main__":
	unittest.main()
