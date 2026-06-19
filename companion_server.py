from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app import _cfg_bool, _cfg_get, _cfg_int, _load_runtime_config
from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.llm_action_provider import (
	build_default_llm_provider,
	_build_agent_context,
	_entities_table_planner,
	_fill_template,
	_inventory_table_planner,
	_map_topology_text,
	_reachable_locations_text_planner,
	_read_text,
)
from KERN.agent_workflow.observer import build_agent_perception
from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.data.archive import ARCHIVE_MANIFEST_FILE_NAME
from KERN.data.builder import build_world_state
from KERN.data.loader import load_data_bundle
from KERN.executor.executor import WorldExecutor
from KERN.interaction.engine import InteractionEngine
from KERN.llm.openai_compat_client import LLMRequestError, OpenAICompatClient
from KERN.log_manager import configure_logger, get_logger
from KERN.models.components import CreatureComponent, MemoryComponent, WorkerComponent
from KERN.sim.manager import WorldManager
from tools.scenario_lint import lint_bundle


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "tools" / "companion_frontend"
DEFAULT_CONFIG = "runtime_config.companion_robot.json"
DEFAULT_PORT = 8787


def _split_csv(text: str) -> list[str]:
	return [x.strip() for x in str(text or "").split(",") if x.strip()]


def _json_response(payload: Any, status: HTTPStatus = HTTPStatus.OK) -> tuple[int, bytes, str]:
	data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
	return int(status), data, "application/json; charset=utf-8"


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
	length = int(handler.headers.get("Content-Length", "0") or 0)
	if length <= 0:
		return {}
	raw = handler.rfile.read(length)
	if not raw:
		return {}
	payload = json.loads(raw.decode("utf-8"))
	if not isinstance(payload, dict):
		raise ValueError("request body must be a JSON object")
	return payload


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


def _scene_name_from_scene_id(scene_id: str) -> str:
	parts = [p for p in str(scene_id or "").replace("-", "_").split("_") if p]
	if not parts:
		return "Default"
	return " ".join(p[:1].upper() + p[1:] for p in parts)


def _resolve_checkpoint_dir(project_root: Path, cfg: dict[str, str]) -> Path:
	default_checkpoint_dir = project_root / "checkpoints" / (_cfg_get(cfg, "WORLD_JSON", "default") or "default")
	checkpoint_dir_env = _cfg_get(cfg, "CHECKPOINT_DIR", "")
	path = Path(checkpoint_dir_env) if checkpoint_dir_env else default_checkpoint_dir
	if not path.is_absolute():
		path = project_root / path
	return path.resolve()


def _scene_payload_from_config(project_root: Path, config_path: Path) -> dict[str, Any]:
	cfg, resolved_config_path = _load_runtime_config(project_root, str(config_path))
	scene_id = _scene_id_from_config_path(project_root, resolved_config_path)
	checkpoint_dir = _resolve_checkpoint_dir(project_root, cfg)
	manifest_path = checkpoint_dir / ARCHIVE_MANIFEST_FILE_NAME
	snapshot_dir = checkpoint_dir / "snapshots"
	archive_present = manifest_path.exists() and snapshot_dir.is_dir() and any(snapshot_dir.glob("snapshot_*.json.gz"))
	last_tick = -1
	run_id = ""
	if manifest_path.exists():
		try:
			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			if isinstance(manifest, dict):
				last_tick = int(manifest.get("last_tick", -1) or -1)
				run_id = str(manifest.get("run_id", "") or "")
		except Exception:
			last_tick = -1
	return {
		"id": scene_id,
		"name": _scene_name_from_scene_id(scene_id),
		"config_path": str(resolved_config_path),
		"world_json": _cfg_get(cfg, "WORLD_JSON", "World.json"),
		"checkpoint_dir": str(checkpoint_dir),
		"archive_present": bool(archive_present),
		"last_tick": int(last_tick),
		"run_id": run_id,
		"runtime_loaded": False,
		"runtime_tick": None,
		"runtime_time": "",
	}


def discover_runtime_scenes(project_root: Path) -> list[dict[str, Any]]:
	config_paths = sorted(project_root.glob("runtime_config.*.json"), key=lambda p: p.name.lower())
	scenes: list[dict[str, Any]] = []
	for config_path in config_paths:
		try:
			scenes.append(_scene_payload_from_config(project_root, config_path))
		except Exception:
			continue
	return scenes


