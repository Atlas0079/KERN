from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from .package import LoadedPackages


IDENTITY_SCHEMA_VERSION = "package_identity.v2"


def build_runtime_identity(loaded: "LoadedPackages") -> dict[str, object]:
	"""Build the immutable checkpoint identity for one already-loaded runtime."""
	packages: list[dict[str, object]] = []
	for package in loaded.packages:
		digest = hashlib.sha256()
		artifacts = sorted(package.artifact_paths, key=lambda item: (item[0], item[1]))
		seen: set[str] = set()
		for relative_path, role in artifacts:
			if relative_path in seen:
				raise ValueError(f"duplicate package artifact: {package.manifest.package_id}:{relative_path}")
			seen.add(relative_path)
			path = (package.root / relative_path).resolve()
			try:
				path.relative_to(package.root.resolve())
			except ValueError as exc:
				raise ValueError(f"package artifact escapes package root: {package.manifest.package_id}:{relative_path}") from exc
			if not path.is_file():
				raise FileNotFoundError(f"package artifact not found: {path}")
			digest.update(relative_path.encode("utf-8"))
			digest.update(b"\0")
			digest.update(role.encode("utf-8"))
			digest.update(b"\0")
			digest.update(path.read_bytes())
		packages.append(
			{
				"package_id": package.manifest.package_id,
				"version": package.manifest.version,
				"runtime_content_hash": digest.hexdigest(),
				"world": bool(package.world_selected),
			}
		)
	return {
		"schema_version": IDENTITY_SCHEMA_VERSION,
		"packages": packages,
		"effect_ids": sorted(loaded.effect_catalog.effect_ids()),
		"component_ids": sorted(loaded.component_catalog.component_ids()),
		"external_runtime_provider_ids": sorted(loaded.external_runtime_catalog.provider_ids()),
		"external_runtime_instances": [
			{
				"runtime_id": instance.runtime_id,
				"provider": instance.provider_id,
				"options": dict(instance.options),
			}
			for instance in loaded.external_runtime_instances
		],
	}


def verify_checkpoint_identity(meta: dict[str, Any], loaded: "LoadedPackages") -> None:
	"""Reject a checkpoint when its versioned Package identity differs."""
	stored = meta.get("package_identity")
	if stored is None:
		raise ValueError("checkpoint package_identity.v2 metadata is required")
	if not isinstance(stored, dict) or stored.get("schema_version") != IDENTITY_SCHEMA_VERSION:
		raise ValueError("checkpoint package identity schema is unsupported")
	if stored != loaded.runtime_identity:
		raise ValueError("checkpoint package identity does not match the selected package composition")
