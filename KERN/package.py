from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data.loader import DataBundle, load_data_bundle
from .component_catalog import ComponentCatalog, build_core_component_catalog
from .effects import EffectCatalog, build_core_effect_catalog


@dataclass(frozen=True)
class PackageData:
	world: str
	entities: tuple[str, ...] = ()
	recipes: tuple[str, ...] = ()
	reactions: tuple[str, ...] = ()
	bundles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageManifest:
	package_id: str
	version: str
	provides_world: bool
	data: PackageData | None = None
	extensions: str = ""


@dataclass(frozen=True)
class LoadedPackage:
	root: Path
	manifest: PackageManifest
	world_selected: bool = False


@dataclass(frozen=True)
class LoadedPackages:
	packages: tuple[LoadedPackage, ...]
	world_package: LoadedPackage
	data_bundle: DataBundle
	effect_catalog: EffectCatalog
	component_catalog: ComponentCatalog
	is_legacy: bool = False


def load_packages_from_config(
	project_root: Path,
	config_path: Path,
	*,
	env: dict[str, str],
) -> LoadedPackages:
	"""Resolve one runtime's package composition and its world data bundle."""
	root = Path(project_root).resolve()
	raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"runtime config must be an object: {config_path}")
	package_entries = raw.get("packages")
	if package_entries is None:
		return _load_legacy_package(root, env)
	if not isinstance(package_entries, list):
		raise ValueError("runtime config field 'packages' must be an array")

	loaded: list[LoadedPackage] = []
	seen_ids: set[str] = set()
	for index, entry in enumerate(package_entries):
		if not isinstance(entry, dict):
			raise ValueError(f"packages[{index}] must be an object")
		package_root = _resolve_package_path(root, config_path, entry.get("path"), index)
		manifest = _load_manifest(package_root)
		world_selected = entry.get("world", False)
		if not isinstance(world_selected, bool):
			raise ValueError(f"packages[{index}].world must be boolean")
		if manifest.package_id in seen_ids:
			raise ValueError(f"duplicate package id: {manifest.package_id}")
		seen_ids.add(manifest.package_id)
		loaded.append(LoadedPackage(package_root, manifest, world_selected))

	worlds = [item for item in loaded if item.world_selected]
	if len(worlds) != 1:
		raise ValueError("runtime config must select exactly one world package")
	world_package = worlds[0]
	if not world_package.manifest.provides_world:
		raise ValueError(f"selected world package does not provide a world: {world_package.manifest.package_id}")
	if world_package.manifest.data is None:
		raise ValueError(f"world package has no data declaration: {world_package.manifest.package_id}")
	data_bundle = _load_world_data(world_package)
	return _loaded_packages(tuple(loaded), world_package, data_bundle)


def _load_legacy_package(project_root: Path, env: dict[str, str]) -> LoadedPackages:
	data = PackageData(
		world=_cfg_get(env, "WORLD_JSON", "World.json"),
		entities=tuple(_split_csv(_cfg_get(env, "ENTITIES_DIRS", "Entities"))),
		recipes=tuple(_split_csv(_cfg_get(env, "RECIPES_JSONS", "Recipes.json"))),
		reactions=tuple(_split_csv(_cfg_get(env, "REACTIONS_JSONS", "Reactions.json"))),
		bundles=tuple(_split_csv(_cfg_get(env, "BUNDLES_JSONS", "Bundles.json"))),
	)
	manifest = PackageManifest("legacy", "legacy", True, data)
	package = LoadedPackage(project_root, manifest, True)
	return _loaded_packages((package,), package, _load_world_data(package), is_legacy=True)


def _loaded_packages(
	packages: tuple[LoadedPackage, ...],
	world_package: LoadedPackage,
	data_bundle: DataBundle,
	*,
	is_legacy: bool = False,
) -> LoadedPackages:
	effect_catalog = build_core_effect_catalog()
	component_catalog = build_core_component_catalog()
	effect_catalog.freeze()
	component_catalog.freeze()
	return LoadedPackages(
		packages=packages,
		world_package=world_package,
		data_bundle=data_bundle,
		effect_catalog=effect_catalog,
		component_catalog=component_catalog,
		is_legacy=is_legacy,
	)


