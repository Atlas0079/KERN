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

from .data.loader import DataBundle, LoadedDataBundle, load_data_bundle_with_sources, load_json
from .component_catalog import ComponentCatalog, build_core_component_catalog
from .effects import EffectCatalog, build_core_effect_catalog
from .external_runtime_catalog import ExternalRuntimeCatalog, ExternalRuntimeInstanceSpec, parse_external_runtime_instances
from .package_definitions import marked_component_spec, marked_effect_spec, marked_external_runtime_spec
from .package_identity import build_runtime_identity


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
	artifact_paths: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LoadedPackages:
	packages: tuple[LoadedPackage, ...]
	world_package: LoadedPackage
	data_bundle: DataBundle
	effect_catalog: EffectCatalog
	component_catalog: ComponentCatalog
	external_runtime_catalog: ExternalRuntimeCatalog
	external_runtime_instances: tuple[ExternalRuntimeInstanceSpec, ...]
	runtime_identity: dict[str, object]


def package_identity(loaded: LoadedPackages) -> dict[str, Any]:
	"""Return the identity fixed when this Package composition was loaded."""
	return dict(loaded.runtime_identity)


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
	external_runtime_catalog = ExternalRuntimeCatalog()
	extension_sources = _register_package_extensions(tuple(loaded), effect_catalog, component_catalog, external_runtime_catalog)
	effect_catalog.freeze()
	component_catalog.freeze()
	external_runtime_catalog.freeze()
	external_runtime_instances = parse_external_runtime_instances(raw.get("external_runtimes"))
	for instance in external_runtime_instances:
		if not external_runtime_catalog.contains(instance.provider_id):
			raise ValueError(f"external runtime provider is not registered: {instance.provider_id}")
	loaded_data, capability_data_sources = _load_composed_data(tuple(loaded), world_package)
	resolved_packages: list[LoadedPackage] = []
	for package in loaded:
		artifacts: list[tuple[str, str]] = [("kern-package.json", "manifest")]
		if package is world_package:
			artifacts.extend((_relative_package_path(package, path), "world_data") for path in loaded_data.source_files)
		else:
			artifacts.extend((_relative_package_path(package, path), "capability_data") for path in capability_data_sources.get(package.root, ()))
		artifacts.extend((_relative_package_path(package, path), "extension_module") for path in extension_sources.get(package.root, ()))
		resolved_packages.append(replace(package, artifact_paths=tuple(artifacts)))
	resolved_world_package = next(package for package in resolved_packages if package.world_selected)
	partial = LoadedPackages(tuple(resolved_packages), resolved_world_package, loaded_data.bundle, effect_catalog, component_catalog, external_runtime_catalog, external_runtime_instances, {})
	return replace(partial, runtime_identity=build_runtime_identity(partial))


def _register_package_extensions(
	packages: tuple[LoadedPackage, ...],
	effect_catalog: EffectCatalog,
	component_catalog: ComponentCatalog,
	external_runtime_catalog: ExternalRuntimeCatalog,
) -> dict[Path, tuple[Path, ...]]:
	loaded_modules: list[tuple[LoadedPackage, tuple[types.ModuleType, ...], tuple[types.ModuleType, ...], tuple[types.ModuleType, ...]]] = []
	sources: dict[Path, tuple[Path, ...]] = {}
	for package in packages:
		extension = str(package.manifest.extensions or "").strip()
		if not extension:
			loaded_modules.append((package, (), (), ()))
			sources[package.root] = ()
			continue
		entry = package.root / extension
		if extension != "extensions.py" or not entry.is_file():
			raise FileNotFoundError(f"package extensions entry not found: {entry}")
		prefix = _package_module_prefix(package)
		entry_module = _load_extension_entry(prefix, entry, package.root)
		component_modules = _import_declared_modules(entry_module, "COMPONENT_MODULES", prefix, package)
		effect_modules = _import_declared_modules(entry_module, "EFFECT_MODULES", prefix, package)
		external_runtime_modules = _import_declared_modules(entry_module, "EXTERNAL_RUNTIME_MODULES", prefix, package)
		loaded_modules.append((package, component_modules, effect_modules, external_runtime_modules))
		sources[package.root] = tuple(
			Path(str(module.__file__)).resolve()
			for module in (entry_module, *component_modules, *effect_modules, *external_runtime_modules)
			if str(getattr(module, "__file__", "") or "").strip()
		)
	for package, component_modules, _effect_modules, _external_runtime_modules in loaded_modules:
		for module in component_modules:
			for spec in _marked_specs(module, marked_component_spec):
				_component_id_for_package(spec.component_id, package)
				component_catalog.register(replace(spec, origin=package.manifest.package_id))
	for package, _component_modules, effect_modules, _external_runtime_modules in loaded_modules:
		for module in effect_modules:
			for spec in _marked_specs(module, marked_effect_spec):
				_component_id_for_package(spec.effect_id, package)
				effect_catalog.register(_package_effect_spec(spec, package))
	for package, _component_modules, _effect_modules, external_runtime_modules in loaded_modules:
		for module in external_runtime_modules:
			for spec in _marked_specs(module, marked_external_runtime_spec):
				_component_id_for_package(spec.provider_id, package)
				external_runtime_catalog.register(replace(spec, origin=package.manifest.package_id))
	return sources


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
	data = _parse_data(package_root, data_raw, require_world=provides_world) if data_raw is not None else None
	if provides_world and data is None:
		raise ValueError(f"world package manifest requires data: {path}")
	if not provides_world and data is not None and (data.world or data.entities):
		raise ValueError(f"capability package data may declare only recipes, reactions, and bundles: {path}")
	return PackageManifest(package_id, version, provides_world, data, extensions)


