from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.package import load_packages_from_config, package_identity
from KERN.package_identity import verify_checkpoint_identity
from KERN.data.checkpoint import load_checkpoint_meta
from KERN.runtime import KernRuntime
from KERN.data.archive import ArchiveRecorder
from KERN.data.checkpoint import restore_world_state_from_checkpoint
from tools.scenario_lint import lint_config


def _write_json(path: Path, value: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(value), encoding="utf-8")


def _write_world_package(root: Path, *, package_id: str = "demo") -> Path:
	package_root = root / "Packages" / package_id
	_write_json(
		package_root / "kern-package.json",
		{
			"package_id": package_id,
			"version": "1.0.0",
			"provides_world": True,
			"data": {
				"world": "Data/World.json",
				"entities": ["Data/Entities"],
				"recipes": ["Data/Recipes.json"],
				"reactions": ["Data/Reactions.json"],
				"bundles": ["Data/Bundles.json"],
			},
		},
	)
	_write_json(
		package_root / "Data" / "World.json",
		{"locations": [{"location_id": "room", "location_name": "Room", "description": "", "entities": []}], "entities": []},
	)
	_write_json(package_root / "Data" / "Recipes.json", {})
	_write_json(package_root / "Data" / "Reactions.json", {"rules": []})
	_write_json(package_root / "Data" / "Bundles.json", {})
	(package_root / "Data" / "Entities").mkdir(parents=True, exist_ok=True)
	_write_json(package_root / "Data" / "Entities" / "entity.json", {"agent": {"name": "Agent", "components": {}}})
	return package_root


