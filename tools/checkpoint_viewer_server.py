from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

from app import _cfg_bool, _cfg_get, _load_runtime_config
from KERN.data.archive import ARCHIVE_MANIFEST_FILE_NAME, materialize_archive_state


TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8765
FRAME_CACHE_LIMIT = 64


def _scene_id_from_config_path(project_root: Path, config_path: Path) -> str:
	try:
		relative = config_path.resolve().relative_to(project_root.resolve())
		name = relative.as_posix()
	except Exception:
		name = config_path.name
	base = str(name or "").replace("\\", "/")
	if base.endswith(".json"):
		base = base[:-5]
	if base.startswith("runtime_config."):
		base = base[len("runtime_config.") :]
	elif base == "runtime_config":
		base = "default"
	base = base.replace("/", "_").replace(".", "_").strip("_")
	return base or "default"


@dataclass(frozen=True)
class ArchiveScene:
	scene_id: str
	name: str
	archive_dir: Path
	last_tick: int
	run_id: str

	def to_dict(self, active: bool = False) -> dict:
		return {
			"id": self.scene_id,
			"name": self.name,
			"archive_dir": str(self.archive_dir),
			"last_tick": int(self.last_tick),
			"run_id": str(self.run_id or ""),
			"archive_ready": True,
			"active": bool(active),
		}


