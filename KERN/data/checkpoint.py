from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ..models.components import ContainerComponent, DecisionArbiterComponent, TaskHostComponent
from ..models.task import Task
from ..models.world_state import WorldState
from .builder import build_world_state


GLOBAL_LOG_FILE_NAME = "simulation_log.json"


def resolve_checkpoint_file(checkpoint_file: str, checkpoint_dir: str) -> Path | None:
	file_raw = str(checkpoint_file or "").strip()
	if file_raw:
		p = Path(file_raw)
		return p if p.exists() else None
	dir_raw = str(checkpoint_dir or "").strip()
	if not dir_raw:
		return None
	dir_path = Path(dir_raw)
	if not dir_path.exists() or not dir_path.is_dir():
		return None
	candidates = sorted(list(dir_path.glob("tick_*.json")))
	if not candidates:
		return None
	return candidates[-1]


def resolve_global_log_file(checkpoint_dir: str | Path) -> Path:
	dir_raw = str(checkpoint_dir or "").strip()
	if not dir_raw:
		base_dir = Path.cwd() / "checkpoints"
	else:
		base_dir = Path(dir_raw)
	return base_dir / GLOBAL_LOG_FILE_NAME


def _serialize_any(value: Any) -> Any:
	if value is None or isinstance(value, (str, int, float, bool)):
		return value
	if isinstance(value, dict):
		return {str(k): _serialize_any(v) for k, v in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_serialize_any(v) for v in value]
	if is_dataclass(value):
		return _serialize_any(asdict(value))
	if hasattr(value, "__dict__"):
		return _serialize_any(dict(vars(value)))
	return str(value)


def _serialize_task(task: Task) -> dict[str, Any]:
	return {
		"task_id": str(getattr(task, "task_id", "") or ""),
		"task_type": str(getattr(task, "task_type", "") or ""),
		"action_type": str(getattr(task, "action_type", "Action") or "Action"),
		"target_entity_id": str(getattr(task, "target_entity_id", "") or ""),
		"progress": float(getattr(task, "progress", 0.0) or 0.0),
		"required_progress": float(getattr(task, "required_progress", 0.0) or 0.0),
		"multiple_entity": bool(getattr(task, "multiple_entity", False)),
		"assigned_agent_ids": [str(x) for x in list(getattr(task, "assigned_agent_ids", []) or [])],
		"task_status": str(getattr(task, "task_status", "Inactive") or "Inactive"),
		"parameters": _serialize_any(dict(getattr(task, "parameters", {}) or {})),
		"progressor_id": str(getattr(task, "progressor_id", "") or ""),
		"progressor_params": _serialize_any(dict(getattr(task, "progressor_params", {}) or {})),
		"tick_effects": _serialize_any(list(getattr(task, "tick_effects", []) or [])),
		"completion_effects": _serialize_any(list(getattr(task, "completion_effects", []) or [])),
	}


def _serialize_arbiter_component(arb: Any) -> dict[str, Any]:
	rules_out: list[dict[str, Any]] = []
	for r in list(getattr(arb, "ruleset", []) or []):
		if isinstance(r, dict):
			rule_type = str(r.get("type", "") or "").strip()
			if rule_type:
				rules_out.append({str(k): _serialize_any(v) for k, v in r.items()})
			continue
		rule_class = str(getattr(getattr(r, "__class__", None), "__name__", "") or "")
		priority = int(getattr(r, "priority", 999) or 999)
		if rule_class == "LowNutritionRule":
			rules_out.append({"type": "LowNutrition", "priority": priority, "threshold": float(getattr(r, "threshold", 50.0) or 50.0)})
			continue
		if rule_class == "PerceptionChangeRule":
			rules_out.append(
				{
					"type": "PerceptionChange",
					"priority": priority,
					"trigger_on_agent_sighted": bool(getattr(r, "trigger_on_agent_sighted", True)),
					"trigger_on_agent_left": bool(getattr(r, "trigger_on_agent_left", True)),
				}
			)
			continue
		if rule_class == "CorpseSightedRule":
			rules_out.append({"type": "CorpseSighted", "priority": priority, "trigger_on_new_corpse": bool(getattr(r, "trigger_on_new_corpse", True))})
			continue
		if rule_class == "IdleRule":
			rules_out.append({"type": "Idle", "priority": priority})
	return {
		"rules": rules_out,
		"active_interrupt_preset_id": str(getattr(arb, "active_interrupt_preset_id", "") or ""),
		"interrupt_presets": _serialize_any(dict(getattr(arb, "interrupt_presets", {}) or {})),
		"interrupt_preset_descriptions": _serialize_any(dict(getattr(arb, "interrupt_preset_descriptions", {}) or {})),
		"interrupt_runtime_state": _serialize_any(dict(getattr(arb, "interrupt_runtime_state", {}) or {})),
		"_runtime_preset_id": str(getattr(arb, "_runtime_preset_id", "") or ""),
	}


