from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EffectBundle:
	effects: list[dict[str, Any]] = field(default_factory=list)
	record: dict[str, Any] = field(default_factory=dict)

	def is_empty(self) -> bool:
		return not bool(self.effects)

	def to_dict(self) -> dict[str, Any]:
		out: dict[str, Any] = {"effects": [dict(x) for x in self.effects]}
		if self.record:
			out["record"] = dict(self.record)
		return out


def effect_bundle_from_raw(raw: Any) -> EffectBundle:
	if isinstance(raw, EffectBundle):
		return EffectBundle(effects=[dict(x) for x in raw.effects], record=dict(raw.record or {}))
	if not isinstance(raw, dict):
		raise ValueError("effect bundle must be an object")
	effects = raw.get("effects", []) or []
	if not isinstance(effects, list):
		raise ValueError("effect bundle.effects must be list")
	if any(not isinstance(item, dict) for item in effects):
		raise ValueError("effect bundle.effects entries must be objects")
	record = raw.get("record", {}) or {}
	if not isinstance(record, dict):
		raise ValueError("effect bundle.record must be object")
	mode = str(record.get("mode", "none") or "none").strip()
	if mode not in {"none", "auto", "template"}:
		raise ValueError("effect bundle.record.mode must be one of none, auto, template")
	target = str(record.get("target", "self") or "self").strip()
	if mode != "none" and target != "self":
		raise ValueError("effect bundle.record.target currently supports only self")
	return EffectBundle(effects=[dict(x) for x in effects], record=dict(record))