class ArchiveViewerData:
	def __init__(self, archive_root: Path, scene_id: str = "") -> None:
		self.archive_root = archive_root.resolve()
		self.active_scene_id = str(scene_id or "").strip()
		self.active_archive_dir: Path | None = None
		self.manifest: dict = {}
		self._log_rows_by_tick: dict[int, list[dict]] | None = None
		self._frame_cache: OrderedDict[int, dict] = OrderedDict()
		self._scene_config_cache: dict[str, dict] = {}
		self.refresh_scenes()

	def refresh_scenes(self) -> list[ArchiveScene]:
		scenes = self._discover_scenes()
		if not scenes:
			if self.active_scene_id or self.active_archive_dir is not None:
				self.active_scene_id = ""
				self.active_archive_dir = None
				self._clear_active_cache()
			return []
		ids = {scene.scene_id for scene in scenes}
		if self.active_scene_id not in ids:
			self.active_scene_id = scenes[0].scene_id
		active = next(scene for scene in scenes if scene.scene_id == self.active_scene_id)
		if self.active_archive_dir != active.archive_dir:
			self.active_archive_dir = active.archive_dir
			self._clear_active_cache()
		return scenes

	def switch_scene(self, scene_id: str) -> dict:
		wanted = str(scene_id or "").strip()
		if not wanted:
			raise ValueError("scene_id is required")
		scenes = self._discover_scenes()
		matched = next((scene for scene in scenes if scene.scene_id == wanted), None)
		if matched is None:
			raise ValueError(f"unknown archive scene: {wanted}")
		self.active_scene_id = matched.scene_id
		self.active_archive_dir = matched.archive_dir
		self._clear_active_cache()
		return self.manifest_payload()

	def scenes_payload(self) -> dict:
		scenes = self.refresh_scenes()
		return {
			"archive_root": str(self.archive_root),
			"active_scene_id": self.active_scene_id,
			"scenes": [scene.to_dict(active=scene.scene_id == self.active_scene_id) for scene in scenes],
		}

	def companion_config_payload(self) -> dict:
		self.refresh_scenes()
		return {
			"archive_root": str(self.archive_root),
			"active_scene_id": self.active_scene_id,
		}

	def manifest_payload(self) -> dict:
		scenes = self.refresh_scenes()
		active = next((scene for scene in scenes if scene.scene_id == self.active_scene_id), None)
		archive_dir = self._require_active_archive_dir(allow_missing=True)
		if active is None:
			self.manifest = {}
			self._log_rows_by_tick = None
			return {
				"archive_root": str(self.archive_root),
				"archive_dir": "",
				"archive_ready": False,
				"active_scene_id": "",
				"scenes": [],
				"ticks": [],
			}
		if archive_dir is None or not self._archive_ready(archive_dir):
			self.manifest = {}
			self._log_rows_by_tick = None
			return {
				"archive_root": str(self.archive_root),
				"archive_dir": str(archive_dir) if archive_dir is not None else "",
				"archive_ready": False,
				"active_scene_id": self.active_scene_id,
				"scenes": [scene.to_dict(active=scene.scene_id == self.active_scene_id) for scene in scenes],
				"ticks": [],
				"last_tick": int(active.last_tick),
				"run_id": str(active.run_id or ""),
			}
		self.manifest = self._load_manifest()
		last_tick = int(self.manifest.get("last_tick", 0) or 0)
		ticks = list(range(max(0, last_tick) + 1))
		return {
			**self.manifest,
			"archive_root": str(self.archive_root),
			"archive_dir": str(archive_dir),
			"archive_ready": True,
			"active_scene_id": self.active_scene_id,
			"scenes": [scene.to_dict(active=scene.scene_id == self.active_scene_id) for scene in scenes],
			"ticks": ticks,
		}

	def frame_payload(self, tick: int) -> dict:
		self.refresh_scenes()
		self.manifest = self._load_manifest()
		target_tick = int(tick)
		last_tick = int(self.manifest.get("last_tick", 0) or 0)
		if target_tick < 0 or target_tick > last_tick:
			raise ValueError(f"tick out of archive range: {target_tick}")
		if target_tick in self._frame_cache:
			frame = self._frame_cache.pop(target_tick)
			self._frame_cache[target_tick] = frame
			return frame
		archive_dir = self._require_active_archive_dir()
		world = materialize_archive_state(archive_dir, target_tick)
		frame = {
			"fileName": f"{self.active_scene_id}:{target_tick}",
			"tick": target_tick,
			"timeStr": self._time_str_from_world(world),
			"runId": str(self.manifest.get("run_id", "") or ""),
			"logScope": "tick",
			"world": world,
			"log": self._log_rows_for_tick(target_tick),
		}
		self._frame_cache[target_tick] = frame
		while len(self._frame_cache) > FRAME_CACHE_LIMIT:
			self._frame_cache.popitem(last=False)
		return frame

	def _discover_scenes(self) -> list[ArchiveScene]:
		return sorted(self._discover_archive_scenes(), key=lambda scene: (scene.name.lower(), scene.scene_id.lower()))

	def _discover_archive_scenes(self) -> list[ArchiveScene]:
		root = self.archive_root
		if not root.exists() or not root.is_dir():
			return []
		manifest_paths = sorted(root.rglob(ARCHIVE_MANIFEST_FILE_NAME), key=lambda p: str(p.parent.relative_to(root)).lower())
		scenes: list[ArchiveScene] = []
		for manifest_path in manifest_paths:
			archive_dir = manifest_path.parent.resolve()
			try:
				relative = archive_dir.relative_to(root)
			except ValueError:
				continue
			if not self._archive_ready(archive_dir):
				continue
			manifest = self._read_manifest(archive_dir)
			if not isinstance(manifest, dict):
				continue
			scene_id = relative.as_posix() if str(relative) != "." else archive_dir.name
			name = archive_dir.name if str(relative) == "." else relative.as_posix()
			scenes.append(
				ArchiveScene(
					scene_id=scene_id,
					name=name,
					archive_dir=archive_dir,
					last_tick=int(manifest.get("last_tick", 0) or 0),
					run_id=str(manifest.get("run_id", "") or ""),
				)
			)
		return scenes

	def _load_manifest(self) -> dict:
		archive_dir = self._require_active_archive_dir()
		path = archive_dir / ARCHIVE_MANIFEST_FILE_NAME
		if not path.exists():
			raise FileNotFoundError(f"archive manifest not found: {path}")
		payload = self._read_manifest(archive_dir)
		if not isinstance(payload, dict):
			raise ValueError(f"archive manifest must be object: {path}")
		previous = dict(self.manifest or {}) if isinstance(self.manifest, dict) else {}
		prev_run_id = str(previous.get("run_id", "") or "")
		next_run_id = str(payload.get("run_id", "") or "")
		prev_last_tick = int(previous.get("last_tick", -1) or -1)
		next_last_tick = int(payload.get("last_tick", -1) or -1)
		if previous and (prev_run_id != next_run_id or next_last_tick < prev_last_tick):
			self._clear_active_cache()
		self._log_rows_by_tick = None
		return payload

	def _read_manifest(self, archive_dir: Path) -> dict | None:
		path = archive_dir / ARCHIVE_MANIFEST_FILE_NAME
		if not path.exists():
			return None
		with path.open("r", encoding="utf-8") as f:
			payload = json.load(f)
		return payload if isinstance(payload, dict) else None

	def _archive_ready(self, archive_dir: Path) -> bool:
		return (archive_dir / ARCHIVE_MANIFEST_FILE_NAME).exists() and (archive_dir / "snapshots").is_dir() and any((archive_dir / "snapshots").glob("snapshot_*.json.gz"))

	def _require_active_archive_dir(self, allow_missing: bool = False) -> Path | None:
		if self.active_archive_dir is None:
			self.refresh_scenes()
		if self.active_archive_dir is None:
			if allow_missing:
				return None
			raise FileNotFoundError("no active archive scene")
		return self.active_archive_dir

	def _clear_active_cache(self) -> None:
		self.manifest = {}
		self._log_rows_by_tick = None
		self._frame_cache.clear()

	def _scene_config_payload(self, scene_id: str) -> dict:
		key = str(scene_id or "").strip()
		if not key:
			return {}
		cached = self._scene_config_cache.get(key)
		if cached is not None:
			return dict(cached)
		payload: dict[str, object] = {}
		for config_path in sorted(ROOT_DIR.glob("runtime_config.*.json"), key=lambda p: p.name.lower()):
			try:
				cfg, resolved_path = _load_runtime_config(ROOT_DIR, str(config_path))
			except Exception:
				continue
			candidate_scene_id = _scene_id_from_config_path(ROOT_DIR, resolved_path)
			if candidate_scene_id != key:
				continue
			use_llm = _cfg_bool(cfg, "USE_LLM", False)
			payload = {
				"scene_id": key,
				"config_path": str(resolved_path),
				"use_llm": bool(use_llm),
				"llm_provider": _cfg_get(cfg, "LLM_PROVIDER", "openai_compat"),
				"planner_model": _cfg_get(cfg, "LLM_PLANNER_MODEL", ""),
				"grounder_model": _cfg_get(cfg, "LLM_GROUNDER_MODEL", ""),
				"action_provider": "LLMActionProvider" if use_llm else "SimplePolicyActionProvider",
			}
			break
		result = dict(payload)
		self._scene_config_cache[key] = result
		return dict(result)

	def _time_str_from_world(self, world: dict) -> str:
		world_state = world.get("world_state", {}) if isinstance(world, dict) else {}
		if not isinstance(world_state, dict):
			return ""
		return str(world_state.get("time_str", "") or world_state.get("current_time", "") or "")

	def _log_rows_for_tick(self, tick: int) -> list[dict]:
		if self._log_rows_by_tick is None:
			self._log_rows_by_tick = self._load_simulation_log()
		return list(self._log_rows_by_tick.get(int(tick), []))

	def _load_simulation_log(self) -> dict[int, list[dict]]:
		path = self._require_active_archive_dir() / "simulation_log.json"
		if not path.exists():
			return {}
		with path.open("r", encoding="utf-8") as f:
			payload = json.load(f)
		if isinstance(payload, dict):
			rows = payload.get("rows", payload.get("log", []))
		else:
			rows = payload
		grouped: dict[int, list[dict]] = {}
		for row in rows if isinstance(rows, list) else []:
			if not isinstance(row, dict):
				continue
			try:
				row_tick = int(row.get("tick", 0) or 0)
			except Exception:
				continue
			grouped.setdefault(row_tick, []).append(row)
		return grouped

	def companion_state_payload(self, *, scene_id: str = "", cursor: int = 0, agent_id: str = "") -> dict:
		wanted_scene_id = str(scene_id or "").strip()
		if wanted_scene_id:
			scene = next((x for x in self._discover_scenes() if x.scene_id == wanted_scene_id), None)
			if scene is None:
				return {
					"status": "waiting_for_archive",
					"tick": -1,
					"time": "",
					"agent_id": "",
					"location": {"id": "", "name": ""},
					"vitals": {},
					"current_task": None,
					"outbox_count": 0,
					"diagnostics": {},
					"outbox": {"items": [], "cursor": int(cursor or 0), "next_cursor": int(cursor or 0)},
					"active_scene_id": wanted_scene_id,
				}
			if wanted_scene_id != self.active_scene_id:
				self.active_scene_id = wanted_scene_id
				self.active_archive_dir = scene.archive_dir
				self._clear_active_cache()
		manifest = self.manifest_payload()
		if not bool(manifest.get("archive_ready", False)):
			return {
				"status": "waiting_for_archive",
				"tick": int(manifest.get("last_tick", -1) or -1),
				"time": "",
				"agent_id": "",
				"location": {"id": "", "name": ""},
				"vitals": {},
				"current_task": None,
				"outbox_count": 0,
				"diagnostics": {},
				"outbox": {"items": [], "cursor": int(cursor or 0), "next_cursor": int(cursor or 0)},
				"active_scene_id": str(manifest.get("active_scene_id", "") or ""),
			}
		last_tick = int(manifest.get("last_tick", 0) or 0)
		frame = self.frame_payload(last_tick)
		world = dict(frame.get("world", {}) or {})
		companion = self._resolve_companion_entity(world, agent_id=agent_id)
		location = self._resolve_companion_location(world, companion.get("instance_id", ""))
		vitals = self._extract_vitals(companion)
		task_payload = self._extract_current_task(world, companion)
		outbox = self._build_outbox_payload(last_tick=last_tick, cursor=cursor)
		diagnostics = self._build_diagnostics_payload(last_tick=last_tick)
		return {
			"status": "running",
			"tick": last_tick,
			"time": str(frame.get("timeStr", "") or ""),
			"agent_id": str(companion.get("instance_id", "") or ""),
			"location": location,
			"vitals": vitals,
			"current_task": task_payload,
			"outbox_count": int(len(outbox.get("items", []) or [])),
			"diagnostics": diagnostics,
			"outbox": outbox,
			"active_scene_id": str(manifest.get("active_scene_id", "") or ""),
		}

	def companion_outbox_payload(self, *, scene_id: str = "", cursor: int = 0) -> dict:
		wanted_scene_id = str(scene_id or "").strip()
		if wanted_scene_id:
			scene = next((x for x in self._discover_scenes() if x.scene_id == wanted_scene_id), None)
			if scene is None:
				return {"items": [], "cursor": int(cursor or 0), "next_cursor": int(cursor or 0), "active_scene_id": wanted_scene_id}
			if wanted_scene_id != self.active_scene_id:
				self.active_scene_id = wanted_scene_id
				self.active_archive_dir = scene.archive_dir
				self._clear_active_cache()
		manifest = self.manifest_payload()
		if not bool(manifest.get("archive_ready", False)):
			return {"items": [], "cursor": int(cursor or 0), "next_cursor": int(cursor or 0), "active_scene_id": str(manifest.get("active_scene_id", "") or "")}
		last_tick = int(manifest.get("last_tick", 0) or 0)
		payload = self._build_outbox_payload(last_tick=last_tick, cursor=cursor)
		payload["active_scene_id"] = str(manifest.get("active_scene_id", "") or "")
		return payload

	def _resolve_companion_entity(self, world: dict, *, agent_id: str = "") -> dict:
		entity_map = self._world_entity_map(world)
		want = str(agent_id or "").strip()
		if want and want in entity_map:
			return dict(entity_map[want])
		if "robot_doudou" in entity_map:
			return dict(entity_map["robot_doudou"])
		for item in entity_map.values():
			tags = self._entity_tags(item)
			if "companion_robot" in tags:
				return dict(item)
		for item in entity_map.values():
			tags = self._entity_tags(item)
			if "agent" in tags and "robot" in tags:
				return dict(item)
		return {}

	def _resolve_companion_location(self, world: dict, entity_id: str) -> dict:
		eid = str(entity_id or "")
		if not eid:
			return {"id": "", "name": ""}
		for loc in list(world.get("locations", []) or []):
			if not isinstance(loc, dict):
				continue
			for ent in list(loc.get("entities", []) or []):
				if isinstance(ent, dict) and str(ent.get("instance_id", "") or "") == eid:
					return {
						"id": str(loc.get("location_id", "") or ""),
						"name": str(loc.get("location_name", "") or ""),
					}
		return {"id": "", "name": ""}

	def _extract_vitals(self, entity: dict) -> dict:
		comp = dict((entity.get("component_overrides", {}) or {}).get("CreatureComponent", {}) or {})
		battery = float(comp.get("current_energy", 0.0) or 0.0)
		battery_max = float(comp.get("max_energy", 0.0) or 0.0)
		worry = float(comp.get("current_stress", 0.0) or 0.0)
		worry_max = float(comp.get("max_stress", 0.0) or 0.0)
		return {
			"battery": round(battery, 1),
			"battery_max": round(battery_max, 1),
			"worry": round(worry, 1),
			"worry_max": round(worry_max, 1),
		}

	def _extract_current_task(self, world: dict, entity: dict) -> dict | None:
		worker = dict((entity.get("component_overrides", {}) or {}).get("WorkerComponent", {}) or {})
		task_id = str(worker.get("current_task_id", "") or "")
		if not task_id:
			return None
		task_map = self._world_task_map(world)
		task = dict(task_map.get(task_id, {}) or {})
		if not task:
			return {"id": task_id, "type": "", "target_id": "", "status": "", "progress": 0.0, "required": 0.0, "ratio": 0.0}
		required = float(task.get("required_progress", 0.0) or 0.0)
		progress = float(task.get("progress", 0.0) or 0.0)
		return {
			"id": str(task.get("task_id", "") or task_id),
			"type": str(task.get("task_type", "") or ""),
			"target_id": str(task.get("target_entity_id", "") or ""),
			"status": str(task.get("task_status", "") or ""),
			"progress": round(progress, 2),
			"required": round(required, 2),
			"ratio": round(progress / required, 3) if required > 0 else 1.0,
		}

	def _world_entity_map(self, world: dict) -> dict[str, dict]:
		entity_map: dict[str, dict] = {}
		for loc in list(world.get("locations", []) or []):
			if not isinstance(loc, dict):
				continue
			for ent in list(loc.get("entities", []) or []):
				if isinstance(ent, dict):
					eid = str(ent.get("instance_id", "") or "")
					if eid:
						entity_map[eid] = dict(ent)
		for ent in list(world.get("entities", []) or []):
			if isinstance(ent, dict):
				eid = str(ent.get("instance_id", "") or "")
				if eid:
					entity_map[eid] = dict(ent)
		return entity_map

	def _world_task_map(self, world: dict) -> dict[str, dict]:
		task_map: dict[str, dict] = {}
		for ent in self._world_entity_map(world).values():
			comp = dict((ent.get("component_overrides", {}) or {}).get("TaskHostComponent", {}) or {})
			tasks = dict(comp.get("tasks", {}) or {})
			for tid, raw_task in tasks.items():
				task_id = str(tid or "")
				if task_id and isinstance(raw_task, dict):
					task_map[task_id] = dict(raw_task)
		return task_map

	def _entity_tags(self, entity: dict) -> list[str]:
		tag_comp = dict((entity.get("component_overrides", {}) or {}).get("TagComponent", {}) or {})
		return [str(x) for x in list(tag_comp.get("tags", []) or []) if str(x)]

	def _all_logs_until(self, *, last_tick: int) -> list[dict]:
		if self._log_rows_by_tick is None:
			self._log_rows_by_tick = self._load_simulation_log()
		rows: list[dict] = []
		for tick in sorted(self._log_rows_by_tick.keys()):
			if int(tick) > int(last_tick):
				continue
			rows.extend([dict(x) for x in list(self._log_rows_by_tick.get(tick, []) or []) if isinstance(x, dict)])
		return rows

	def _build_outbox_payload(self, *, last_tick: int, cursor: int) -> dict:
		items: list[dict] = []
		cursor_int = int(cursor or 0)
		for row in self._all_logs_until(last_tick=last_tick):
			if str(row.get("kind", "") or "") != "event":
				continue
			seq = int(row.get("seq", 0) or 0)
			if seq <= cursor_int:
				continue
			event = dict(row.get("event", {}) or {})
			ev_type = str(event.get("type", "") or "")
			if ev_type != "EventEmitted":
				continue
			payload = dict(event.get("payload", {}) or {})
			event_type = str(payload.get("event_type", "") or event.get("event_type", "") or ev_type)
			if event_type not in {"HelpRequestCreated", "OpenThreadCreated", "ResourceFound", "LearningRecordCreated", "ChildAdviceResolved", "RobotNeedsCharge", "RobotWorryHigh"}:
				continue
			message = str(payload.get("message", "") or event.get("message", "") or event_type)
			items.append(
				{
					"seq": seq,
					"tick": int(row.get("tick", 0) or 0),
					"type": self._outbox_type(event_type),
					"event_type": event_type,
					"summary": message,
					"source": {"kind": "event_log", "seq": seq},
				}
			)
		next_cursor = max([cursor_int] + [int(x.get("seq", 0) or 0) for x in items])
		return {"items": items, "cursor": cursor_int, "next_cursor": next_cursor}

	def _build_diagnostics_payload(self, *, last_tick: int) -> dict:
		workflow_errors: list[dict] = []
		for row in self._all_logs_until(last_tick=last_tick):
			if str(row.get("kind", "") or "") != "event":
				continue
			event = dict(row.get("event", {}) or {})
			if str(event.get("type", "") or "") == "WorkflowDecisionError":
				workflow_errors.append(row)
		scene_cfg = self._scene_config_payload(self.active_scene_id)
		return {
			"use_llm": bool(scene_cfg.get("use_llm", False)),
			"llm_provider": str(scene_cfg.get("llm_provider", "") or ""),
			"action_provider": str(scene_cfg.get("action_provider", "") or ""),
			"planner_model": str(scene_cfg.get("planner_model", "") or ""),
			"grounder_model": str(scene_cfg.get("grounder_model", "") or ""),
			"llm_log_count": 0,
			"recent_llm_events": [],
			"workflow_error_count": len(workflow_errors),
			"config_path": str(scene_cfg.get("config_path", "") or ""),
		}

	@staticmethod
	def _outbox_type(event_type: str) -> str:
		if event_type in {"HelpRequestCreated", "RobotNeedsCharge", "RobotWorryHigh"}:
			return "help_request"
		if event_type == "OpenThreadCreated":
			return "open_thread"
		if event_type in {"LearningRecordCreated", "ChildAdviceResolved"}:
			return "reflection"
		return "event"


