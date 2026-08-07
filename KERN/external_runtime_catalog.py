from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ExternalRuntimeFactory = Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass(frozen=True)
class ExternalRuntimeSpec:
	"""One Package-provided type of external runtime."""

	provider_id: str
	factory: ExternalRuntimeFactory
	origin: str = "core"
	version: str = "1"


@dataclass(frozen=True)
class ExternalRuntimeInstanceSpec:
	"""One named runtime instance selected by a runtime configuration."""

	runtime_id: str
	provider_id: str
	options: dict[str, Any]


class ExternalRuntimeCatalog:
	"""Runtime-scoped registry of external runtime factories.

	A provider ID identifies a trusted Package capability. A later runtime-config
	assembly step will select a provider and construct one or more named instances.
	"""

	def __init__(self) -> None:
		self._specs: dict[str, ExternalRuntimeSpec] = {}
		self._frozen = False

	def register(self, spec: ExternalRuntimeSpec) -> None:
		if self._frozen:
			raise RuntimeError("external runtime catalog is frozen")
		if not isinstance(spec, ExternalRuntimeSpec):
			raise TypeError("external runtime spec is required")
		provider_id = str(spec.provider_id or "").strip()
		if not provider_id:
			raise ValueError("external runtime provider id must not be blank")
		if provider_id != str(spec.provider_id):
			raise ValueError(f"external runtime provider id must not contain surrounding whitespace: {spec.provider_id!r}")
		if provider_id in self._specs:
			raise ValueError(f"external runtime provider id already registered: {provider_id}")
		if not callable(spec.factory):
			raise TypeError(f"external runtime factory must be callable: {provider_id}")
		self._specs[provider_id] = spec

	def contains(self, provider_id: str) -> bool:
		return str(provider_id or "") in self._specs

	def require(self, provider_id: str) -> ExternalRuntimeSpec:
		clean_id = str(provider_id or "")
		try:
			return self._specs[clean_id]
		except KeyError as exc:
			raise KeyError(f"external runtime provider id is not registered: {clean_id}") from exc

	def provider_ids(self) -> frozenset[str]:
		return frozenset(self._specs)

	def freeze(self) -> None:
		self._frozen = True

	def clone_mutable(self) -> "ExternalRuntimeCatalog":
		clone = ExternalRuntimeCatalog()
		for spec in self._specs.values():
			clone.register(spec)
		return clone


def parse_external_runtime_instances(raw: Any) -> tuple[ExternalRuntimeInstanceSpec, ...]:
	"""Validate the top-level ``external_runtimes`` config field."""
	if raw is None:
		return ()
	if not isinstance(raw, list):
		raise ValueError("runtime config field 'external_runtimes' must be an array")
	instances: list[ExternalRuntimeInstanceSpec] = []
	seen_ids: set[str] = set()
	for index, item in enumerate(raw):
		if not isinstance(item, dict):
			raise ValueError(f"external_runtimes[{index}] must be an object")
		if set(item).difference({"runtime_id", "provider", "options"}):
			raise ValueError(f"external_runtimes[{index}] has unknown fields")
		runtime_id = str(item.get("runtime_id", "") or "").strip()
		provider_id = str(item.get("provider", "") or "").strip()
		if not runtime_id:
			raise ValueError(f"external_runtimes[{index}].runtime_id must not be blank")
		if not provider_id:
			raise ValueError(f"external_runtimes[{index}].provider must not be blank")
		if runtime_id in seen_ids:
			raise ValueError(f"duplicate external runtime id: {runtime_id}")
		options = item.get("options", {})
		if not isinstance(options, dict):
			raise ValueError(f"external_runtimes[{index}].options must be an object")
		seen_ids.add(runtime_id)
		instances.append(ExternalRuntimeInstanceSpec(runtime_id, provider_id, dict(options)))
	return tuple(instances)
