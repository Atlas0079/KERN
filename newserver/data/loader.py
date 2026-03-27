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


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def load_data_bundle(
	project_root: Path,
	recipes_jsons: list[str] | None = None,
	reactions_jsons: list[str] | None = None,
	entities_dirs: list[str] | None = None,
	world_json: str = "World.json",
) -> DataBundle:
	"""
	Read JSON from Data directory.
	project_root:
	- Can be "Repo/Godot Project Root" (Has Data/ under it)
	- Can also pass Data/ directory directly
	"""

	data_dir = project_root
	if (project_root / "Data").exists():
		data_dir = project_root / "Data"
	elif str(project_root.name).lower() == "data":
		data_dir = project_root
	else:
		raise FileNotFoundError(f"Data directory not found under: {project_root}")
	
	if not entities_dirs:
		entities_dirs = ["Entities"]
	if not recipes_jsons:
		recipes_jsons = ["Recipes.json"]
	if not reactions_jsons:
		reactions_jsons = ["Reactions.json"]

	world_name = str(world_json or "World.json").strip() or "World.json"
	world = load_json(data_dir / world_name)
	
	recipes: dict[str, Any] = {}
	for r_json in recipes_jsons:
		r_path = data_dir / r_json
		if r_path.exists():
			data = load_json(r_path)
			if isinstance(data, dict):
				recipes.update(data)
	
	reactions: dict[str, Any] = {"rules": []}
	for r_json in reactions_jsons:
		r_path = data_dir / r_json
		if r_path.exists():
			data = load_json(r_path)
			if isinstance(data, dict) and isinstance(data.get("rules"), list):
				reactions["rules"].extend(data["rules"])

	# Automatically load Entities/*.json and merge
	# Consistent with Godot DataManager.merge: Later loaded overwrites earlier loaded for same-name keys
	entity_templates: dict[str, Any] = {}
	for edir in entities_dirs:
		entities_dir = data_dir / edir
		if entities_dir.exists():
			for p in sorted(list(entities_dir.glob("*.json"))):
				data = load_json(p)
				if isinstance(data, dict):
					entity_templates.update(data)

	return DataBundle(
		entity_templates=entity_templates,
		recipes=recipes,
		reactions=reactions,
		world=world,
	)
