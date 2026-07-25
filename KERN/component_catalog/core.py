from __future__ import annotations

from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..models.components import (
	AgentControlComponent,
	AgentSetting,
	ContainerComponent,
	CreatureComponent,
	AgentWakePolicyComponent,
	DescriptionComponent,
	EdibleComponent,
	EquipmentComponent,
	LogicControlComponent,
	MemoryComponent,
	PerceptionComponent,
	PlayerControlComponent,
	StatusComponent,
	TagComponent,
	TaskHostComponent,
	ValuableComponent,
	WorkerComponent,
	WorldStateEntityComponent,
)
from .catalog import ComponentCatalog
from .codecs import ContainerCodec, DataclassCodec, AgentWakePolicyCodec, TaskHostCodec
from .spec import ComponentSpec


def _dict(raw: Any) -> dict[str, Any]:
	return dict(raw or {}) if isinstance(raw, dict) else {}


def _agent_setting(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {
		"agent_name": str(d.get("agent_name", "")),
		"personality_summary": str(d.get("personality_summary", "")),
		"common_knowledge_summary": str(d.get("common_knowledge_summary", "")),
		"money": float(d.get("money", 0.0) or 0.0),
	}


def _agent_control(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {"enabled": bool(d.get("enabled", True)), "provider_id": str(d.get("provider_id", "") or "")}


def _player_control(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {"enabled": bool(d.get("enabled", True)), "provider_id": str(d.get("provider_id", "player") or "player")}


def _logic_control(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {"enabled": bool(d.get("enabled", True)), "provider_id": str(d.get("provider_id", "logic") or "logic")}


def _creature(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {
		"max_hp": float(d.get("max_hp", 100.0)),
		"max_energy": float(d.get("max_energy", 100.0)),
		"max_nutrition": float(d.get("max_nutrition", 100.0)),
		"max_stress": float(d["max_stress"]) if d.get("max_stress") is not None else None,
		"current_hp": float(d["current_hp"]) if d.get("current_hp") is not None else None,
		"current_energy": float(d["current_energy"]) if d.get("current_energy") is not None else None,
		"current_nutrition": float(d["current_nutrition"]) if d.get("current_nutrition") is not None else None,
		"current_stress": float(d["current_stress"]) if d.get("current_stress") is not None else None,
	}


def _memory(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {
		"short_term_queue": [dict(item) for item in list(d.get("short_term_queue", []) or []) if isinstance(item, dict)],
		"short_term_max_entries": int(d.get("short_term_max_entries", 25) or 25),
		"mid_term_prep_queue": [dict(item) for item in list(d.get("mid_term_prep_queue", []) or []) if isinstance(item, dict)],
		"mid_term_prep_max_entries": int(d.get("mid_term_prep_max_entries", 50) or 50),
		"mid_term_queue": [dict(item) for item in list(d.get("mid_term_queue", []) or []) if isinstance(item, dict)],
		"mid_term_max_entries": int(d.get("mid_term_max_entries", 20) or 20),
		"last_mid_term_summary_tick": int(d.get("last_mid_term_summary_tick", -1) or -1),
		"mid_term_summary_cooldown_ticks": int(d.get("mid_term_summary_cooldown_ticks", 15) or 15),
	}


def _description(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	description = str(d.get("description", "") or "")
	return {
		"description": description,
		"base_description": str(d.get("base_description", description) or ""),
		"observed_description": str(d.get("observed_description", description) or ""),
		"recipe_description": str(d.get("recipe_description", "") or ""),
	}


def _edible(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	return {"on_consume_bundle": effect_bundle_from_raw(d.get("on_consume_bundle", {}) or {"effects": []})}


def _status(raw: Any) -> dict[str, Any]:
	d = _dict(raw)
	expire: dict[str, int] = {}
	if isinstance(d.get("expire_at_tick"), dict):
		for key, value in dict(d.get("expire_at_tick") or {}).items():
			clean_key = str(key or "").strip()
			if not clean_key:
				continue
			try:
				expire[clean_key] = int(value)
			except Exception:
				continue
	return {"statuses": [str(item) for item in list(d.get("statuses", []) or [])], "expire_at_tick": expire}


def _register(catalog: ComponentCatalog, component_id: str, component_type: type, codec) -> None:
	catalog.register(ComponentSpec(component_id=component_id, component_type=component_type, codec=codec))


def build_core_component_catalog() -> ComponentCatalog:
	catalog = ComponentCatalog()
	_register(catalog, "AgentSetting", AgentSetting, DataclassCodec(AgentSetting, _agent_setting))
	_register(catalog, "AgentControlComponent", AgentControlComponent, DataclassCodec(AgentControlComponent, _agent_control))
	_register(catalog, "PlayerControlComponent", PlayerControlComponent, DataclassCodec(PlayerControlComponent, _player_control))
	_register(catalog, "LogicControlComponent", LogicControlComponent, DataclassCodec(LogicControlComponent, _logic_control))
	_register(catalog, "MemoryComponent", MemoryComponent, DataclassCodec(MemoryComponent, _memory))
	_register(catalog, "ContainerComponent", ContainerComponent, ContainerCodec())
	_register(catalog, "CreatureComponent", CreatureComponent, DataclassCodec(CreatureComponent, _creature))
	_register(catalog, "AgentWakePolicyComponent", AgentWakePolicyComponent, AgentWakePolicyCodec())
	_register(catalog, "DescriptionComponent", DescriptionComponent, DataclassCodec(DescriptionComponent, _description))
	_register(catalog, "EdibleComponent", EdibleComponent, DataclassCodec(EdibleComponent, _edible, _edible))
	_register(
		catalog,
		"EquipmentComponent",
		EquipmentComponent,
		DataclassCodec(EquipmentComponent, lambda raw: {"slots": dict(_dict(raw).get("slots", {}) or {})}),
	)
	_register(
		catalog,
		"PerceptionComponent",
		PerceptionComponent,
		DataclassCodec(
			PerceptionComponent,
			lambda raw: {
				"enabled": bool(_dict(raw).get("enabled", True)),
				"interaction_inbox": [
					dict(item)
					for item in list(_dict(raw).get("interaction_inbox", []) or [])
					if isinstance(item, dict)
				],
			},
		),
	)
	_register(catalog, "StatusComponent", StatusComponent, DataclassCodec(StatusComponent, _status))
	_register(
		catalog,
		"TagComponent",
		TagComponent,
		DataclassCodec(
			TagComponent,
			lambda raw: {"tags": [str(item) for item in list(_dict(raw).get("tags", []) or [])]},
		),
	)
	_register(catalog, "TaskHostComponent", TaskHostComponent, TaskHostCodec())
	_register(
		catalog,
		"ValuableComponent",
		ValuableComponent,
		DataclassCodec(
			ValuableComponent,
			lambda raw: {"price": float(_dict(raw).get("price", 0.0) or 0.0)},
		),
	)
	_register(
		catalog,
		"WorkerComponent",
		WorkerComponent,
		DataclassCodec(
			WorkerComponent,
			lambda raw: {"current_task_id": str(_dict(raw).get("current_task_id", "") or "")},
		),
	)
	_register(
		catalog,
		"WorldStateEntityComponent",
		WorldStateEntityComponent,
		DataclassCodec(
			WorldStateEntityComponent,
			lambda raw: {
				"debug_visible": bool(_dict(raw).get("debug_visible", True)),
				"visible_to_agents": bool(_dict(raw).get("visible_to_agents", False)),
				"note": str(_dict(raw).get("note", "") or ""),
			},
		),
	)
	return catalog
