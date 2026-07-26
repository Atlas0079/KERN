from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from KERN.data.loader import load_data_bundle
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

	def test_unknown_side_effect_policy_is_rejected(self) -> None:
		catalog = EffectCatalog()

		with self.assertRaisesRegex(ValueError, "side_effect"):
			catalog.register(EffectSpec(effect_id="test:Ping", binder=_bind_passthrough, handler=_execute_ping, side_effect="network_magic"))

	def test_import_failure_exposes_effect_and_module(self) -> None:
		catalog = EffectCatalog()
		catalog.register(EffectSpec(effect_id="test:Broken", module="missing.effect.module"))

		with self.assertRaisesRegex(EffectResolutionError, "test:Broken.*binder.*missing.effect.module"):
			catalog.resolve_binder("test:Broken")

	def test_all_core_effects_resolve_binder_and_handler(self) -> None:
		catalog = build_core_effect_catalog()

		for effect_id in catalog.effect_ids():
			with self.subTest(effect_id=effect_id):
				self.assertTrue(callable(catalog.resolve_binder(effect_id)))
				self.assertTrue(callable(catalog.resolve_handler(effect_id)))

	def test_lint_uses_the_callers_catalog(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		bundle = load_data_bundle(
			project_root / "Packages" / "Camping",
			recipes_jsons=["Recipes.core.json", "Recipes.json"],
			reactions_jsons=["Reactions.core.json", "Reactions.json"],
			entities_dirs=["Entities"],
			world_json="World.json",
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
			config_path=project_root / "runtime_config.camping.package.smoke.json",
			env={},
			bundle=bundle,
			world_json="World.json",
			recipes_jsons=["Recipes.core.json", "Recipes.json"],
			reactions_jsons=["Reactions.core.json", "Reactions.json"],
			entities_dirs=["Entities"],
			bundles_jsons=["Bundles.json"],
			effect_catalog=catalog,
		)
		core_result = lint_bundle(
			project_root=project_root,
			config_path=project_root / "runtime_config.camping.package.smoke.json",
			env={},
			bundle=bundle,
			world_json="World.json",
			recipes_jsons=["Recipes.core.json", "Recipes.json"],
			reactions_jsons=["Reactions.core.json", "Reactions.json"],
			entities_dirs=["Entities"],
			bundles_jsons=["Bundles.json"],
			effect_catalog=build_core_effect_catalog(),
		)

		self.assertFalse(any(issue.message == "unknown effect: test:Ping" for issue in result.issues))
		self.assertTrue(any(issue.message == "unknown effect: test:Ping" for issue in core_result.issues))

	def test_lint_rejects_irreversible_effect_before_later_effect(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		bundle = load_data_bundle(project_root / "Packages" / "Camping")
		bundle.named_bundles = {
			"invalid_external_order": {
				"effects": [
					{"effect": "test:Irreversible"},
					{"effect": "EmitEvent", "event_type": "Later", "payload": {}},
				]
			}
		}
		catalog = build_core_effect_catalog()
		catalog.register(
			EffectSpec(
				effect_id="test:Irreversible",
				binder=_bind_passthrough,
				handler=_execute_ping,
				side_effect="external_irreversible",
			)
		)

		result = lint_bundle(
			project_root=project_root,
			config_path=project_root / "runtime_config.camping.package.smoke.json",
			env={},
			bundle=bundle,
			world_json="World.json",
			recipes_jsons=["Recipes.json"],
			reactions_jsons=["Reactions.json"],
			entities_dirs=["Entities"],
			bundles_jsons=["Bundles.json"],
			effect_catalog=catalog,
		)

		self.assertTrue(any("external irreversible effect must be last" in issue.message for issue in result.issues))

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
