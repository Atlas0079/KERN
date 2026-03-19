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


def load_data_bundle(project_root: Path) -> DataBundle:
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
	entities_dir = data_dir / "Entities"

	world = load_json(data_dir / "World.json")
	recipes = load_json(data_dir / "Recipes.json")
	reactions_path = data_dir / "Reactions.json"
	reactions = load_json(reactions_path) if reactions_path.exists() else {"rules": []}

	# Automatically load Entities/*.json and merge
	# Consistent with Godot DataManager.merge: Later loaded overwrites earlier loaded for same-name keys
	entity_templates: dict[str, Any] = {}
	for p in sorted(list(entities_dir.glob("*.json"))):
		data = load_json(p)
		if isinstance(data, dict):
			entity_templates.update(data)

	return DataBundle(
		entity_templates=entity_templates,
		recipes=recipes,
		reactions=reactions if isinstance(reactions, dict) else {"rules": []},
		world=world,
	)