def _serialize_component_override(name: str, comp: Any) -> dict[str, Any]:
	if isinstance(comp, DecisionArbiterComponent):
		return _serialize_arbiter_component(comp)
	if isinstance(comp, ContainerComponent):
		slots_out: dict[str, Any] = {}
		for sid, slot in (getattr(comp, "slots", {}) or {}).items():
			slots_out[str(sid)] = {
				"config": _serialize_any(dict(getattr(slot, "config", {}) or {})),
				"items": [str(x) for x in list(getattr(slot, "items", []) or [])],
			}
		return {"slots": slots_out}
	if isinstance(comp, TaskHostComponent):
		task_map: dict[str, Any] = {}
		task_items = []
		if hasattr(comp, "get_all_tasks"):
			task_items = list(comp.get_all_tasks() or [])
		elif isinstance(getattr(comp, "tasks", None), dict):
			task_items = list((getattr(comp, "tasks") or {}).values())
		for t in task_items:
			tid = str(getattr(t, "task_id", "") or "")
			if tid:
				task_map[tid] = _serialize_task(t)
		return {"tasks": task_map}
	raw = _serialize_any(comp)
	if isinstance(raw, dict):
		return raw
	return {"value": raw}


def _build_parent_map(ws: WorldState) -> dict[str, str]:
	parent_map: dict[str, str] = {}
	for ent in list(ws.entities.values()):
		if ent is None:
			continue
		container = ent.get_component("ContainerComponent")
		if not isinstance(container, ContainerComponent):
			continue
		for slot in (container.slots or {}).values():
			for item_id in list(getattr(slot, "items", []) or []):
				iid = str(item_id or "")
				if iid:
					parent_map[iid] = str(ent.entity_id)
	return parent_map


def _world_dict_from_world_state(ws: WorldState) -> dict[str, Any]:
	world: dict[str, Any] = {
		"world_state": {"current_tick": int(getattr(ws.game_time, "total_ticks", 0) or 0)},
		"locations": [],
		"entities": [],
		"tasks": [],
		"paths": [],
	}
	location_map: dict[str, dict[str, Any]] = {}
	for loc in list(ws.locations.values()):
		if loc is None:
			continue
		item = {
			"location_id": str(getattr(loc, "location_id", "") or ""),
			"location_name": str(getattr(loc, "location_name", "") or ""),
			"description": str(getattr(loc, "description", "") or ""),
			"entities": [],
		}
		lid = str(item["location_id"] or "")
		if not lid:
			continue
		world["locations"].append(item)
		location_map[lid] = item

	for p in list(ws.paths.values()):
		world["paths"].append(
			{
				"path_id": str(getattr(p, "path_id", "") or ""),
				"from_location_id": str(getattr(p, "from_location_id", "") or ""),
				"to_location_id": str(getattr(p, "to_location_id", "") or ""),
				"distance": float(getattr(p, "distance", 1.0) or 1.0),
				"travel_type": str(getattr(p, "travel_type", "walk") or "walk"),
				"is_blocked": bool(getattr(p, "is_blocked", False)),
			}
		)

	parent_map = _build_parent_map(ws)
	for ent in list(ws.entities.values()):
		if ent is None:
			continue
		snapshot: dict[str, Any] = {
			"instance_id": str(getattr(ent, "entity_id", "") or ""),
			"template_id": str(getattr(ent, "template_id", "") or ""),
			"component_overrides": {},
		}
		if not snapshot["instance_id"] or not snapshot["template_id"]:
			raise ValueError("world->checkpoint serialize failed: entity missing instance_id/template_id")
		for comp_name, comp_value in (getattr(ent, "components", {}) or {}).items():
			snapshot["component_overrides"][str(comp_name)] = _serialize_component_override(str(comp_name), comp_value)
		parent_id = str(parent_map.get(snapshot["instance_id"], "") or "")
		if parent_id:
			snapshot["parent_container"] = parent_id
			world["entities"].append(snapshot)
			continue
		loc = ws.get_location_of_entity(snapshot["instance_id"])
		lid = str(getattr(loc, "location_id", "") or "") if loc is not None else ""
		if not lid or lid not in location_map:
			raise ValueError(f"world->checkpoint serialize failed: top-level entity has no location: {snapshot['instance_id']}")
		location_map[lid]["entities"].append(snapshot)
	return world


