from __future__ import annotations

import json
import hashlib
import importlib
import importlib.util
import sys
import types
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data.loader import DataBundle, load_data_bundle
from .component_catalog import ComponentCatalog, build_core_component_catalog
from .effects import EffectCatalog, build_core_effect_catalog
from .package_definitions import marked_component_spec, marked_effect_spec


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


def package_identity(loaded: LoadedPackages) -> dict[str, Any]:
	packages: list[dict[str, Any]] = []
	for package in loaded.packages:
		digest = hashlib.sha256()
		for path in sorted(path for path in package.root.rglob("*") if path.is_file() and path.suffix in {".json", ".py"}):
			digest.update(path.relative_to(package.root).as_posix().encode("utf-8"))
			digest.update(b"\0")
			digest.update(path.read_bytes())
		packages.append({"package_id": package.manifest.package_id, "version": package.manifest.version, "content_hash": digest.hexdigest(), "world": bool(package.world_selected)})
	return {"packages": packages, "effect_ids": sorted(loaded.effect_catalog.effect_ids()), "component_ids": sorted(loaded.component_catalog.component_ids())}


def package_selection_identity(project_root: Path, config_path: Path) -> tuple[tuple[str, bool], ...]:
	"""Read only the package selection from config without importing package code."""
	root = Path(project_root).resolve()
	raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"runtime config must be an object: {config_path}")
	entries = raw.get("packages")
	if not isinstance(entries, list):
		raise ValueError("runtime config requires a top-level 'packages' array")
	selection: list[tuple[str, bool]] = []
	for index, entry in enumerate(entries):
		if not isinstance(entry, dict):
			raise ValueError(f"packages[{index}] must be an object")
		selected_world = entry.get("world", False)
		if not isinstance(selected_world, bool):
			raise ValueError(f"packages[{index}].world must be boolean")
		path = _resolve_package_path(root, Path(config_path), entry.get("path"), index)
		selection.append((str(path), selected_world))
	return tuple(selection)


def loaded_package_selection_identity(loaded: LoadedPackages) -> tuple[tuple[str, bool], ...]:
	return tuple((str(item.root.resolve()), bool(item.world_selected)) for item in loaded.packages)


def load_packages_from_config(
	project_root: Path,
	config_path: Path,
) -> LoadedPackages:
	"""Resolve one runtime's package composition and its world data bundle."""
	root = Path(project_root).resolve()
	raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"runtime config must be an object: {config_path}")
	package_entries = raw.get("packages")
	if package_entries is None:
		raise ValueError("runtime config requires a top-level 'packages' array")
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
	effect_catalog = build_core_effect_catalog()
	component_catalog = build_core_component_catalog()
	_register_package_extensions(tuple(loaded), effect_catalog, component_catalog)
	effect_catalog.freeze()
	component_catalog.freeze()
	data_bundle = _load_world_data(world_package)
	return LoadedPackages(tuple(loaded), world_package, data_bundle, effect_catalog, component_catalog)


def _register_package_extensions(
	packages: tuple[LoadedPackage, ...],
	effect_catalog: EffectCatalog,
	component_catalog: ComponentCatalog,
) -> None:
	loaded_modules: list[tuple[LoadedPackage, tuple[types.ModuleType, ...], tuple[types.ModuleType, ...]]] = []
	for package in packages:
		extension = str(package.manifest.extensions or "").strip()
		if not extension:
			loaded_modules.append((package, (), ()))
			continue
		entry = package.root / extension
		if extension != "extensions.py" or not entry.is_file():
			raise FileNotFoundError(f"package extensions entry not found: {entry}")
		prefix = _package_module_prefix(package)
		entry_module = _load_extension_entry(prefix, entry, package.root)
		component_modules = _import_declared_modules(entry_module, "COMPONENT_MODULES", prefix, package)
		effect_modules = _import_declared_modules(entry_module, "EFFECT_MODULES", prefix, package)
		loaded_modules.append((package, component_modules, effect_modules))
	for package, component_modules, _effect_modules in loaded_modules:
		for module in component_modules:
			for spec in _marked_specs(module, marked_component_spec):
				_component_id_for_package(spec.component_id, package)
				component_catalog.register(replace(spec, origin=package.manifest.package_id))
	for package, _component_modules, effect_modules in loaded_modules:
		for module in effect_modules:
			for spec in _marked_specs(module, marked_effect_spec):
				_component_id_for_package(spec.effect_id, package)
				effect_catalog.register(_package_effect_spec(spec, package))


def _package_module_prefix(package: LoadedPackage) -> str:
	digest = hashlib.sha256(str(package.root).encode("utf-8")).hexdigest()[:12]
	return f"_kern_package_{digest}"


def _load_extension_entry(prefix: str, entry: Path, package_root: Path) -> types.ModuleType:
	root_module = types.ModuleType(prefix)
	root_module.__path__ = [str(package_root)]
	sys.modules[prefix] = root_module
	module_name = f"{prefix}.extensions"
	spec = importlib.util.spec_from_file_location(module_name, entry)
	if spec is None or spec.loader is None:
		raise ImportError(f"unable to load package extensions: {entry}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	try:
		spec.loader.exec_module(module)
	except Exception as exc:
		raise ImportError(f"package extensions import failed: {entry}: {exc}") from exc
	return module


def _import_declared_modules(entry: types.ModuleType, attribute: str, prefix: str, package: LoadedPackage) -> tuple[types.ModuleType, ...]:
	declared = getattr(entry, attribute, ())
	if not isinstance(declared, tuple) or not all(isinstance(item, str) for item in declared):
		raise ValueError(f"{package.manifest.package_id} extensions.{attribute} must be a tuple of module paths")
	modules: list[types.ModuleType] = []
	for relative in declared:
		if not relative or any(not part.isidentifier() for part in relative.split(".")):
			raise ValueError(f"invalid package module path: {relative!r}")
		try:
			modules.append(importlib.import_module(f"{prefix}.{relative}"))
		except Exception as exc:
			raise ImportError(f"package module import failed: {package.manifest.package_id}:{relative}: {exc}") from exc
	return tuple(modules)


def _marked_specs(module: types.ModuleType, marker) -> tuple[Any, ...]:
	seen: set[int] = set()
	specs: list[Any] = []
	for value in vars(module).values():
		spec = marker(value)
		if spec is not None and id(spec) not in seen:
			seen.add(id(spec))
			specs.append(spec)
	return tuple(specs)


def _component_id_for_package(identifier: str, package: LoadedPackage) -> None:
	prefix = f"{package.manifest.package_id}:"
	if not str(identifier or "").startswith(prefix):
		raise ValueError(f"package definition id must use namespace {prefix}: {identifier}")


def _package_effect_spec(spec: Any, package: LoadedPackage):
	module = str(getattr(spec, "module", "") or "").strip()
	if module:
		if any(not part.isidentifier() for part in module.split(".")):
			raise ValueError(f"invalid package effect module path: {module!r}")
		module = f"{_package_module_prefix(package)}.{module}"
	return replace(spec, module=module, origin=package.manifest.package_id)


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