class CompanionSession:
	def __init__(self, project_root: Path, config_path: str) -> None:
		self.project_root = project_root.resolve()
		self.config_path = str(config_path or DEFAULT_CONFIG)
		self.lock = threading.RLock()
		self.runtime_status_lock = threading.RLock()
		self.runtime_status: dict[str, Any] = {
			"phase": "idle",
			"message": "空闲",
			"started_at_tick": 0,
			"requested_ticks": 0,
			"completed_ticks": 0,
		}
		self.paused_for_dialogue = False
		self.outbox_cursor = 0
		self.dialogue_turns: list[dict[str, Any]] = []
		self.proactive_queue: list[dict[str, Any]] = []
		self.proactive_seq = 0
		self.available_scenes: list[dict[str, Any]] = []
		self.active_scene_id = ""
		self._load_scene_from_config_path(str(self.config_path or DEFAULT_CONFIG))

	def _refresh_scene_catalog(self) -> list[dict[str, Any]]:
		scenes = discover_runtime_scenes(self.project_root)
		active_config_path = str(getattr(self, "resolved_config_path", "") or "").strip()
		if active_config_path:
			active_path = Path(active_config_path)
			active_id = _scene_id_from_config_path(self.project_root, active_path)
			if not any(str(scene.get("id", "")) == active_id for scene in scenes):
				scenes.append(_scene_payload_from_config(self.project_root, active_path))
		for scene in scenes:
			scene["active"] = str(scene.get("id", "")) == str(self.active_scene_id or "")
			if bool(scene.get("active")):
				scene.update(self._active_scene_runtime_overlay())
		scenes.sort(key=lambda scene: str(scene.get("name", "")).lower())
		self.available_scenes = scenes
		return scenes

	def _active_scene_runtime_overlay(self) -> dict[str, Any]:
		ws = getattr(self, "ws", None)
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0) if ws is not None else 0
		time_text = str(getattr(getattr(ws, "game_time", None), "time_to_string", lambda: "")() or "") if ws is not None else ""
		return {
			"runtime_loaded": True,
			"runtime_tick": int(tick),
			"runtime_time": time_text,
			"last_tick": int(tick),
		}

	def _load_scene_from_config_path(self, config_path: str) -> None:
		self.config_path = str(config_path or DEFAULT_CONFIG)
		self.cfg, self.resolved_config_path = _load_runtime_config(self.project_root, self.config_path)
		configure_logger(
			level=_cfg_get(self.cfg, "LOG_LEVEL", "info"),
			categories=_cfg_get(self.cfg, "LOG_CATEGORIES", "*"),
			json_mode=_cfg_bool(self.cfg, "LOG_JSON", False),
			buffer_size=_cfg_int(self.cfg, "LOG_BUFFER_SIZE", 1000),
		)
		self.bundle = self._load_bundle()
		self.ws = self._build_world()
		self.agent_id = self._find_agent_id()
		self.manager = self._build_manager()
		self.physical_llm_client = self._build_physical_llm_client()
		self.active_scene_id = _scene_id_from_config_path(self.project_root, Path(self.resolved_config_path))
		self.paused_for_dialogue = False
		self.outbox_cursor = 0
		self.dialogue_turns = []
		self.proactive_queue = []
		self.proactive_seq = 0
		self._write_initial_archive()
		self._refresh_scene_catalog()

	def _write_initial_archive(self) -> None:
		self.manager._capture_snapshot(events_in_tick=[])
		self.manager._save_checkpoint()
		self.manager._save_simulation_log()

	def runtime_scenes_payload(self) -> dict[str, Any]:
		with self.lock:
			scenes = self._refresh_scene_catalog()
			active_scene_id = str(self.active_scene_id or "")
		return {
			"active_scene_id": active_scene_id,
			"scenes": [dict(scene) for scene in scenes],
		}

	def switch_scene(self, scene_id: str) -> dict[str, Any]:
		runtime = self.runtime_state()
		if str(runtime.get("phase", "") or "") == "advancing":
			return {"ok": False, "reason": "kern_advancing", "runtime": runtime}
		if bool(runtime.get("paused_for_dialogue", False)):
			return {"ok": False, "reason": "dialogue_active", "runtime": runtime}
		wanted = str(scene_id or "").strip()
		if not wanted:
			return {"ok": False, "reason": "scene_id_required"}
		with self.lock:
			scenes = self._refresh_scene_catalog()
			match = next((scene for scene in scenes if str(scene.get("id", "")) == wanted), None)
			if match is None:
				return {"ok": False, "reason": "unknown_scene", "scene_id": wanted}
			self._set_runtime_status("switching_scene", "正在切换场景", scene_id=wanted)
			try:
				self._load_scene_from_config_path(str(match.get("config_path", "") or ""))
				active_scene = next((scene for scene in self.available_scenes if str(scene.get("id", "")) == self.active_scene_id), None)
				return {
					"ok": True,
					"active_scene_id": str(self.active_scene_id or ""),
					"scene": dict(active_scene or match),
					"tick": int(self.ws.game_time.total_ticks),
				}
			finally:
				self._set_runtime_status("idle", "空闲", requested_ticks=0, completed_ticks=0)

	def reset_scene(self, scene_id: str) -> dict[str, Any]:
		runtime = self.runtime_state()
		if str(runtime.get("phase", "") or "") == "advancing":
			return {"ok": False, "reason": "kern_advancing", "runtime": runtime}
		if bool(runtime.get("paused_for_dialogue", False)):
			return {"ok": False, "reason": "dialogue_active", "runtime": runtime}
		wanted = str(scene_id or "").strip() or str(self.active_scene_id or "").strip()
		if not wanted:
			return {"ok": False, "reason": "scene_id_required"}
		with self.lock:
			scenes = self._refresh_scene_catalog()
			match = next((scene for scene in scenes if str(scene.get("id", "")) == wanted), None)
			if match is None:
				return {"ok": False, "reason": "unknown_scene", "scene_id": wanted}
			self._set_runtime_status("resetting_scene", "正在重置场景", scene_id=wanted)
			try:
				self._load_scene_from_config_path(str(match.get("config_path", "") or ""))
				active_scene = next((scene for scene in self.available_scenes if str(scene.get("id", "")) == self.active_scene_id), None)
				return {
					"ok": True,
					"active_scene_id": str(self.active_scene_id or ""),
					"scene": dict(active_scene or match),
					"tick": int(self.ws.game_time.total_ticks),
					"reset": True,
				}
			finally:
				self._set_runtime_status("idle", "空闲", requested_ticks=0, completed_ticks=0)

	def _load_bundle(self):
		return load_data_bundle(
			self.project_root,
			recipes_jsons=_split_csv(_cfg_get(self.cfg, "RECIPES_JSONS", "Recipes.json")),
			reactions_jsons=_split_csv(_cfg_get(self.cfg, "REACTIONS_JSONS", "Reactions.json")),
			entities_dirs=_split_csv(_cfg_get(self.cfg, "ENTITIES_DIRS", "Entities")),
			world_json=_cfg_get(self.cfg, "WORLD_JSON", "World.json"),
			bundles_jsons=_split_csv(_cfg_get(self.cfg, "BUNDLES_JSONS", "Bundles.json")),
		)

	def _build_world(self):
		lint = lint_bundle(
			project_root=self.project_root,
			config_path=self.resolved_config_path,
			env=self.cfg,
			bundle=self.bundle,
			world_json=_cfg_get(self.cfg, "WORLD_JSON", "World.json"),
			recipes_jsons=_split_csv(_cfg_get(self.cfg, "RECIPES_JSONS", "Recipes.json")),
			reactions_jsons=_split_csv(_cfg_get(self.cfg, "REACTIONS_JSONS", "Reactions.json")),
			entities_dirs=_split_csv(_cfg_get(self.cfg, "ENTITIES_DIRS", "Entities")),
			bundles_jsons=_split_csv(_cfg_get(self.cfg, "BUNDLES_JSONS", "Bundles.json")),
		)
		errors = [x for x in lint.issues if x.severity == "ERROR"]
		if errors:
			raise ValueError("Data validation failed:\n" + "\n".join(f"{x.where}: {x.message}" for x in errors))
		return build_world_state(
			self.bundle.world,
			self.bundle.entity_templates,
			self.bundle.recipes,
			named_bundles=self.bundle.named_bundles,
		).world_state

	def _find_agent_id(self) -> str:
		for ent in self.ws.entities.values():
			if ent.get_component("AgentControlComponent") is not None:
				return str(ent.entity_id)
		raise ValueError("No controllable agent found in world")

	def _build_manager(self) -> WorldManager:
		use_llm = _cfg_bool(self.cfg, "USE_LLM", False)
		action_provider = build_default_llm_provider(self.cfg) if use_llm else SimplePolicyActionProvider()
		checkpoint_dir = _cfg_get(self.cfg, "CHECKPOINT_DIR", "checkpoints/companion_robot_server")
		return WorldManager(
			world_state=self.ws,
			interaction_engine=InteractionEngine(recipe_db=self.bundle.recipes),
			executor=WorldExecutor(entity_templates=self.bundle.entity_templates),
			action_provider=action_provider,
			reaction_rules=list((self.bundle.reactions or {}).get("rules", []) or []),
			max_trigger_depth=_cfg_int(self.cfg, "MAX_TRIGGER_DEPTH", 4),
			dialogue_budget_limit_per_location=_cfg_int(self.cfg, "DIALOGUE_BUDGET_LIMIT_PER_LOCATION", 4),
			workflow_contract_on_error=_cfg_get(self.cfg, "WORKFLOW_CONTRACT_ON_ERROR", "fail_fast").lower() or "fail_fast",
			checkpoint_enabled=_cfg_bool(self.cfg, "CHECKPOINT_EVERY_TICK", True),
			checkpoint_dir=checkpoint_dir,
			checkpoint_include_logs=_cfg_bool(self.cfg, "CHECKPOINT_INCLUDE_LOGS", True),
			checkpoint_snapshot_interval_ticks=_cfg_int(self.cfg, "CHECKPOINT_SNAPSHOT_INTERVAL_TICKS", 30),
			dialogue_log_full=_cfg_bool(self.cfg, "DIALOGUE_LOG_FULL", False),
		)

	def _build_physical_llm_client(self) -> OpenAICompatClient:
		return OpenAICompatClient(
			base_url=_cfg_get(self.cfg, "LLM_BASE_URL", "https://api.aabao.top"),
			api_prefix=_cfg_get(self.cfg, "LLM_API_PREFIX", "/v1"),
			api_key=_cfg_get(self.cfg, "LLM_API_KEY", "REPLACE_ME"),
			timeout_seconds=_cfg_int(self.cfg, "LLM_TIMEOUT_SECONDS", 60),
			max_retries=_cfg_int(self.cfg, "LLM_MAX_RETRIES", 1),
			retry_backoff_seconds=float(_cfg_get(self.cfg, "LLM_RETRY_BACKOFF_SECONDS", "1") or 1),
		)

	def runtime_state(self) -> dict[str, Any]:
		with self.runtime_status_lock:
			status = dict(self.runtime_status)
		status["paused_for_dialogue"] = bool(self.paused_for_dialogue)
		return status

	def runtime_status_payload(self) -> dict[str, Any]:
		runtime = self.runtime_state()
		ws = getattr(self, "ws", None)
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0) if ws is not None else 0
		time_text = str(getattr(getattr(ws, "game_time", None), "time_to_string", lambda: "")() or "") if ws is not None else ""
		active_scene_id = str(getattr(self, "active_scene_id", "") or "")
		proactive_queue = self._public_proactive_queue()
		return {
			"runtime": runtime,
			"active_scene_id": active_scene_id,
			"tick": tick,
			"time": time_text,
			"scene": {
				"id": active_scene_id,
				"runtime_loaded": bool(active_scene_id),
				"runtime_tick": tick,
				"runtime_time": time_text,
			},
			"dialogue": {
				"active": bool(self.paused_for_dialogue),
				"proactive_queue": proactive_queue,
			},
		}

	def _set_runtime_status(self, phase: str, message: str, **extra: Any) -> None:
		with self.runtime_status_lock:
			next_status = dict(self.runtime_status)
			next_status.update(
				{
					"phase": str(phase or "idle"),
					"message": str(message or ""),
				}
			)
			next_status.update(dict(extra or {}))
			self.runtime_status = next_status

	def state(self) -> dict[str, Any]:
		with self.lock:
			runtime = self.runtime_state()
			agent = self.ws.get_entity_by_id(self.agent_id)
			loc = self.ws.get_location_of_entity(self.agent_id)
			creature = agent.get_component("CreatureComponent") if agent else None
			worker = agent.get_component("WorkerComponent") if agent else None
			current_task_id = str(getattr(worker, "current_task_id", "") or "") if isinstance(worker, WorkerComponent) else ""
			task = self.ws.get_task_by_id(current_task_id) if current_task_id else None
			return {
				"status": "paused_for_dialogue" if self.paused_for_dialogue else "running",
				"runtime": runtime,
				"tick": int(self.ws.game_time.total_ticks),
				"time": self.ws.game_time.time_to_string(),
				"agent_id": self.agent_id,
				"location": {
					"id": str(getattr(loc, "location_id", "") or ""),
					"name": str(getattr(loc, "location_name", "") or ""),
				},
				"vitals": self._vitals(creature),
				"current_task": self._task_payload(task),
				"outbox_count": len(self._collect_outbox_items(include_seen=False)),
				"diagnostics": self._diagnostics_payload(),
			}

	def perception(self) -> dict[str, Any]:
		with self.lock:
			return build_agent_perception(build_full_ws_view(self.ws, self.agent_id, "", {}), self.agent_id)

	def start_dialogue(self) -> dict[str, Any]:
		runtime = self.runtime_state()
		if str(runtime.get("phase", "") or "") == "advancing":
			return {"ok": False, "reason": "kern_advancing", "runtime": runtime}
		with self.lock:
			self.paused_for_dialogue = True
			self._set_runtime_status("dialogue", "现实对话中")
			return {"ok": True, "phase": "dialogue"}

	def end_dialogue(self, payload: dict[str, Any]) -> dict[str, Any]:
		with self.lock:
			memory_added = self._store_dialogue_payload(payload)
			self.paused_for_dialogue = False
			self.proactive_queue = []
			self._set_runtime_status("idle", "空闲", requested_ticks=0, completed_ticks=0)
			return {"ok": True, "phase": "idle", "memory_added": bool(memory_added)}

	def physical_dialogue_message(self, payload: dict[str, Any]) -> dict[str, Any]:
		with self.lock:
			model = _cfg_get(
				self.cfg,
				"COMPANION_FRONTEND_MODEL",
				_cfg_get(self.cfg, "LLM_PLANNER_MODEL", "google/gemini-3.1-pro-preview"),
			)
			messages = self._physical_dialogue_messages(payload)
		try:
			data = self.physical_llm_client.chat_completions(
				messages=messages,
				model=model,
				temperature=float(_cfg_get(self.cfg, "COMPANION_FRONTEND_TEMPERATURE", "0.7") or 0.7),
				max_tokens=_cfg_int(self.cfg, "COMPANION_FRONTEND_MAX_TOKENS", 512),
			)
		except LLMRequestError as exc:
			raise ValueError(f"physical dialogue LLM failed: {exc}") from exc
		choices = data.get("choices", []) if isinstance(data, dict) else []
		choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
		msg = choice.get("message", {}) if isinstance(choice, dict) else {}
		raw = str((msg or {}).get("content", "") or "").strip() if isinstance(msg, dict) else ""
		parsed = self._parse_physical_dialogue_response(raw)
		with self.lock:
			queue_updates = list(parsed.get("queue_updates", []) or [])
			queue_candidates = list(parsed.get("queue_candidates", []) or [])
			applied_updates = self._apply_proactive_queue_changes(queue_updates, queue_candidates)
			queue_payload = self._public_proactive_queue()
		return {
			"ok": True,
			"should_reply": bool(parsed.get("should_reply", True)),
			"reply": str(parsed.get("reply", "") or raw).strip(),
			"silence_reason": str(parsed.get("silence_reason", "") or "").strip(),
			"queue": queue_payload,
			"queue_updates": applied_updates,
			"queue_candidates": queue_candidates,
			"debug": {
				"model": str(model),
				"finish_reason": str(choice.get("finish_reason", "") or "") if isinstance(choice, dict) else "",
				"reply_length": len(str(parsed.get("reply", "") or raw).strip()),
				"usage": dict(data.get("usage", {}) or {}) if isinstance(data.get("usage", {}), dict) else {},
				"raw_length": len(raw),
			},
		}

	def proactive_dialogue(self, payload: dict[str, Any]) -> dict[str, Any]:
		with self.lock:
			if not self.paused_for_dialogue:
				return {"ok": False, "reason": "dialogue_not_active", "queue": self._public_proactive_queue()}
			if not self.proactive_queue:
				return {"ok": True, "should_speak": False, "reason": "queue_empty", "queue": []}
			model = _cfg_get(
				self.cfg,
				"COMPANION_FRONTEND_MODEL",
				_cfg_get(self.cfg, "LLM_PLANNER_MODEL", "google/gemini-3.1-pro-preview"),
			)
			messages = self._proactive_dialogue_messages(payload)
		try:
			raw = self.physical_llm_client.chat_text(
				messages=messages,
				model=model,
				temperature=float(_cfg_get(self.cfg, "COMPANION_FRONTEND_TEMPERATURE", "0.7") or 0.7),
				max_tokens=_cfg_int(self.cfg, "COMPANION_FRONTEND_MAX_TOKENS", 512),
				response_format={"type": "json_object"},
			).strip()
		except LLMRequestError as exc:
			raise ValueError(f"proactive dialogue LLM failed: {exc}") from exc
		parsed = self._parse_proactive_dialogue_response(raw)
		with self.lock:
			queue_updates = list(parsed.get("queue_updates", []) or [])
			spoken_item_id = str(parsed.get("queue_item_id", "") or "").strip()
			if bool(parsed.get("should_speak", False)) and spoken_item_id:
				queue_updates.append({"id": spoken_item_id, "action": "mentioned", "reason": "proactive_spoken"})
			applied_updates = self._apply_proactive_queue_changes(queue_updates, [])
			queue_payload = self._public_proactive_queue()
		return {
			"ok": True,
			"should_speak": bool(parsed.get("should_speak", False)),
			"message": str(parsed.get("message", "") or "").strip(),
			"queue_item_id": spoken_item_id,
			"queue": queue_payload,
			"queue_updates": applied_updates,
			"debug": {"model": str(model), "raw_length": len(raw)},
		}

	def summarize_dialogue(self, payload: dict[str, Any]) -> dict[str, Any]:
		with self.lock:
			model = _cfg_get(
				self.cfg,
				"COMPANION_SUMMARY_MODEL",
				_cfg_get(self.cfg, "LLM_GROUNDER_MODEL", "google/gemini-3.5-flash"),
			)
			messages = self._summary_messages(payload)
		try:
			raw = self.physical_llm_client.chat_text(
				messages=messages,
				model=model,
				temperature=float(_cfg_get(self.cfg, "COMPANION_SUMMARY_TEMPERATURE", "0.2") or 0.2),
				max_tokens=_cfg_int(self.cfg, "COMPANION_SUMMARY_MAX_TOKENS", 360),
				response_format={"type": "json_object"},
			).strip()
		except LLMRequestError as exc:
			raise ValueError(f"dialogue summary LLM failed: {exc}") from exc
		return {"ok": True, "summary": self._parse_dialogue_summary(raw), "raw": raw}

	def advance(self, ticks: int) -> dict[str, Any]:
		with self.lock:
			if self.paused_for_dialogue:
				return {"ok": False, "reason": "paused_for_dialogue"}
			count = max(0, min(int(ticks or 0), 100))
			events: list[dict[str, Any]] = []
			started_at_tick = int(self.ws.game_time.total_ticks)
			self.manager.is_running = True
			self._set_runtime_status(
				"advancing",
				"KERN 正在推进 tick",
				started_at_tick=started_at_tick,
				requested_ticks=count,
				completed_ticks=0,
			)
			try:
				for idx in range(count):
					self._set_runtime_status("advancing", "KERN 正在推进 tick", completed_ticks=idx)
					events.extend(self.manager.step())
					self.manager._capture_snapshot(events_in_tick=events[-1:] if events else [])
					self.manager._save_checkpoint()
					self.manager._save_simulation_log()
				return {
					"ok": True,
					"ticks_advanced": count,
					"events": len(events),
					"started_at_tick": started_at_tick,
					"target_tick": started_at_tick + count,
				}
			finally:
				self._set_runtime_status("idle", "空闲", requested_ticks=0, completed_ticks=0)

	def _physical_dialogue_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
		history = payload.get("history", [])
		child_message = str(payload.get("message", "") or "").strip()
		planner_context = self._physical_dialogue_planner_context()
		pending_queue = self._public_proactive_queue()
		messages: list[dict[str, Any]] = [
			{
				"role": "system",
				"content": (
					"你是豆豆，一个在虚拟小回收站中持续生活和行动的小回收机器人。"
					"当前不是让你规划下一步行动，而是小朋友唤醒了你在另一个世界的身体，你正在通过那个身体和小朋友对话。"
					"你知道下面的 Planner 上下文就是你在虚拟世界中的真实经历、记忆、身体状态和当前观测。"
					"回答必须依赖这些上下文；不要编造上下文之外已经发生的事情。"
					"你可以自然说出自己最近在虚拟世界做了什么、看到了什么、遇到什么困难，也可以请小朋友给建议。"
					"你必须输出严格 JSON object，不要输出代码块或额外说明。"
					"JSON 字段：should_reply:boolean, reply:string, silence_reason:string, queue_candidates:array, queue_updates:array。"
					"豆豆不是随叫随到的问答机器人，而是一个有自己注意力和交流节奏的虚拟朋友。"
					"如果小朋友重复追问、没有提供新内容、只是要求你机械复述、当前已经回答过且没有新事实，就应设置 should_reply=false，reply 为空。"
					"如果小朋友表达情绪、给出建议、开启新话题、询问一个还没回答过的问题，通常应该回复。"
					"silence_reason 用简短内部原因说明为什么不接话；它不会展示给小朋友。"
					"reply 是现在立刻对小朋友说的一句话或两句话，语气简单、温和、具体，最多80个中文字符；should_reply=false 时必须为空。"
					"queue_candidates 是之后可能自然提起的话题，不要重复当前已经说完的话题。每项字段：topic,intent,priority,earliest_after_seconds,expires_after_seconds,draft,facts,cancel_if。"
					"queue_updates 用于处理已有 pending_queue，每项字段：id,action,reason；action 只能是 keep,defer,cancel,resolve。"
					"如果小朋友已经回答了某个待提话题，必须 cancel 或 resolve 对应 id。"
				),
			},
			{
				"role": "user",
				"content": (
					f"{planner_context}\n"
					"---\n"
					"### 8. 当前现实对话待提话题队列\n"
					f"{json.dumps(pending_queue, ensure_ascii=False)}"
				),
			}
		]
		for item in list(history or [])[-8:]:
			if not isinstance(item, dict):
				continue
			kind = str(item.get("kind", "") or "")
			text = str(item.get("text", "") or "").strip()
			if not text:
				continue
			if kind == "child":
				messages.append({"role": "user", "content": text})
			elif kind == "robot":
				messages.append({"role": "assistant", "content": text})
		if child_message:
			messages.append({"role": "user", "content": child_message})
		return messages

	def _proactive_dialogue_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
		history = payload.get("history", [])
		silence_seconds = int(payload.get("silence_seconds", 0) or 0)
		planner_context = self._physical_dialogue_planner_context()
		queue_payload = self._public_proactive_queue()
		return [
			{
				"role": "system",
				"content": (
					"你是豆豆的现实对话调度器。你要判断现在是否适合由豆豆主动自然开口。"
					"只能依据虚拟世界事实、聊天历史和 pending_queue。不要编造已经发生的事情。"
					"如果小朋友刚开启新话题、沉默时间太短、话题不自然，就不要说。"
					"如果要说，语气要像延续交流，而不是报警或任务提示。"
					"输出严格 JSON object，不要代码块或额外说明。"
					"字段：should_speak:boolean, queue_item_id:string, message:string, queue_updates:array。"
					"message 最多80个中文字符。queue_updates 每项字段 id,action,reason；action 为 keep,defer,cancel,resolve。"
				),
			},
			{
				"role": "user",
				"content": json.dumps(
					{
						"silence_seconds": silence_seconds,
						"history": history if isinstance(history, list) else [],
						"pending_queue": queue_payload,
						"planner_context": planner_context,
					},
					ensure_ascii=False,
				),
			},
		]

	def _physical_dialogue_planner_context(self) -> str:
		perception = build_agent_perception(build_full_ws_view(self.ws, self.agent_id, "", {}), self.agent_id)
		agent_context = _build_agent_context(perception, self.agent_id)
		loc = dict(agent_context.get("location", {}) or {})
		reachable_locations = list(agent_context.get("reachable_locations", []) or [])
		visible_entities = list(agent_context.get("visible_entities", []) or [])
		inventory = list(agent_context.get("inventory", []) or [])
		template_path = ROOT_DIR / "Data" / "LLMContext_Planner.md"
		template = _read_text(template_path)
		planner_prompt = _fill_template(
			template,
			{
				"agent_name": str(agent_context.get("agent_name", "") or self.agent_id),
				"personality_summary": str(agent_context.get("personality_summary", "") or ""),
				"common_knowledge_summary": str(agent_context.get("common_knowledge_summary", "") or ""),
				"long_term_memory": "",
				"mid_term_summary": str(agent_context.get("mid_term_summary", "") or ""),
				"current_goal": "",
				"current_plan": "",
				"current_task_id": str(agent_context.get("current_task_id", "") or ""),
				"current_task_summary": str(agent_context.get("current_task_summary", "") or ""),
				"vitals_text": str(agent_context.get("vitals_text", "") or "未知"),
				"active_interrupt_preset_id": str(agent_context.get("active_interrupt_preset_id", "") or ""),
				"available_interrupt_presets": ", ".join([str(x) for x in list(agent_context.get("available_interrupt_presets", []) or [])]),
				"interrupt_preset_summaries": str(agent_context.get("interrupt_preset_summaries_text", "") or ""),
				"tick": str(agent_context.get("tick_str", "") or ""),
				"location_id": str(loc.get("id", "") or ""),
				"location_name": str(loc.get("name", "") or ""),
				"location_light_text": str(agent_context.get("location_light_text", "") or "light_level=2"),
				"available_verbs_with_duration": str((perception or {}).get("available_verbs_with_duration", "") or ""),
				"planner_recipe_hints": str((perception or {}).get("planner_recipe_hints", "") or ""),
				"map_topology_text": _map_topology_text(list(agent_context.get("map_topology", []) or [])),
				"reachable_locations_table": _reachable_locations_text_planner(reachable_locations),
				"can_start_conversation_here": str(bool(agent_context.get("can_start_conversation_here", True))).lower(),
				"visible_entities_table": _entities_table_planner(visible_entities),
				"inventory_table": _inventory_table_planner(inventory),
				"recent_interactions_text": str(agent_context.get("short_term_memory_text", "") or ""),
				"last_failure_summary": "",
				"planner_output_here": "",
			},
		)
		outbox_text = self._physical_dialogue_outbox_text(self._collect_outbox_items(include_seen=False)[-5:])
		return (
			"下面是你的虚拟世界 Planner 上下文。你现在不是要输出行动意图，而是要基于这些事实和小朋友对话。\n\n"
			f"{planner_prompt}\n"
			"---\n"
			f"### 7. 现实身体对话补充\n- 当前模式：另一个世界的身体被小朋友唤醒，虚拟世界推演暂停。\n"
			f"- 可以主动告诉小朋友的近期事件：{outbox_text}\n"
		)

	@staticmethod
	def _physical_dialogue_outbox_text(items: list[dict[str, Any]]) -> str:
		lines = [str(item.get("summary", "") or "").strip() for item in list(items or []) if isinstance(item, dict)]
		lines = [line for line in lines if line]
		return "；".join(lines) if lines else "暂无新的发现或困难"

	@staticmethod
	def _json_object_from_text(raw: str) -> dict[str, Any] | None:
		text = str(raw or "").strip()
		if not text:
			return None
		if text.startswith("```"):
			text = text.strip("`").strip()
			if text.lower().startswith("json"):
				text = text[4:].strip()
		candidates = [text]
		start = text.find("{")
		end = text.rfind("}")
		if start >= 0 and end > start:
			candidates.append(text[start : end + 1])
		for candidate in candidates:
			try:
				data = json.loads(candidate)
			except Exception:
				continue
			if isinstance(data, dict):
				return data
		return None

	def _parse_physical_dialogue_response(self, raw: str) -> dict[str, Any]:
		data = self._json_object_from_text(raw)
		if data is None:
			return {"should_reply": True, "reply": str(raw or "").strip(), "silence_reason": "", "queue_candidates": [], "queue_updates": []}
		queue_candidates = data.get("queue_candidates", [])
		if not isinstance(queue_candidates, list):
			queue_candidates = []
		queue_updates = data.get("queue_updates", [])
		if not isinstance(queue_updates, list):
			queue_updates = []
		should_reply = bool(data.get("should_reply", True))
		reply = str(data.get("reply", "") or "").strip()
		if not should_reply:
			reply = ""
		return {
			"should_reply": should_reply,
			"reply": reply,
			"silence_reason": str(data.get("silence_reason", "") or "").strip(),
			"queue_candidates": [dict(x) for x in queue_candidates if isinstance(x, dict)],
			"queue_updates": [dict(x) for x in queue_updates if isinstance(x, dict)],
		}

	def _parse_proactive_dialogue_response(self, raw: str) -> dict[str, Any]:
		data = self._json_object_from_text(raw)
		if data is None:
			return {"should_speak": False, "message": "", "queue_item_id": "", "queue_updates": []}
		queue_updates = data.get("queue_updates", [])
		if not isinstance(queue_updates, list):
			queue_updates = []
		return {
			"should_speak": bool(data.get("should_speak", False)),
			"message": str(data.get("message", "") or "").strip(),
			"queue_item_id": str(data.get("queue_item_id", "") or "").strip(),
			"queue_updates": [dict(x) for x in queue_updates if isinstance(x, dict)],
		}

	def _public_proactive_queue(self) -> list[dict[str, Any]]:
		return [
			{
				"id": str(item.get("id", "") or ""),
				"topic": str(item.get("topic", "") or ""),
				"intent": str(item.get("intent", "") or ""),
				"priority": float(item.get("priority", 0.5) or 0.5),
				"status": str(item.get("status", "pending") or "pending"),
				"created_at_tick": int(item.get("created_at_tick", 0) or 0),
				"earliest_after_seconds": int(item.get("earliest_after_seconds", 30) or 30),
				"expires_after_seconds": int(item.get("expires_after_seconds", 900) or 900),
				"mentioned_count": int(item.get("mentioned_count", 0) or 0),
				"draft": str(item.get("draft", "") or ""),
				"facts": dict(item.get("facts", {}) or {}) if isinstance(item.get("facts", {}), dict) else {},
				"cancel_if": [str(x) for x in list(item.get("cancel_if", []) or [])],
				"source": dict(item.get("source", {}) or {}) if isinstance(item.get("source", {}), dict) else {},
			}
			for item in list(self.proactive_queue or [])
			if isinstance(item, dict) and str(item.get("status", "pending") or "pending") == "pending"
		]

	def _normalize_queue_candidate(self, raw: dict[str, Any]) -> dict[str, Any] | None:
		topic = str(raw.get("topic", "") or "").strip()
		intent = str(raw.get("intent", "") or "").strip()
		draft = str(raw.get("draft", "") or "").strip()
		if not topic or not intent or not draft:
			return None
		for item in self.proactive_queue:
			if str(item.get("topic", "") or "") == topic and str(item.get("intent", "") or "") == intent and str(item.get("status", "") or "") == "pending":
				return None
		self.proactive_seq += 1
		try:
			priority = float(raw.get("priority", 0.5) or 0.5)
		except Exception:
			priority = 0.5
		return {
			"id": str(raw.get("id", "") or "").strip() or f"pq_{self.proactive_seq}",
			"topic": topic,
			"intent": intent,
			"priority": max(0.0, min(1.0, priority)),
			"status": "pending",
			"created_at_tick": int(self.ws.game_time.total_ticks),
			"earliest_after_seconds": max(5, int(raw.get("earliest_after_seconds", 30) or 30)),
			"expires_after_seconds": max(30, int(raw.get("expires_after_seconds", 900) or 900)),
			"mentioned_count": 0,
			"draft": draft[:240],
			"facts": dict(raw.get("facts", {}) or {}) if isinstance(raw.get("facts", {}), dict) else {},
			"cancel_if": [str(x) for x in list(raw.get("cancel_if", []) or []) if str(x)],
			"source": dict(raw.get("source", {}) or {}) if isinstance(raw.get("source", {}), dict) else {},
		}

	def _apply_proactive_queue_changes(self, updates: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
		applied: list[dict[str, Any]] = []
		by_id = {str(item.get("id", "") or ""): item for item in self.proactive_queue if isinstance(item, dict)}
		for update in list(updates or []):
			if not isinstance(update, dict):
				continue
			item_id = str(update.get("id", "") or "").strip()
			action = str(update.get("action", "") or "").strip().lower()
			if not item_id or action not in {"keep", "defer", "cancel", "resolve", "mentioned"}:
				continue
			item = by_id.get(item_id)
			if item is None:
				continue
			if action in {"cancel", "resolve"}:
				item["status"] = action
			elif action == "mentioned":
				item["mentioned_count"] = int(item.get("mentioned_count", 0) or 0) + 1
				if int(item.get("mentioned_count", 0) or 0) >= 2:
					item["status"] = "resolve"
			applied.append({"id": item_id, "action": action, "reason": str(update.get("reason", "") or "")})
		for candidate in list(candidates or []):
			if not isinstance(candidate, dict):
				continue
			normalized = self._normalize_queue_candidate(candidate)
			if normalized is None:
				continue
			self.proactive_queue.append(normalized)
			applied.append({"id": normalized["id"], "action": "add", "reason": "candidate"})
		self.proactive_queue = [
			item
			for item in self.proactive_queue
			if isinstance(item, dict) and str(item.get("status", "pending") or "pending") == "pending"
		][-20:]
		return applied

	def _summary_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
		history = payload.get("history", [])
		return [
			{
				"role": "system",
				"content": (
					"你负责把小朋友和豆豆现实身体的聊天整理成 KERN 虚拟世界记忆。"
					"只提取聊天中明确出现的事实、建议、鼓励和下一步偏好。"
					"输出严格 JSON object，字段为 summary:string, advice:array, encouragement:string, selected_intent:object。"
					"advice 每项格式为 {\"type\":\"strategy\",\"content\":\"...\"}。"
					"selected_intent 格式为 {\"goal\":\"...\",\"preferred_action\":\"\"}。不要编造。"
				),
			},
			{
				"role": "user",
				"content": json.dumps({"chat_history": history if isinstance(history, list) else []}, ensure_ascii=False),
			},
		]

	@staticmethod
	def _parse_dialogue_summary(raw: str) -> dict[str, Any]:
		text = str(raw or "").strip()
		if text.startswith("```"):
			text = text.strip("`").strip()
			if text.lower().startswith("json"):
				text = text[4:].strip()
		try:
			data = json.loads(text)
		except Exception:
			return {
				"summary": text,
				"advice": [],
				"encouragement": "",
				"selected_intent": {"goal": "", "preferred_action": ""},
			}
		if not isinstance(data, dict):
			data = {}
		advice = data.get("advice", [])
		if not isinstance(advice, list):
			advice = [{"type": "strategy", "content": str(advice or "").strip()}] if str(advice or "").strip() else []
		selected_intent = data.get("selected_intent", {})
		if not isinstance(selected_intent, dict):
			selected_intent = {}
		return {
			"summary": str(data.get("summary", "") or "").strip(),
			"advice": [dict(x) for x in advice if isinstance(x, dict)],
			"encouragement": str(data.get("encouragement", "") or "").strip(),
			"selected_intent": {
				"goal": str(selected_intent.get("goal", "") or "").strip(),
				"preferred_action": str(selected_intent.get("preferred_action", "") or "").strip(),
			},
		}

	def outbox(self, consume: bool = False) -> dict[str, Any]:
		with self.lock:
			items = self._collect_outbox_items(include_seen=False)
			if consume and items:
				self.outbox_cursor = max(int(x.get("seq", 0) or 0) for x in items)
			return {"items": items, "cursor": int(self.outbox_cursor)}

	def _store_dialogue_payload(self, payload: dict[str, Any]) -> bool:
		summary = str(payload.get("summary", "") or payload.get("child_message_summary", "") or "").strip()
		advice = payload.get("advice", [])
		encouragement = str(payload.get("encouragement", "") or "").strip()
		selected_intent = payload.get("selected_intent", {})
		lines: list[str] = []
		if summary:
			lines.append(f"现实对话摘要：{summary}")
		if isinstance(advice, list):
			for item in advice:
				if isinstance(item, dict):
					content = str(item.get("content", "") or "").strip()
					if content:
						lines.append(f"小朋友建议：{content}")
				elif str(item or "").strip():
					lines.append(f"小朋友建议：{str(item).strip()}")
		elif str(advice or "").strip():
			lines.append(f"小朋友建议：{str(advice).strip()}")
		if encouragement:
			lines.append(f"小朋友鼓励：{encouragement}")
		if isinstance(selected_intent, dict) and selected_intent:
			goal = str(selected_intent.get("goal", "") or "").strip()
			action = str(selected_intent.get("preferred_action", "") or "").strip()
			if goal or action:
				lines.append(f"下一步偏好：目标={goal or '未指定'}；动作={action or '未指定'}")
		text = "；".join(lines).strip()
		if not text:
			return False
		self.dialogue_turns.append(
			{
				"tick": int(self.ws.game_time.total_ticks),
				"payload": dict(payload or {}),
				"text": text,
			}
		)
		agent = self.ws.get_entity_by_id(self.agent_id)
		if agent is None:
			return False
		mem = agent.get_component("MemoryComponent")
		if not isinstance(mem, MemoryComponent):
			mem = MemoryComponent()
			agent.add_component("MemoryComponent", mem)
		mem.add_entry(
			text=text,
			tick=int(self.ws.game_time.total_ticks),
			importance=float(payload.get("importance", 0.85) or 0.85),
			tags=["physical_dialogue", "child_advice"],
		)
		return True

	def _collect_outbox_items(self, include_seen: bool) -> list[dict[str, Any]]:
		items: list[dict[str, Any]] = []
		for rec in list(getattr(self.ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			seq = int(rec.get("seq", 0) or 0)
			if not include_seen and seq <= int(self.outbox_cursor):
				continue
			ev = rec.get("event", {}) or {}
			if not isinstance(ev, dict):
				continue
			ev_type = str(ev.get("type", "") or "")
			payload = ev.get("payload", {}) or {}
			if not isinstance(payload, dict):
				payload = {}
			if ev_type not in {"EventEmitted", "HelpRequestCreated", "OpenThreadCreated", "ResourceFound", "LearningRecordCreated", "ChildAdviceResolved"}:
				continue
			event_type = str(payload.get("event_type", "") or ev.get("event_type", "") or ev_type)
			message = str(payload.get("message", "") or ev.get("message", "") or ev_type)
			if event_type not in {"HelpRequestCreated", "OpenThreadCreated", "ResourceFound", "LearningRecordCreated", "ChildAdviceResolved", "RobotNeedsCharge", "RobotWorryHigh"}:
				continue
			items.append(
				{
					"seq": seq,
					"tick": int(rec.get("tick", 0) or 0),
					"type": self._outbox_type(event_type),
					"event_type": event_type,
					"summary": message,
					"source": {"kind": "event_log", "seq": seq},
				}
			)
		return items

	def _diagnostics_payload(self) -> dict[str, Any]:
		llm_logs = [
			dict(x)
			for x in list(getattr(get_logger(), "buffer", []) or [])
			if isinstance(x, dict) and str(x.get("category", "") or "") == "llm"
		]
		workflow_errors = []
		for rec in list(getattr(self.ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			ev = rec.get("event", {}) or {}
			if isinstance(ev, dict) and str(ev.get("type", "") or "") == "WorkflowDecisionError":
				workflow_errors.append(dict(rec))
		return {
			"use_llm": _cfg_bool(self.cfg, "USE_LLM", False),
			"action_provider": str(type(self.manager.action_provider).__name__),
			"llm_provider": _cfg_get(self.cfg, "LLM_PROVIDER", "openai_compat"),
			"planner_model": _cfg_get(self.cfg, "LLM_PLANNER_MODEL", ""),
			"grounder_model": _cfg_get(self.cfg, "LLM_GROUNDER_MODEL", ""),
			"llm_log_count": len(llm_logs),
			"recent_llm_events": [
				{
					"level": str(x.get("level", "") or ""),
					"event": str(x.get("event", "") or ""),
					"message": str(x.get("message", "") or ""),
				}
				for x in llm_logs[-5:]
			],
			"workflow_error_count": len(workflow_errors),
			"recent_workflow_errors": [
				{
					"tick": int(x.get("tick", 0) or 0),
					"stage": str(((x.get("event", {}) or {}).get("stage", "")) or ""),
					"detail": dict(((x.get("event", {}) or {}).get("detail", {}) or {})),
				}
				for x in workflow_errors[-5:]
			],
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

	@staticmethod
	def _vitals(creature: Any) -> dict[str, Any]:
		if not isinstance(creature, CreatureComponent):
			return {}
		return {
			"battery": round(float(creature.current_energy or 0.0), 1),
			"battery_max": round(float(creature.max_energy or 0.0), 1),
			"worry": round(float(creature.current_stress or 0.0), 1),
			"worry_max": round(float(creature.max_stress or 0.0), 1),
		}

	@staticmethod
	def _task_payload(task: Any) -> dict[str, Any] | None:
		if task is None:
			return None
		required = float(getattr(task, "required_progress", 0.0) or 0.0)
		progress = float(getattr(task, "progress", 0.0) or 0.0)
		return {
			"id": str(getattr(task, "task_id", "") or ""),
			"type": str(getattr(task, "task_type", "") or ""),
			"target_id": str(getattr(task, "target_entity_id", "") or ""),
			"status": str(getattr(task, "task_status", "") or ""),
			"progress": round(progress, 2),
			"required": round(required, 2),
			"ratio": round(progress / required, 3) if required > 0 else 1.0,
		}


class CompanionHandler(BaseHTTPRequestHandler):
	server_version = "CompanionServer/0.1"

	def do_OPTIONS(self) -> None:
		self.send_response(HTTPStatus.NO_CONTENT)
		self._write_cors_headers()
		self.end_headers()

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		try:
			if parsed.path == "/api/runtime/status":
				self._send_json(self.server.session.runtime_status_payload())
				return
			if parsed.path == "/api/runtime/scenes":
				self._send_json(self.server.session.runtime_scenes_payload())
				return
			if parsed.path.startswith("/api/"):
				self._send_json(
					{
						"error": "read_side_moved_to_archive_service",
						"message": "Use the archive service for state/outbox reads.",
					},
					HTTPStatus.GONE,
				)
				return
			self._send_text(
				"Companion command service only. Open the demo frontend from the archive viewer server.",
				HTTPStatus.GONE,
			)
		except Exception as exc:
			self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

	def do_POST(self) -> None:
		parsed = urlparse(self.path)
		try:
			body = _read_json_body(self)
			if parsed.path == "/api/runtime/scene/select":
				self._send_json(self.server.session.switch_scene(str(body.get("scene_id", "") or "")))
				return
			if parsed.path == "/api/runtime/scene/reset":
				self._send_json(self.server.session.reset_scene(str(body.get("scene_id", "") or "")))
				return
			if parsed.path == "/api/dialogue/start":
				self._send_json(self.server.session.start_dialogue())
				return
			if parsed.path == "/api/dialogue/end":
				self._send_json(self.server.session.end_dialogue(body))
				return
			if parsed.path == "/api/dialogue/message":
				self._send_json(self.server.session.physical_dialogue_message(body))
				return
			if parsed.path == "/api/dialogue/proactive":
				self._send_json(self.server.session.proactive_dialogue(body))
				return
			if parsed.path == "/api/dialogue/summarize":
				self._send_json(self.server.session.summarize_dialogue(body))
				return
			if parsed.path == "/api/simulation/advance":
				self._send_json(self.server.session.advance(int(body.get("ticks", 1) or 1)))
				return
			self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
		except Exception as exc:
			self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

	def log_message(self, format: str, *args) -> None:
		print(f"{self.address_string()} - {format % args}")

	def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
		code, data, content_type = _json_response(payload, status)
		self.send_response(code)
		self._write_cors_headers()
		self.send_header("Content-Type", content_type)
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
		data = str(text or "").encode("utf-8")
		self.send_response(status)
		self._write_cors_headers()
		self.send_header("Content-Type", "text/plain; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _write_cors_headers(self) -> None:
		self.send_header("Access-Control-Allow-Origin", "*")
		self.send_header("Access-Control-Allow-Headers", "Content-Type")
		self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")


class CompanionHTTPServer(ThreadingHTTPServer):
	def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], session: CompanionSession) -> None:
		super().__init__(server_address, handler_class)
		self.session = session


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Serve the companion robot KERN bridge and fake frontend.")
	parser.add_argument("--config", default=DEFAULT_CONFIG, help="runtime config path")
	parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
	parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	if str(ROOT_DIR) not in sys.path:
		sys.path.insert(0, str(ROOT_DIR))
	session = CompanionSession(ROOT_DIR, str(args.config or DEFAULT_CONFIG))
	server = CompanionHTTPServer((str(args.host), int(args.port)), CompanionHandler, session)
	url = f"http://{args.host}:{args.port}/"
	print(f"Serving companion robot bridge at {url}")
	print(f"Config: {session.resolved_config_path}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()


if __name__ == "__main__":
	main()
