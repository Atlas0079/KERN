from __future__ import annotations

import json
import gzip
from pathlib import Path
from typing import Any

from ..component_catalog import ComponentCatalog, build_core_component_catalog
from ..models.components import ContainerComponent
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
	archive_snapshot_dir = dir_path / "snapshots"
	if archive_snapshot_dir.exists() and archive_snapshot_dir.is_dir():
		archive_candidates = sorted(list(archive_snapshot_dir.glob("snapshot_*.json.gz")))
		if archive_candidates:
			return archive_candidates[-1]
	return None


def resolve_global_log_file(checkpoint_dir: str | Path) -> Path:
	dir_raw = str(checkpoint_dir or "").strip()
	if not dir_raw:
		base_dir = Path.cwd() / "checkpoints"
	else:
		base_dir = Path(dir_raw)
	return base_dir / GLOBAL_LOG_FILE_NAME


def _int_or_default(value: Any, default: int) -> int:
	try:
		return int(value)
	except Exception:
		return int(default)


def _serialize_component_override(
	name: str,
	component: Any,
	component_catalog: ComponentCatalog,
) -> dict[str, Any]:
	return component_catalog.serialize(name, component)


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


def _world_dict_from_world_state(
	ws: WorldState,
	component_catalog: ComponentCatalog | None = None,
) -> dict[str, Any]:
	catalog = component_catalog or build_core_component_catalog()
	world: dict[str, Any] = {
		"world_state": {
			"current_tick": int(getattr(ws.game_time, "total_ticks", 0) or 0),
			"tick0_datetime": str(getattr(ws.game_time, "tick0_datetime", "") or ""),
		},
		"environment_scopes": [],
		"locations": [],
		"entities": [],
		"tasks": [],
		"paths": [],
	}
	location_map: dict[str, dict[str, Any]] = {}
	for loc in list(ws.locations.values()):
		if loc is None:
			continue
		location_id = str(getattr(loc, "location_id", "") or "")
		environment = {}
		if hasattr(ws, "get_environment_for_location"):
			environment = ws.get_environment_for_location(location_id)
		if not isinstance(environment, dict):
			environment = {}
		item = {
			"location_id": location_id,
			"location_name": str(getattr(loc, "location_name", "") or ""),
			"description": str(getattr(loc, "description", "") or ""),
			"light_level": _int_or_default(environment.get("light_level", getattr(loc, "light_level", 2)), 2),
			"environment": dict(environment),
			"entities": [],
		}
		lid = str(item["location_id"] or "")
		if not lid:
			continue
		world["locations"].append(item)
		location_map[lid] = item

	for scope in list(getattr(ws, "environment_scopes", {}).values()):
		if scope is None:
			continue
		scope_id = str(getattr(scope, "scope_id", "") or "")
		if not scope_id:
			continue
		fields = getattr(scope, "fields", {}) or {}
		world["environment_scopes"].append(
			{
				"scope_id": scope_id,
				"scope_type": str(getattr(scope, "scope_type", "region") or "region"),
				"location_ids": [str(x) for x in list(getattr(scope, "location_ids", []) or []) if str(x)],
				"priority": int(getattr(scope, "priority", 0) or 0),
				"fields": dict(fields) if isinstance(fields, dict) else {},
				"conditions": [str(x) for x in list(getattr(scope, "conditions", []) or []) if str(x)],
				"condition_expire_at_tick": {
					str(k): int(v)
					for k, v in dict(getattr(scope, "condition_expire_at_tick", {}) or {}).items()
					if str(k)
				},
			}
		)

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
			snapshot["component_overrides"][str(comp_name)] = _serialize_component_override(str(comp_name), comp_value, catalog)
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
	log_dir = checkpoint_path.parent.parent if checkpoint_path.parent.name == "snapshots" else checkpoint_path.parent
	log_path = resolve_global_log_file(log_dir)
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


def restore_world_state_from_checkpoint(
	checkpoint_path: Path,
	entity_templates: dict[str, Any],
	named_bundles: dict[str, Any] | None = None,
	component_catalog: ComponentCatalog | None = None,
) -> WorldState:
	catalog = component_catalog or build_core_component_catalog()
	if checkpoint_path.suffix == ".gz":
		with gzip.open(checkpoint_path, "rt", encoding="utf-8") as f:
			payload = json.load(f)
	else:
		with checkpoint_path.open("r", encoding="utf-8") as f:
			payload = json.load(f)
	meta = (payload or {}).get("meta", {}) or {}
	world = (payload or {}).get("world", {}) or {}
	if not isinstance(world, dict) or not world:
		raise ValueError("checkpoint world missing")
	if not isinstance(entity_templates, dict) or not entity_templates:
		raise ValueError("checkpoint restore requires non-empty entity_templates")
	ws = build_world_state(
		world,
		entity_templates,
		{},
		check_container_snapshot_consistency=True,
		named_bundles=named_bundles or {},
		component_catalog=catalog,
	).world_state
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
	ws._event_seq = max(
		[int((x or {}).get("seq", 0) or 0) for x in ws.event_log] + [int(meta.get("event_seq", 0) or 0)],
		default=0,
	)
	ws._interaction_seq = max(
		[int((x or {}).get("seq", 0) or 0) for x in ws.interaction_log] + [int(meta.get("interaction_seq", 0) or 0)],
		default=0,
	)
	setattr(ws, "_checkpoint_run_id", str(meta.get("run_id", "") or "").strip())
	setattr(ws, "_checkpoint_restore_tick", int(meta.get("tick", getattr(ws.game_time, "total_ticks", 0)) or 0))
	setattr(ws, "_checkpoint_restore_time_str", str(meta.get("time_str", "") or ""))
	return ws
