from __future__ import annotations

from typing import Any


def resolve_workflow_provider(
	services: dict[str, Any] | None,
	controller: Any | None,
	requested_provider_id: str = "",
) -> Any | None:
	"""Resolve a workflow by explicit request, controller preference, then default."""
	service_map = dict(services or {})
	providers = service_map.get("action_providers", {}) or {}
	if not isinstance(providers, dict):
		providers = {}
	for provider_id in (
		str(requested_provider_id or "").strip(),
		str(getattr(controller, "provider_id", "") or "").strip(),
	):
		if provider_id and provider_id in providers:
			return providers[provider_id]
	return service_map.get("default_action_provider")
