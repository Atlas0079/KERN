from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EffectBundle:
	effects: list[dict[str, Any]] = field(default_factory=list)
	react_per_effect: bool = False

	def is_empty(self) -> bool:
		return not bool(self.effects)

	def to_dict(self) -> dict[str, Any]:
		out = {"effects": [dict(x) for x in list(self.effects or []) if isinstance(x, dict)]}
		if bool(self.react_per_effect):
			out["react_per_effect"] = True
		return out


def effect_bundle_from_raw(raw: Any) -> EffectBundle:
	if isinstance(raw, EffectBundle):
		return EffectBundle(effects=[dict(x) for x in list(raw.effects or []) if isinstance(x, dict)], react_per_effect=bool(raw.react_per_effect))
	if not isinstance(raw, dict):
		raise ValueError("effect bundle must be an object")
	effects = raw.get("effects", []) or []
	if not isinstance(effects, list):
		raise ValueError("effect bundle.effects must be list")
	react_per_effect = raw.get("react_per_effect", False)
	if not isinstance(react_per_effect, bool):
		raise ValueError("effect bundle.react_per_effect must be bool")
	return EffectBundle(effects=[dict(x) for x in effects if isinstance(x, dict)], react_per_effect=bool(react_per_effect))

