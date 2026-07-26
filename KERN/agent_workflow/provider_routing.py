from __future__ import annotations

from typing import Any


def resolve_workflow_provider(
	services: dict[str, Any] | None,
	controller: Any | None,
	requested_provider_id: str = "",
) -> Any | None:
	"""Resolve a workflow by explicit request, controller preference, then default."""
	service_map = dict(services or {})
	registry = service_map.get("workflow_registry")
	if registry is not None and callable(getattr(registry, "resolve", None)):
		return registry.resolve(controller, requested_provider_id)
	providers = service_map.get("action_providers", {}) or {}
	if not isinstance(providers, dict):
		providers = {}
	requested_id = str(requested_provider_id or "").strip()
	controller_id = str(getattr(controller, "provider_id", "") or "").strip()
	for provider_id in (requested_id, controller_id):
		if provider_id:
			return providers[provider_id]
	return service_map.get("default_action_provider")