class CheckpointViewerHandler(BaseHTTPRequestHandler):
	server_version = "CheckpointViewer/1.0"

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		query = parse_qs(parsed.query, keep_blank_values=False)
		if parsed.path == "/api/scenes":
			self._write_json(self.server.viewer_data.scenes_payload())
			return
		if parsed.path == "/api/manifest":
			self._write_json(self.server.viewer_data.manifest_payload())
			return
		if parsed.path == "/api/companion/config":
			self._write_json(self.server.viewer_data.companion_config_payload())
			return
		if parsed.path == "/api/companion/state":
			scene_id = str((query.get("scene_id", [""])[0] or "")).strip()
			agent_id = str((query.get("agent_id", [""])[0] or "")).strip()
			cursor_raw = str((query.get("cursor", ["0"])[0] or "0")).strip()
			cursor = int(cursor_raw or 0)
			self._write_json(self.server.viewer_data.companion_state_payload(scene_id=scene_id, cursor=cursor, agent_id=agent_id))
			return
		if parsed.path == "/api/companion/outbox":
			scene_id = str((query.get("scene_id", [""])[0] or "")).strip()
			cursor_raw = str((query.get("cursor", ["0"])[0] or "0")).strip()
			cursor = int(cursor_raw or 0)
			self._write_json(self.server.viewer_data.companion_outbox_payload(scene_id=scene_id, cursor=cursor))
			return
		if parsed.path.startswith("/api/tick/"):
			tick_text = unquote(parsed.path.removeprefix("/api/tick/")).strip()
			if not tick_text:
				self._write_error(HTTPStatus.BAD_REQUEST, "tick is required")
				return
			try:
				tick = int(tick_text)
				payload = self.server.viewer_data.frame_payload(tick)
			except Exception as error:
				self._write_error(HTTPStatus.BAD_REQUEST, str(error))
				return
			self._write_json(payload)
			return
		self._serve_static(parsed.path)

	def do_POST(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path == "/api/scenes/select":
			try:
				body = self._read_json_body()
				payload = self.server.viewer_data.switch_scene(str(body.get("scene_id", "") or ""))
			except Exception as error:
				self._write_error(HTTPStatus.BAD_REQUEST, str(error))
				return
			self._write_json(payload)
			return
		self._write_error(HTTPStatus.NOT_FOUND, "not found")

	def log_message(self, format: str, *args) -> None:
		print(f"{self.address_string()} - {format % args}")

	def _read_json_body(self) -> dict:
		length = int(self.headers.get("Content-Length", "0") or 0)
		if length <= 0:
			return {}
		data = self.rfile.read(length)
		payload = json.loads(data.decode("utf-8"))
		if not isinstance(payload, dict):
			raise ValueError("request body must be a JSON object")
		return payload

	def _serve_static(self, request_path: str) -> None:
		relative = unquote(request_path.lstrip("/")) or "checkpoint_viewer.html"
		path = (TOOLS_DIR / relative).resolve()
		if not str(path).startswith(str(TOOLS_DIR.resolve())) or not path.is_file():
			self._write_error(HTTPStatus.NOT_FOUND, "not found")
			return
		content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
		data = path.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _write_json(self, payload: dict) -> None:
		data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _write_error(self, status: HTTPStatus, message: str) -> None:
		data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)


class CheckpointViewerServer(ThreadingHTTPServer):
	def __init__(self, server_address: tuple[str, int], handler_class, viewer_data: ArchiveViewerData) -> None:
		super().__init__(server_address, handler_class)
		self.viewer_data = viewer_data


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Serve checkpoint viewer for run archives.")
	parser.add_argument("--archive-root", default=str(ROOT_DIR / "checkpoints"), help="Directory that contains archive scene directories.")
	parser.add_argument("--archive-dir", dest="archive_root", help=argparse.SUPPRESS)
	parser.add_argument("--scene", default="", help="Initial archive scene id.")
	parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
	parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind.")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	viewer_data = ArchiveViewerData(
		Path(args.archive_root),
		scene_id=str(args.scene or ""),
	)
	server = CheckpointViewerServer((str(args.host), int(args.port)), CheckpointViewerHandler, viewer_data)
	url = f"http://{args.host}:{args.port}/checkpoint_viewer.html"
	print(f"Serving checkpoint viewer at {url}")
	print(f"Archive root: {viewer_data.archive_root}")
	print(f"Active scene: {viewer_data.active_scene_id}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()


if __name__ == "__main__":
	main()
