from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DataBundle:
	"""
	Pure Data Bundle: Load templates and recipes as is, for builder use.
	"""

	entity_templates: dict[str, Any]
	recipes: dict[str, Any]
	reactions: dict[str, Any]
	world: dict[str, Any]
	named_bundles: dict[str, Any] = None

	def __post_init__(self) -> None:
		if self.named_bundles is None:
			self.named_bundles = {}


@dataclass(frozen=True)
class LoadedDataBundle:
	"""A data bundle together with the JSON files that actually supplied it."""

	bundle: DataBundle
	source_files: tuple[Path, ...]


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def load_data_bundle(
	project_root: Path,
	recipes_jsons: list[str] | None = None,
	reactions_jsons: list[str] | None = None,
	entities_dirs: list[str] | None = None,
	world_json: str = "World.json",
	bundles_jsons: list[str] | None = None,
) -> DataBundle:
	return load_data_bundle_with_sources(
		project_root,
		recipes_jsons=recipes_jsons,
		reactions_jsons=reactions_jsons,
		entities_dirs=entities_dirs,
		world_json=world_json,
		bundles_jsons=bundles_jsons,
	).bundle


def load_data_bundle_with_sources(
	project_root: Path,
	recipes_jsons: list[str] | None = None,
	reactions_jsons: list[str] | None = None,
	entities_dirs: list[str] | None = None,
	world_json: str = "World.json",
	bundles_jsons: list[str] | None = None,
) -> LoadedDataBundle:
	"""
	Read JSON from a world package's Data directory.
	project_root can be the package root (which contains Data/) or Data itself.
	"""

	data_dir = project_root
	if (project_root / "Data").exists():
		data_dir = project_root / "Data"
	elif str(project_root.name).lower() == "data":
		data_dir = project_root
	else:
		raise FileNotFoundError(f"Data directory not found under: {project_root}")
	
	if entities_dirs is None:
		entities_dirs = ["Entities"]
	if recipes_jsons is None:
		recipes_jsons = ["Recipes.json"]
	if reactions_jsons is None:
		reactions_jsons = ["Reactions.json"]
	if bundles_jsons is None:
		bundles_jsons = ["Bundles.json"]

	world_name = str(world_json or "World.json").strip() or "World.json"
	source_files: list[Path] = []

	def load_source(path: Path) -> Any:
		value = load_json(path)
		resolved = path.resolve()
		if resolved not in source_files:
			source_files.append(resolved)
		return value

	world = load_source(data_dir / world_name)
	
	recipes: dict[str, Any] = {}
	for r_json in recipes_jsons:
		r_path = data_dir / r_json
		if r_path.exists():
			data = load_source(r_path)
			if isinstance(data, dict):
				recipes.update(data)
	
	reactions: dict[str, Any] = {"rules": []}
	for r_json in reactions_jsons:
		r_path = data_dir / r_json
		if r_path.exists():
			data = load_source(r_path)
			if isinstance(data, dict) and isinstance(data.get("rules"), list):
				reactions["rules"].extend(data["rules"])

	# Automatically load Entities/*.json and merge
	# Consistent with Godot DataManager.merge: Later loaded overwrites earlier loaded for same-name keys
	entity_templates: dict[str, Any] = {}
	for edir in entities_dirs:
		entities_dir = data_dir / edir
		if entities_dir.exists():
			for p in sorted(list(entities_dir.glob("*.json"))):
				data = load_source(p)
				if isinstance(data, dict):
					entity_templates.update(data)

	named_bundles: dict[str, Any] = {}
	for b_json in bundles_jsons:
		b_path = data_dir / b_json
		if b_path.exists():
			data = load_source(b_path)
			if isinstance(data, dict):
				named_bundles.update(data)

	return LoadedDataBundle(
		bundle=DataBundle(
			entity_templates=entity_templates,
			recipes=recipes,
			reactions=reactions,
			world=world,
			named_bundles=named_bundles,
		),
		source_files=tuple(source_files),
	)
