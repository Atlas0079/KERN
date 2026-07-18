from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from KERN.package import load_packages_from_config
from KERN.runtime import KernRuntime
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

	def test_legacy_config_remains_a_world_package_adapter(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		runtime = KernRuntime.from_config(
			project_root,
			"runtime_config.camping.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)

		self.assertTrue(runtime.loaded_packages.is_legacy)
		self.assertIn("camp_main", runtime.world_state.locations)

	def test_package_path_cannot_escape_project_root(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_json(root / "runtime.json", {"packages": [{"path": "../outside", "world": True}], "env": {}})

			with self.assertRaisesRegex(ValueError, "within project root"):
				KernRuntime.from_config(root, "runtime.json", configure_logging=False)

	def test_capability_package_is_resolved_without_executing_extensions(self) -> None:
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
			self.assertFalse(marker.exists())

	def test_loaded_packages_can_be_reused_for_runtime_assembly(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			_write_world_package(root)
			config_path = root / "runtime.json"
			_write_json(config_path, {"packages": [{"path": "Packages/demo", "world": True}], "env": {"CHECKPOINT_EVERY_TICK": "0"}})
			loaded = load_packages_from_config(root, config_path, env={"CHECKPOINT_EVERY_TICK": "0"})

			runtime = KernRuntime.from_loaded_packages(loaded, root, "runtime.json", configure_logging=False)

			self.assertIs(runtime.loaded_packages, loaded)
			self.assertIn("room", runtime.world_state.locations)

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


if __name__ == "__main__":
	unittest.main()
