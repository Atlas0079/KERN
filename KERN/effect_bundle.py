from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EffectBundle:
	effects: list[dict[str, Any]] = field(default_factory=list)

	def is_empty(self) -> bool:
		return not bool(self.effects)

	def to_dict(self) -> dict[str, Any]:
		out: dict[str, Any] = {"effects": [dict(x) for x in list(self.effects or []) if isinstance(x, dict)]}
		return out


def effect_bundle_from_raw(raw: Any) -> EffectBundle:
	if isinstance(raw, EffectBundle):
		return EffectBundle(effects=[dict(x) for x in list(raw.effects or []) if isinstance(x, dict)])
	if not isinstance(raw, dict):
		raise ValueError("effect bundle must be an object")
	effects = raw.get("effects", []) or []
	if not isinstance(effects, list):
		raise ValueError("effect bundle.effects must be list")
	if any(not isinstance(item, dict) for item in effects):
		raise ValueError("effect bundle.effects entries must be objects")
	return EffectBundle(effects=[dict(x) for x in effects])