def _resolve_package_path(project_root: Path, config_path: Path, value: Any, index: int) -> Path:
	raw = str(value or "").strip()
	if not raw:
		raise ValueError(f"packages[{index}].path must not be blank")
	candidate = Path(raw)
	if not candidate.is_absolute():
		candidate = config_path.parent / candidate
	resolved = candidate.resolve()
	try:
		resolved.relative_to(project_root)
	except ValueError as exc:
		raise ValueError(f"package path must remain within project root: {raw}") from exc
	if not resolved.is_dir():
		raise FileNotFoundError(f"package directory not found: {resolved}")
	return resolved


def _load_manifest(package_root: Path) -> PackageManifest:
	path = package_root / "kern-package.json"
	if not path.is_file():
		raise FileNotFoundError(f"package manifest not found: {path}")
	raw = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"package manifest must be an object: {path}")
	package_id = str(raw.get("package_id", "")).strip()
	version = str(raw.get("version", "")).strip()
	if not package_id or not version:
		raise ValueError(f"package manifest requires package_id and version: {path}")
	provides_world = raw.get("provides_world", False)
	if not isinstance(provides_world, bool):
		raise ValueError(f"package manifest provides_world must be boolean: {path}")
	extensions = str(raw.get("extensions", "") or "").strip()
	data_raw = raw.get("data")
	data = _parse_data(package_root, data_raw) if data_raw is not None else None
	if provides_world and data is None:
		raise ValueError(f"world package manifest requires data: {path}")
	if not provides_world and data is not None:
		raise ValueError(f"capability package must not declare world data: {path}")
	return PackageManifest(package_id, version, provides_world, data, extensions)


def _parse_data(package_root: Path, raw: Any) -> PackageData:
	if not isinstance(raw, dict):
		raise ValueError(f"package data must be an object: {package_root}")
	world = _safe_data_path(package_root, raw.get("world"), "data.world", required=True, directory=False)
	return PackageData(
		world=world,
		entities=_safe_data_paths(package_root, raw.get("entities", []), "data.entities", directory=True),
		recipes=_safe_data_paths(package_root, raw.get("recipes", []), "data.recipes", directory=False),
		reactions=_safe_data_paths(package_root, raw.get("reactions", []), "data.reactions", directory=False),
		bundles=_safe_data_paths(package_root, raw.get("bundles", []), "data.bundles", directory=False),
	)


def _safe_data_paths(package_root: Path, value: Any, label: str, *, directory: bool) -> tuple[str, ...]:
	if not isinstance(value, list):
		raise ValueError(f"{label} must be an array")
	return tuple(_safe_data_path(package_root, item, label, required=True, directory=directory) for item in value)


def _safe_data_path(package_root: Path, value: Any, label: str, *, required: bool, directory: bool) -> str:
	raw = str(value or "").strip()
	if not raw:
		if required:
			raise ValueError(f"{label} must not be blank")
		return ""
	data_root = (package_root / "Data").resolve()
	path = (package_root / raw).resolve()
	try:
		relative = path.relative_to(data_root)
	except ValueError as exc:
		raise ValueError(f"{label} must remain within package Data directory: {raw}") from exc
	if not path.exists():
		raise FileNotFoundError(f"{label} not found: {path}")
	if directory and not path.is_dir():
		raise ValueError(f"{label} must be a directory: {path}")
	if not directory and not path.is_file():
		raise ValueError(f"{label} must be a file: {path}")
	return relative.as_posix()


def _load_world_data(world_package: LoadedPackage) -> DataBundle:
	data = world_package.manifest.data
	if data is None:
		raise ValueError("world package data is required")
	return load_data_bundle(
		world_package.root / "Data",
		world_json=data.world,
		entities_dirs=list(data.entities),
		recipes_jsons=list(data.recipes),
		reactions_jsons=list(data.reactions),
		bundles_jsons=list(data.bundles),
	)


def _cfg_get(cfg: dict[str, str], key: str, default: str) -> str:
	return str(cfg.get(key, default) or default).strip()


def _split_csv(value: str) -> list[str]:
	return [item.strip() for item in str(value or "").split(",") if item.strip()]
