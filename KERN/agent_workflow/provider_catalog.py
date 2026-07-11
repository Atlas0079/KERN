from __future__ import annotations

import json
from typing import Any

from .llm_action_provider import build_default_llm_provider


def build_workflow_provider_catalog(config: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
	"""Build the default workflow plus named LLM workflows from runtime config.

	`LLM_PROFILES_JSON` is a JSON object keyed by stable, scenario-facing profile
	IDs.  Each value uses the existing LLM configuration keys (for example
	`LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_PLANNER_MODEL`) and overrides the
	base runtime configuration for that profile only.
	"""
	base_config = dict(config or {})
	default_provider = build_default_llm_provider(base_config)
	raw = str(base_config.get("LLM_PROFILES_JSON", "") or "").strip()
	if not raw:
		return default_provider, {}
	try:
		profiles_raw = json.loads(raw)
	except json.JSONDecodeError as exc:
		raise ValueError(f"LLM_PROFILES_JSON must be valid JSON: {exc}") from exc
	if not isinstance(profiles_raw, dict):
		raise ValueError("LLM_PROFILES_JSON must be a JSON object")
	named: dict[str, Any] = {}
	for profile_id_raw, overrides_raw in profiles_raw.items():
		profile_id = str(profile_id_raw or "").strip()
		if not profile_id:
			raise ValueError("LLM_PROFILES_JSON contains a blank profile id")
		if not isinstance(overrides_raw, dict):
			raise ValueError(f"LLM profile {profile_id!r} must be an object")
		profile_config = dict(base_config)
		for key, value in dict(overrides_raw).items():
			if value is None:
				continue
			profile_config[str(key)] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
		named[profile_id] = build_default_llm_provider(profile_config)
	return default_provider, named