def _parse_data(package_root: Path, raw: Any, *, require_world: bool) -> PackageData:
	if not isinstance(raw, dict):
		raise ValueError(f"package data must be an object: {package_root}")
	world = _safe_data_path(package_root, raw.get("world"), "data.world", required=require_world, directory=False)
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


def _relative_package_path(package: LoadedPackage, path: Path) -> str:
	try:
		return path.resolve().relative_to(package.root.resolve()).as_posix()
	except ValueError as exc:
		raise ValueError(f"package artifact must remain within package root: {path}") from exc


def _load_world_data(world_package: LoadedPackage):
	data = world_package.manifest.data
	if data is None:
		raise ValueError("world package data is required")
	return load_data_bundle_with_sources(
		world_package.root / "Data",
		world_json=data.world,
		entities_dirs=list(data.entities),
		recipes_jsons=list(data.recipes),
		reactions_jsons=list(data.reactions),
		bundles_jsons=list(data.bundles),
	)


def _load_composed_data(
	packages: tuple[LoadedPackage, ...],
	world_package: LoadedPackage,
) -> tuple[LoadedDataBundle, dict[Path, tuple[Path, ...]]]:
	"""Compose capability recipes/reactions/bundles ahead of the selected world's data."""
	world_data = _load_world_data(world_package)
	capability_sources: dict[Path, tuple[Path, ...]] = {}
	capability_recipes: dict[str, Any] = {}
	capability_reaction_rules: list[dict[str, Any]] = []
	capability_bundles: dict[str, Any] = {}
	for package in packages:
		if package is world_package or package.manifest.data is None:
			continue
		data = package.manifest.data
		sources: list[Path] = []
		for relative in data.recipes:
			path = package.root / "Data" / relative
			value = load_json(path)
			if not isinstance(value, dict):
				raise ValueError(f"capability recipes must be an object: {path}")
			_duplicate_package_data("recipe", capability_recipes, value, package)
			capability_recipes.update(value)
			sources.append(path.resolve())
		for relative in data.reactions:
			path = package.root / "Data" / relative
			value = load_json(path)
			if not isinstance(value, dict) or not isinstance(value.get("rules"), list):
				raise ValueError(f"capability reactions must be an object with rules array: {path}")
			capability_reaction_rules.extend(dict(rule) for rule in value["rules"] if isinstance(rule, dict))
			sources.append(path.resolve())
		for relative in data.bundles:
			path = package.root / "Data" / relative
			value = load_json(path)
			if not isinstance(value, dict):
				raise ValueError(f"capability bundles must be an object: {path}")
			_duplicate_package_data("bundle", capability_bundles, value, package)
			capability_bundles.update(value)
			sources.append(path.resolve())
		capability_sources[package.root] = tuple(sources)
	_duplicate_package_data("recipe", capability_recipes, world_data.bundle.recipes, world_package)
	_duplicate_package_data("bundle", capability_bundles, world_data.bundle.named_bundles, world_package)
	return (
		LoadedDataBundle(
			bundle=DataBundle(
				entity_templates=world_data.bundle.entity_templates,
				recipes={**capability_recipes, **world_data.bundle.recipes},
				reactions={"rules": [*capability_reaction_rules, *list((world_data.bundle.reactions or {}).get("rules", []) or [])]},
				world=world_data.bundle.world,
				named_bundles={**capability_bundles, **world_data.bundle.named_bundles},
			),
			source_files=world_data.source_files,
		),
		capability_sources,
	)


def _duplicate_package_data(kind: str, existing: dict[str, Any], incoming: dict[str, Any], package: LoadedPackage) -> None:
	duplicates = sorted(set(existing).intersection(incoming))
	if duplicates:
		raise ValueError(f"duplicate {kind} ids while loading package {package.manifest.package_id}: {', '.join(duplicates)}")
