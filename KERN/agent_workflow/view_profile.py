from __future__ import annotations

from typing import Any


DEFAULT_PROFILE_ID = "embodied_default"


BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
	"embodied_default": {
		"profile_id": "embodied_default",
		"perception": {
			"include_visible_entities": True,
			"include_map_topology": True,
			"include_reachable_locations": True,
			"include_location_description": True,
			"include_inventory": True,
			"include_operable_screen_contexts": True,
			"can_start_conversation_here": True,
		},
		"memory": {
			"include_same_location_events": True,
			"include_same_location_interactions": True,
			"include_social_events_from_other_actors": True,
		},
	},
	"social_platform": {
		"profile_id": "social_platform",
		"perception": {
			"include_visible_entities": False,
			"include_map_topology": False,
			"include_reachable_locations": False,
			"include_location_description": False,
			"include_inventory": True,
			"include_operable_screen_contexts": True,
			"can_start_conversation_here": False,
		},
		"memory": {
			"include_same_location_events": False,
			"include_same_location_interactions": False,
			"include_social_events_from_other_actors": False,
		},
	},
	"social_platform_debug": {
		"profile_id": "social_platform_debug",
		"perception": {
			"include_visible_entities": True,
			"include_map_topology": False,
			"include_reachable_locations": False,
			"include_location_description": True,
			"include_inventory": True,
			"include_operable_screen_contexts": True,
			"can_start_conversation_here": False,
		},
		"memory": {
			"include_same_location_events": False,
			"include_same_location_interactions": False,
			"include_social_events_from_other_actors": False,
		},
	},
}


def _as_bool(value: Any, default: bool) -> bool:
	if value is None:
		return bool(default)
	if isinstance(value, bool):
		return bool(value)
	text = str(value).strip().lower()
	if text in {"1", "true", "yes", "on"}:
		return True
	if text in {"0", "false", "no", "off"}:
		return False
	return bool(default)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
	out = dict(base or {})
	for key, value in dict(override or {}).items():
		if isinstance(value, dict) and isinstance(out.get(key), dict):
			out[key] = _deep_merge(dict(out.get(key, {}) or {}), dict(value))
		else:
			out[key] = value
	return out


def normalize_workflow_view_profile(profile_id: str = "", override: dict[str, Any] | None = None) -> dict[str, Any]:
	pid = str(profile_id or "").strip() or DEFAULT_PROFILE_ID
	base = BUILTIN_PROFILES.get(pid)
	if base is None:
		base = BUILTIN_PROFILES[DEFAULT_PROFILE_ID]
		pid = DEFAULT_PROFILE_ID
	profile = _deep_merge(dict(base), dict(override or {}))
	profile["profile_id"] = str(profile.get("profile_id", "") or pid)
	perception = dict(profile.get("perception", {}) or {})
	memory = dict(profile.get("memory", {}) or {})
	default_perception = dict(BUILTIN_PROFILES[DEFAULT_PROFILE_ID]["perception"])
	default_memory = dict(BUILTIN_PROFILES[DEFAULT_PROFILE_ID]["memory"])
	profile["perception"] = {
		key: _as_bool(perception.get(key), bool(default_perception.get(key, True)))
		for key in default_perception.keys()
	}
	profile["memory"] = {
		key: _as_bool(memory.get(key), bool(default_memory.get(key, True)))
		for key in default_memory.keys()
	}
	return profile


def active_workflow_view_profile(ws: Any = None, mode_context: dict[str, Any] | None = None, full_ws_view: dict[str, Any] | None = None) -> dict[str, Any]:
	for source in (mode_context, full_ws_view):
		if isinstance(source, dict):
			raw = source.get("workflow_view_profile", None)
			if isinstance(raw, dict) and raw:
				return normalize_workflow_view_profile(str(raw.get("profile_id", "") or ""), raw)
			pid = str(source.get("workflow_view_profile_id", "") or "").strip()
			if pid:
				return normalize_workflow_view_profile(pid)
	services = getattr(ws, "services", {}) if ws is not None else {}
	if isinstance(services, dict):
		raw = services.get("workflow_view_profile", None)
		if isinstance(raw, dict) and raw:
			return normalize_workflow_view_profile(str(raw.get("profile_id", "") or ""), raw)
	return normalize_workflow_view_profile()