class PackageLoadingTests(unittest.TestCase):
	def test_capability_recipes_reactions_and_bundles_are_composed_before_world_data(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			capability = root / "Packages" / "navigation"
			_write_json(
				capability / "kern-package.json",
				{
					"package_id": "navigation",
					"version": "1.0.0",
					"provides_world": False,
					"data": {
						"recipes": ["Data/Recipes.json"],
						"reactions": ["Data/Reactions.json"],
						"bundles": ["Data/Bundles.json"],
					},
				},
			)
			_write_json(capability / "Data" / "Recipes.json", {"ExitNavigation": {"verb": "ExitNavigation", "is_meta": True}})
			_write_json(
				capability / "Data" / "Reactions.json",
				{"rules": [{"id": "navigation_reaction", "on_event": "NavigationEvent", "bundle": {"effects": []}}]},
			)
			_write_json(capability / "Data" / "Bundles.json", {"navigation_defaults": {"effects": []}})
			_write_json(root / "runtime.json", {"packages": [{"path": "Packages/navigation"}, {"path": "Packages/demo", "world": True}], "env": {}})

			loaded = load_packages_from_config(root, root / "runtime.json")

			self.assertIn("ExitNavigation", loaded.data_bundle.recipes)
			self.assertEqual([rule["id"] for rule in loaded.data_bundle.reactions["rules"]], ["navigation_reaction"])
			self.assertIn("navigation_defaults", loaded.data_bundle.named_bundles)
			self.assertIn(("Data/Reactions.json", "capability_data"), loaded.packages[0].artifact_paths)
			capability_identity = next(item for item in package_identity(loaded)["packages"] if item["package_id"] == "navigation")
			self.assertTrue(capability_identity["runtime_content_hash"])

	def test_camping_world_package_replaces_legacy_smoke_config(self) -> None:
		project_root = Path(__file__).resolve().parents[2]

		runtime = KernRuntime.from_config(
			project_root,
			"runtime_config.camping.package.smoke.json",
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)
		lint = lint_config(project_root, "runtime_config.camping.package.smoke.json")

		self.assertEqual(runtime.loaded_packages.world_package.manifest.package_id, "camping")
		self.assertIn("camp_main", runtime.world_state.locations)
		self.assertFalse([issue for issue in lint.issues if issue.severity == "ERROR"])
		self.assertEqual(package_identity(runtime.loaded_packages)["packages"][0]["package_id"], "camping")

	def test_social_propagation_empty_runtime_smoke_config(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		runtime = KernRuntime.from_config(
			project_root,
			"runtime_config.social_propagation.empty.smoke.json",
			configure_logging=False,
		)

		adapter = runtime.external_runtimes["social_platform"]
		self.assertTrue(adapter.started)
		self.assertEqual(adapter.invoke("health_check", {}, {})[0]["type"], "ExternalRuntimeHealthy")
		runtime.close()
		self.assertTrue(adapter.closed)

	def test_runtime_and_lint_load_a_selected_world_package(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			_write_json(
				root / "runtime.json",
				{"packages": [{"path": "Packages/demo", "world": True}], "env": {"USE_LLM": "0", "CHECKPOINT_EVERY_TICK": "0"}},
			)

			runtime = KernRuntime.from_config(root, "runtime.json", configure_logging=False)
			lint = lint_config(root, "runtime.json")

			self.assertIn("room", runtime.world_state.locations)
			self.assertEqual(runtime.loaded_packages.world_package.manifest.package_id, "demo")
			self.assertFalse([issue for issue in lint.issues if issue.severity == "ERROR"])

	def test_package_path_cannot_escape_project_root(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_json(root / "runtime.json", {"packages": [{"path": "../outside", "world": True}], "env": {}})

			with self.assertRaisesRegex(ValueError, "within project root"):
				KernRuntime.from_config(root, "runtime.json", configure_logging=False)

	def test_selected_capability_executes_its_declared_extensions_entry(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			capability_root = root / "Packages" / "weather"
			_write_json(
				capability_root / "kern-package.json",
				{"package_id": "weather", "version": "1.0.0", "provides_world": False, "extensions": "extensions.py"},
			)
			marker = root / "extensions-ran"
			(capability_root / "extensions.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8")
			_write_json(
				root / "runtime.json",
				{"packages": [{"path": "Packages/weather"}, {"path": "Packages/demo", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}},
			)

			runtime = KernRuntime.from_config(root, "runtime.json", configure_logging=False)

			self.assertEqual([item.manifest.package_id for item in runtime.loaded_packages.packages], ["weather", "demo"])
			self.assertTrue(marker.exists())

	def test_selected_package_registers_declared_external_runtime_factories(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			capability_root = root / "Packages" / "social"
			_write_json(
				capability_root / "kern-package.json",
				{"package_id": "social", "version": "1.0.0", "provides_world": False, "extensions": "extensions.py"},
			)
			(capability_root / "runtimes").mkdir(parents=True)
			(capability_root / "extensions.py").write_text('EXTERNAL_RUNTIME_MODULES = ("runtimes.sqlite",)\n', encoding="utf-8")
			(capability_root / "runtimes" / "sqlite.py").write_text(
				"from KERN.external_runtime_catalog import ExternalRuntimeSpec\n"
				"from KERN.package_definitions import package_external_runtime\n"
				"@package_external_runtime(ExternalRuntimeSpec(provider_id='social:sqlite', factory=lambda context, options: {'context': context, 'options': options}))\n"
				"def sqlite_runtime():\n"
				"    pass\n",
				encoding="utf-8",
			)
			_write_json(root / "runtime.json", {"packages": [{"path": "Packages/social"}, {"path": "Packages/demo", "world": True}], "env": {}})

			loaded = load_packages_from_config(root, root / "runtime.json")

			self.assertEqual(loaded.external_runtime_catalog.provider_ids(), frozenset({"social:sqlite"}))
			self.assertIn("social:sqlite", package_identity(loaded)["external_runtime_provider_ids"])
			social_package = next(item for item in loaded.packages if item.manifest.package_id == "social")
			self.assertIn(("runtimes/sqlite.py", "extension_module"), social_package.artifact_paths)

	def test_config_constructs_a_named_external_runtime_from_a_package_provider(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			capability_root = root / "Packages" / "social"
			_write_json(
				capability_root / "kern-package.json",
				{"package_id": "social", "version": "1.0.0", "provides_world": False, "extensions": "extensions.py"},
			)
			(capability_root / "runtimes").mkdir(parents=True)
			(capability_root / "extensions.py").write_text('EXTERNAL_RUNTIME_MODULES = ("runtimes.empty",)\n', encoding="utf-8")
			(capability_root / "runtimes" / "empty.py").write_text(
				"from KERN.external_runtime_catalog import ExternalRuntimeSpec\n"
				"from KERN.package_definitions import package_external_runtime\n"
				"class EmptyRuntime:\n"
				"    def __init__(self, context, options):\n"
				"        self.context = context\n"
				"        self.options = options\n"
				"        self.started = []\n"
				"    def start(self, context):\n"
				"        self.started.append(context)\n"
				"        return [{'type': 'EmptyRuntimeStarted'}]\n"
				"    def close(self, context):\n"
				"        self.closed = context\n"
				"        return [{'type': 'EmptyRuntimeClosed'}]\n"
				"@package_external_runtime(ExternalRuntimeSpec(provider_id='social:empty', factory=lambda context, options: EmptyRuntime(context, options)))\n"
				"def empty_runtime():\n"
				"    pass\n",
				encoding="utf-8",
			)
			_write_json(
				root / "runtime.json",
				{
					"packages": [{"path": "Packages/social"}, {"path": "Packages/demo", "world": True}],
					"external_runtimes": [{"runtime_id": "social_platform", "provider": "social:empty", "options": {"mode": "test"}}],
					"env": {"CHECKPOINT_EVERY_TICK": "0"},
				},
			)

			runtime = KernRuntime.from_config(root, "runtime.json", configure_logging=False)
			adapter = runtime.external_runtimes["social_platform"]

			self.assertEqual(adapter.options, {"mode": "test"})
			self.assertEqual(adapter.context["runtime_id"], "social_platform")
			self.assertEqual(adapter.started[0]["runtime_id"], "social_platform")
			self.assertIn("external_runtime_instances", package_identity(runtime.loaded_packages))
			runtime.close()
			self.assertEqual(adapter.closed["runtime_id"], "social_platform")

	def test_loaded_packages_can_be_reused_for_runtime_assembly(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			config_path = root / "runtime.json"
			_write_json(config_path, {"packages": [{"path": "Packages/demo", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}})
			loaded = load_packages_from_config(root, config_path)

			runtime = KernRuntime.from_loaded_packages(loaded, root, "runtime.json", configure_logging=False)

			self.assertIs(runtime.loaded_packages, loaded)
			self.assertIn("room", runtime.world_state.locations)

	def test_loaded_packages_must_match_the_config_package_selection(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root, package_id="one")
			_write_world_package(root, package_id="two")
			_write_json(root / "one.json", {"packages": [{"path": "Packages/one", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}})
			_write_json(root / "two.json", {"packages": [{"path": "Packages/two", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}})
			loaded = load_packages_from_config(root, root / "one.json")

			with self.assertRaisesRegex(ValueError, "package selection"):
				KernRuntime.from_loaded_packages(loaded, root, "two.json", configure_logging=False)

	def test_world_selection_must_be_boolean(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			_write_json(root / "runtime.json", {"packages": [{"path": "Packages/demo", "world": "false"}], "env": {}})

			with self.assertRaisesRegex(ValueError, "world must be boolean"):
				KernRuntime.from_config(root, "runtime.json", configure_logging=False)

	def test_package_composition_rejects_invalid_world_and_manifest_contracts(self) -> None:
		with self.subTest("zero world packages"):
			with tempfile.TemporaryDirectory() as temp_dir:
				root = Path(temp_dir)
				_write_world_package(root)
				_write_json(root / "runtime.json", {"packages": [{"path": "Packages/demo"}], "env": {}})
				with self.assertRaisesRegex(ValueError, "exactly one"):
					KernRuntime.from_config(root, "runtime.json", configure_logging=False)

		with self.subTest("duplicate package id"):
			with tempfile.TemporaryDirectory() as temp_dir:
				root = Path(temp_dir)
				_write_world_package(root, package_id="one")
				_write_world_package(root, package_id="two")
				_write_json(root / "Packages" / "two" / "kern-package.json", {"package_id": "one", "version": "1.0.0", "provides_world": True, "data": {"world": "Data/World.json"}})
				_write_json(root / "runtime.json", {"packages": [{"path": "Packages/one", "world": True}, {"path": "Packages/two"}], "env": {}})
				with self.assertRaisesRegex(ValueError, "duplicate package id"):
					KernRuntime.from_config(root, "runtime.json", configure_logging=False)

		with self.subTest("selected capability package"):
			with tempfile.TemporaryDirectory() as temp_dir:
				root = Path(temp_dir)
				capability = root / "Packages" / "weather"
				_write_json(capability / "kern-package.json", {"package_id": "weather", "version": "1.0.0", "provides_world": False})
				_write_json(root / "runtime.json", {"packages": [{"path": "Packages/weather", "world": True}], "env": {}})
				with self.assertRaisesRegex(ValueError, "does not provide"):
					KernRuntime.from_config(root, "runtime.json", configure_logging=False)

		with self.subTest("manifest data contract"):
			with tempfile.TemporaryDirectory() as temp_dir:
				root = Path(temp_dir)
				_write_json(root / "Packages" / "world" / "kern-package.json", {"package_id": "world", "version": "1.0.0", "provides_world": True})
				_write_json(root / "runtime.json", {"packages": [{"path": "Packages/world", "world": True}], "env": {}})
				with self.assertRaisesRegex(ValueError, "requires data"):
					KernRuntime.from_config(root, "runtime.json", configure_logging=False)

		with self.subTest("manifest resource kinds"):
			with tempfile.TemporaryDirectory() as temp_dir:
				root = Path(temp_dir)
				_write_world_package(root)
				_write_json(
					root / "Packages" / "demo" / "kern-package.json",
					{"package_id": "demo", "version": "1.0.0", "provides_world": True, "data": {"world": "Data/World.json", "entities": ["Data/Recipes.json"]}},
				)
				_write_json(root / "runtime.json", {"packages": [{"path": "Packages/demo", "world": True}], "env": {}})
				with self.assertRaisesRegex(ValueError, "must be a directory"):
					KernRuntime.from_config(root, "runtime.json", configure_logging=False)

	def test_exactly_one_world_package_is_required(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root, package_id="one")
			_write_world_package(root, package_id="two")
			_write_json(
				root / "runtime.json",
				{"packages": [{"path": "Packages/one", "world": True}, {"path": "Packages/two", "world": True}], "env": {}},
			)

			with self.assertRaisesRegex(ValueError, "exactly one"):
				KernRuntime.from_config(root, "runtime.json", configure_logging=False)

	def test_runtime_identity_hashes_only_loaded_artifacts_and_validates_restore(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			package_root = _write_world_package(root)
			_write_json(root / "runtime.json", {"packages": [{"path": "Packages/demo", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}})
			(package_root / "unused.py").write_text("VALUE = 1\n", encoding="utf-8")
			_write_json(package_root / "Data" / "unused.json", {"unused": True})

			first = load_packages_from_config(root, root / "runtime.json")
			first_identity = package_identity(first)
			(package_root / "unused.py").write_text("VALUE = 2\n", encoding="utf-8")
			_write_json(package_root / "Data" / "unused.json", {"unused": "changed"})
			second = load_packages_from_config(root, root / "runtime.json")
			self.assertEqual(package_identity(second), first_identity)

			archive_dir = root / "archive"
			ArchiveRecorder(
				archive_dir=str(archive_dir),
				run_id="identity",
				component_catalog=first.component_catalog,
				package_identity={"package_identity": first_identity},
			).record_tick(KernRuntime.from_loaded_packages(first, root, "runtime.json", configure_logging=False).world_state)
			meta = load_checkpoint_meta(archive_dir / "snapshots" / "snapshot_000000.json.gz")
			verify_checkpoint_identity(meta, second)

			_write_json(package_root / "Data" / "World.json", {"locations": [{"location_id": "changed", "location_name": "Changed", "description": "", "entities": []}], "entities": []})
			changed = load_packages_from_config(root, root / "runtime.json")
			with self.assertRaisesRegex(ValueError, "package identity"):
				verify_checkpoint_identity(meta, changed)
			with self.assertRaisesRegex(ValueError, "package_identity.v2 metadata is required"):
				verify_checkpoint_identity({}, second)


if __name__ == "__main__":
	unittest.main()
