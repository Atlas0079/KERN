from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class DecisionArbiterComponent:
	"""Pure data component for interrupt configuration and runtime state."""

	ruleset: list[Any] = field(default_factory=list)
	active_interrupt_preset_id: str = ""
	interrupt_presets: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
	interrupt_preset_descriptions: dict[str, str] = field(default_factory=dict)
	interrupt_runtime_state: dict[str, dict[str, Any]] = field(default_factory=dict)
	_runtime_preset_id: str = ""

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		# Arbiter component usually doesn't need progression, read-only check suffices.
		return

	def get_active_interrupt_rule_params(self, rule_type: str) -> dict[str, Any]:
		preset_id = str(self.active_interrupt_preset_id or "").strip()
		if not preset_id:
			return {}
		preset = (self.interrupt_presets or {}).get(preset_id, {})
		if not isinstance(preset, dict):
			return {}
		params = preset.get(str(rule_type), {})
		return dict(params) if isinstance(params, dict) else {}

	def get_rule_runtime(self, rule_type: str) -> dict[str, Any]:
		return self._get_rule_runtime(rule_type)

	def _get_rule_runtime(self, rule_type: str) -> dict[str, Any]:
		rt = (self.interrupt_runtime_state or {}).get(rule_type, None)
		if not isinstance(rt, dict):
			rt = {"latched": False, "last_fire_tick": -10**18}
			self.interrupt_runtime_state[str(rule_type)] = rt
		rt.setdefault("latched", False)
		rt.setdefault("last_fire_tick", -10**18)
		return rt

	@staticmethod
	def from_template_data(component_data: dict[str, Any]) -> "DecisionArbiterComponent":
		rules_raw = component_data.get("rules", []) if isinstance(component_data, dict) else []
		ruleset: list[Any] = []

		for rd in rules_raw:
			if not isinstance(rd, dict):
				continue
			rule_type = str(rd.get("type", "") or "").strip()
			if not rule_type:
				continue
			item = dict(rd)
			item["type"] = rule_type
			try:
				item["priority"] = int(item.get("priority", 999999))
			except Exception:
				item["priority"] = 999999
			ruleset.append(item)

		ruleset.sort(key=lambda r: int((r or {}).get("priority", 999999)))
		active_interrupt_preset_id = str((component_data or {}).get("active_interrupt_preset_id", "") or "")
		interrupt_presets = (component_data or {}).get("interrupt_presets", {}) or {}
		interrupt_preset_descriptions = (component_data or {}).get("interrupt_preset_descriptions", {}) or {}
		if not isinstance(interrupt_presets, dict):
			interrupt_presets = {}
		if not isinstance(interrupt_preset_descriptions, dict):
			interrupt_preset_descriptions = {}
		return DecisionArbiterComponent(
			ruleset=ruleset,
			active_interrupt_preset_id=active_interrupt_preset_id,
			interrupt_presets=dict(interrupt_presets),
			interrupt_preset_descriptions={str(k): str(v or "") for k, v in dict(interrupt_preset_descriptions).items()},
		)