def _build_combined_log_rows(
	ws: WorldState,
	*,
	tick: int | None = None,
	tick_max: int | None = None,
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []

	def _include(rec: dict[str, Any]) -> bool:
		rec_tick = int(rec.get("tick", 0) or 0)
		if tick is not None and rec_tick != int(tick):
			return False
		if tick_max is not None and rec_tick > int(tick_max):
			return False
		return True

	for rec in list(getattr(ws, "event_log", []) or []):
		if not isinstance(rec, dict) or not _include(rec):
			continue
		row = dict(rec)
		row["kind"] = "event"
		rows.append(row)
	for rec in list(getattr(ws, "interaction_log", []) or []):
		if not isinstance(rec, dict) or not _include(rec):
			continue
		row = dict(rec)
		row["kind"] = "interaction"
		rows.append(row)
	rows.sort(key=lambda x: (int((x or {}).get("tick", 0) or 0), int((x or {}).get("seq", 0) or 0), str((x or {}).get("kind", ""))))
	return rows


def build_checkpoint_payload_from_world_state(ws: WorldState, include_logs: bool = True, run_id: str = "") -> dict[str, Any]:
	tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
	payload: dict[str, Any] = {
		"meta": {"schema_version": "checkpoint.v4", "tick": tick, "time_str": ws.game_time.time_to_string()},
		"world": _world_dict_from_world_state(ws),
	}
	if str(run_id or "").strip():
		payload["meta"]["run_id"] = str(run_id).strip()
	if include_logs:
		payload["meta"]["log_scope"] = "tick"
		payload["log"] = _build_combined_log_rows(ws, tick=tick)
	return payload


def build_simulation_log_payload_from_world_state(ws: WorldState, run_id: str = "") -> dict[str, Any]:
	tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
	meta: dict[str, Any] = {
		"schema_version": "simlog.v1",
		"last_tick": tick,
		"time_str": ws.game_time.time_to_string(),
	}
	if str(run_id or "").strip():
		meta["run_id"] = str(run_id).strip()
	return {
		"meta": meta,
		"log": _build_combined_log_rows(ws),
	}


def _load_history_log_rows(checkpoint_path: Path, checkpoint_meta: dict[str, Any]) -> list[dict[str, Any]]:
	run_id = str((checkpoint_meta or {}).get("run_id", "") or "").strip()
	if not run_id:
		return []
	log_path = resolve_global_log_file(checkpoint_path.parent)
	if not log_path.exists():
		return []
	try:
		payload = json.loads(log_path.read_text(encoding="utf-8"))
	except Exception:
		return []
	if not isinstance(payload, dict):
		return []
	meta = payload.get("meta", {}) or {}
	if str(meta.get("run_id", "") or "").strip() != run_id:
		return []
	tick_limit = int((checkpoint_meta or {}).get("tick", 0) or 0)
	rows = payload.get("log", []) or []
	if not isinstance(rows, list):
		return []
	out: list[dict[str, Any]] = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		if int(row.get("tick", 0) or 0) > tick_limit:
			continue
		out.append(dict(row))
	out.sort(key=lambda x: (int((x or {}).get("tick", 0) or 0), int((x or {}).get("seq", 0) or 0), str((x or {}).get("kind", ""))))
	return out


def restore_world_state_from_checkpoint(checkpoint_path: Path, entity_templates: dict[str, Any]) -> WorldState:
	with checkpoint_path.open("r", encoding="utf-8") as f:
		payload = json.load(f)
	meta = (payload or {}).get("meta", {}) or {}
	world = (payload or {}).get("world", {}) or {}
	if not isinstance(world, dict) or not world:
		raise ValueError("checkpoint world missing")
	if not isinstance(entity_templates, dict) or not entity_templates:
		raise ValueError("checkpoint restore requires non-empty entity_templates")
	ws = build_world_state(world, entity_templates, {}, check_container_snapshot_consistency=True).world_state
	log_rows = _load_history_log_rows(checkpoint_path, meta)
	if not log_rows:
		log_rows = (payload or {}).get("log", []) or []
	if not isinstance(log_rows, list):
		log_rows = []
	event_log: list[dict[str, Any]] = []
	interaction_log: list[dict[str, Any]] = []
	for row in log_rows:
		if not isinstance(row, dict):
			continue
		kind = str(row.get("kind", "") or "")
		rec = dict(row)
		rec.pop("kind", None)
		if kind == "event":
			event_log.append(rec)
		elif kind == "interaction":
			interaction_log.append(rec)
	ws.event_log = event_log
	ws.interaction_log = interaction_log
	ws._event_seq = max([int((x or {}).get("seq", 0) or 0) for x in ws.event_log], default=0)
	ws._interaction_seq = max([int((x or {}).get("seq", 0) or 0) for x in ws.interaction_log], default=0)
	setattr(ws, "_checkpoint_run_id", str(meta.get("run_id", "") or "").strip())
	return ws
