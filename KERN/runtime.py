from __future__ import annotations
import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_workflow.llm_action_provider import build_default_llm_provider
from .agent_workflow.simple_policy import SimplePolicyActionProvider
from .data.archive import ArchiveRecorder
from .data.builder import build_world_state
from .data.checkpoint import (
	build_simulation_log_payload_from_world_state,
	resolve_checkpoint_file,
	resolve_global_log_file,
	restore_world_state_from_checkpoint,
)
from .data.loader import load_data_bundle
from .execution_errors import is_execution_error_event
from .executor.executor import WorldExecutor
from .interaction.engine import InteractionEngine
from .log_manager import configure_logger, get_logger
from .models.world_state import WorldState
from .sim.trigger_system import TriggerSystem
from .sim.world_settlement import WorldSettlement


def _resolve_runtime_config_path(project_root: Path, config_path: str = "") -> Path:
	raw = str(config_path or "").strip()
	if not raw:
		raw = "runtime_config.json"
	p = Path(raw)
	if p.is_absolute():
		return p
	return project_root / p


def _load_runtime_config(project_root: Path, config_path: str = "") -> tuple[dict[str, str], Path]:
	resolved = _resolve_runtime_config_path(project_root, config_path)
	if not resolved.exists():
		raise FileNotFoundError(f"runtime config not found: {resolved}")
	raw = json.loads(resolved.read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"runtime config must be object with key 'env': {resolved}")
	env_raw = raw.get("env")
	if not isinstance(env_raw, dict):
		raise ValueError(f"runtime config must use {{'env': {{...}}}} format: {resolved}")
	out: dict[str, str] = {}
	for k, v in dict(env_raw).items():
		key = str(k or "").strip()
		if not key or v is None:
			continue
		out[key] = str(v)
	return out, resolved


def _cfg_get(cfg: dict[str, str], key: str, default: str = "") -> str:
	return str(cfg.get(str(key), default) or default).strip()


def _cfg_bool(cfg: dict[str, str], key: str, default: bool = False) -> bool:
	v = _cfg_get(cfg, key, "1" if default else "0").lower()
	return v in {"1", "true", "yes", "on"}


def _cfg_int(cfg: dict[str, str], key: str, default: int) -> int:
	raw = _cfg_get(cfg, key, str(default))
	try:
		return int(raw)
	except Exception:
		return int(default)


@dataclass
class KernRuntime:
	"""
	SDK entry point and runtime runner for a single KERN WorldState.

	Responsibilities:
	- Build a ready-to-run runtime from scenario/config data
	- Advance game time by runtime ticks
	- Dispatch AdvanceTick per entity
	- Build reaction effects via TriggerSystem
	- Execute effects through executor and chain follow-up reactions
	- Provide per-tick runtime services to effects/workflows
	- Record runtime snapshots, checkpoints, and simulation logs

	Explanation:
	- This class does not directly write WorldState details; specific writes should be done by executor.
	- Product orchestration such as scene switching, user dialogue, and UI outbox handling belongs to app/server layers.
	"""

	world_state: WorldState
	interaction_engine: Any
	executor: Any
	action_provider: Any

	is_running: bool = False
	ticks_per_step: int = 1
	max_trigger_depth: int = 4

	# Optional: Route different action providers by provider_id (Player/LLM/Script/Replay, etc.)
	# If an entity's controller provider_id is not in this table, the entity will not produce actions in the decision loop (Safe default).
	action_providers: dict[str, Any] = field(default_factory=dict)
	reaction_rules: list[dict[str, Any]] = field(default_factory=list)
	trigger_system: TriggerSystem | None = None

	# Snapshot storage
	snapshots: list[dict[str, Any]] = field(default_factory=list)
	checkpoint_enabled: bool = True
	checkpoint_dir: str = ""
	checkpoint_include_logs: bool = True
	checkpoint_write_global_log: bool = True
	checkpoint_snapshot_interval_ticks: int = 60
	dialogue_log_full: bool = False
	dialogue_budget_limit_per_location: int = 4
	workflow_contract_on_error: str = "fail_fast"
	last_stop_info: dict[str, Any] = field(default_factory=dict)
	run_id: str = ""
	archive_recorder: ArchiveRecorder | None = None

	project_root: Path | None = None
	config_path: Path | None = None
	runtime_config: dict[str, str] = field(default_factory=dict)
	data_bundle: Any = None
	configured_max_ticks: int = 100

	def __post_init__(self) -> None:
		if self.trigger_system is None:
			self.trigger_system = TriggerSystem(rules=list(self.reaction_rules or []))
		if self.checkpoint_enabled:
			base_dir = str(self.checkpoint_dir or "").strip()
			if not base_dir:
				base_dir = str(Path.cwd() / "checkpoints")
			self.checkpoint_dir = base_dir
			Path(self.checkpoint_dir).mkdir(parents=True, exist_ok=True)
		run_id = str(self.run_id or "").strip()
		if not run_id:
			run_id = str(getattr(self.world_state, "_checkpoint_run_id", "") or "").strip()
		if not run_id:
			run_id = uuid4().hex
		self.run_id = run_id
		if self.checkpoint_enabled:
			self.archive_recorder = ArchiveRecorder(
				archive_dir=str(self.checkpoint_dir),
				run_id=str(self.run_id or ""),
				snapshot_interval_ticks=int(self.checkpoint_snapshot_interval_ticks or 60),
				include_logs=bool(self.checkpoint_include_logs),
			)

	@classmethod
	def from_config(
		cls,
		project_root: str | Path,
		config_path: str | Path = "",
		*,
		validate: bool = True,
		configure_logging: bool = True,
		overrides: dict[str, Any] | None = None,
	) -> "KernRuntime":
		"""
		Create a ready-to-run KERN runtime from a runtime config file.

		This is the SDK entry point for apps and scripts. It owns the object
		assembly that used to live in the CLI: config parsing, data loading,
		optional validation, checkpoint restore, world build, provider selection,
		and runtime construction.
		"""
		root = Path(project_root).resolve()
		cfg, resolved_config_path = _load_runtime_config(root, str(config_path or ""))
		for key, value in dict(overrides or {}).items():
			clean_key = str(key or "").strip()
			if clean_key and value is not None:
				cfg[clean_key] = str(value)
		if configure_logging:
			configure_logger(
				level=_cfg_get(cfg, "LOG_LEVEL", "info"),
				categories=_cfg_get(cfg, "LOG_CATEGORIES", "*"),
				json_mode=_cfg_bool(cfg, "LOG_JSON", False),
				buffer_size=_cfg_int(cfg, "LOG_BUFFER_SIZE", 1000),
			)

		recipes_jsons = [x.strip() for x in _cfg_get(cfg, "RECIPES_JSONS", "Recipes.json").split(",") if x.strip()]
		reactions_jsons = [x.strip() for x in _cfg_get(cfg, "REACTIONS_JSONS", "Reactions.json").split(",") if x.strip()]
		entities_dirs = [x.strip() for x in _cfg_get(cfg, "ENTITIES_DIRS", "Entities").split(",") if x.strip()]
		bundles_jsons = [x.strip() for x in _cfg_get(cfg, "BUNDLES_JSONS", "Bundles.json").split(",") if x.strip()]
		world_json_name = _cfg_get(cfg, "WORLD_JSON", "World.json")

		bundle = load_data_bundle(
			root,
			recipes_jsons=recipes_jsons,
			reactions_jsons=reactions_jsons,
			entities_dirs=entities_dirs,
			world_json=world_json_name,
			bundles_jsons=bundles_jsons,
		)
		restore_path = resolve_checkpoint_file(_cfg_get(cfg, "CHECKPOINT_RESTORE_FILE", ""), _cfg_get(cfg, "CHECKPOINT_RESTORE_DIR", ""))
		if restore_path is not None:
			ws = restore_world_state_from_checkpoint(restore_path, bundle.entity_templates, bundle.named_bundles)
			if not ws.entities or not ws.locations:
				raise ValueError(f"Invalid checkpoint format or empty world state: {restore_path}")
		else:
			if validate:
				from tools.scenario_lint import lint_bundle

				lint = lint_bundle(
					project_root=root,
					config_path=resolved_config_path,
					env=cfg,
					bundle=bundle,
					world_json=world_json_name,
					recipes_jsons=recipes_jsons,
					reactions_jsons=reactions_jsons,
					entities_dirs=entities_dirs,
					bundles_jsons=bundles_jsons,
				)
				errors = [x for x in lint.issues if x.severity == "ERROR"]
				if errors:
					raise ValueError("Data validation failed:\n" + "\n".join(f"{x.where}: {x.message}" for x in errors))
			result = build_world_state(bundle.world, bundle.entity_templates, bundle.recipes, named_bundles=bundle.named_bundles)
			ws = result.world_state

		use_llm = _cfg_bool(cfg, "USE_LLM", False)
		action_provider = build_default_llm_provider(cfg) if use_llm else SimplePolicyActionProvider()
		max_ticks_env = _cfg_get(cfg, "MAX_TICKS", "")
		default_max_ticks_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_LLM", 15)
		default_max_ticks_no_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_NO_LLM", 65)
		configured_max_ticks = int(max_ticks_env) if max_ticks_env else (default_max_ticks_llm if use_llm else default_max_ticks_no_llm)

		default_checkpoint_dir = root / "checkpoints" / (world_json_name or "default")
		checkpoint_dir_env = _cfg_get(cfg, "CHECKPOINT_DIR", "")
		return cls(
			world_state=ws,
			interaction_engine=InteractionEngine(recipe_db=bundle.recipes),
			executor=WorldExecutor(entity_templates=bundle.entity_templates),
			action_provider=action_provider,
			reaction_rules=list((bundle.reactions or {}).get("rules", []) or []),
			max_trigger_depth=_cfg_int(cfg, "MAX_TRIGGER_DEPTH", 4),
			dialogue_budget_limit_per_location=_cfg_int(cfg, "DIALOGUE_BUDGET_LIMIT_PER_LOCATION", 4),
			workflow_contract_on_error=_cfg_get(cfg, "WORKFLOW_CONTRACT_ON_ERROR", "fail_fast").lower() or "fail_fast",
			checkpoint_enabled=_cfg_bool(cfg, "CHECKPOINT_EVERY_TICK", True),
			checkpoint_dir=checkpoint_dir_env if checkpoint_dir_env else str(default_checkpoint_dir),
			checkpoint_include_logs=_cfg_bool(cfg, "CHECKPOINT_INCLUDE_LOGS", True),
			checkpoint_snapshot_interval_ticks=_cfg_int(cfg, "CHECKPOINT_SNAPSHOT_INTERVAL_TICKS", 60),
			dialogue_log_full=_cfg_bool(cfg, "DIALOGUE_LOG_FULL", False),
			project_root=root,
			config_path=resolved_config_path,
			runtime_config=dict(cfg),
			data_bundle=bundle,
			configured_max_ticks=int(configured_max_ticks),
		)

	def run_configured(self) -> list[dict[str, Any]]:
		"""Run until the `MAX_TICKS` value resolved from runtime config."""
		return self.run(max_ticks=int(self.configured_max_ticks or 100))

	def run(self, max_ticks: int = 100) -> list[dict[str, Any]]:
		self.is_running = True
		all_events: list[dict[str, Any]] = []

		self.record_initial_state()

		while self.is_running and self.world_state.game_time.total_ticks < max_ticks:
			tick_events = self.step_and_record()
			all_events.extend(tick_events)

		return all_events

	def record_initial_state(self) -> None:
		"""Record the current world state before runtime advancement."""
		self._record_runtime_frame(events_in_tick=[])

	def step_and_record(self) -> list[dict[str, Any]]:
		"""Advance one runtime tick and record snapshot/checkpoint/log outputs."""
		tick_events = self.step()
		self._record_runtime_frame(events_in_tick=tick_events)
		return tick_events

	def advance_ticks(self, count: int) -> dict[str, Any]:
		"""
		Advance up to count runtime ticks, recording outputs after each tick.

		This is the public API for app/server layers that manually drive KERN.
		"""
		requested = max(0, int(count or 0))
		started_at_tick = int(getattr(self.world_state.game_time, "total_ticks", 0) or 0)
		all_events: list[dict[str, Any]] = []
		completed = 0
		was_running = bool(self.is_running)
		self.is_running = True
		stopped_early = False
		try:
			for _idx in range(requested):
				if not bool(self.is_running):
					stopped_early = True
					break
				tick_events = self.step_and_record()
				all_events.extend(tick_events)
				completed += 1
				if not bool(self.is_running):
					stopped_early = True
					break
		finally:
			stopped_early = stopped_early or completed < requested
			if not was_running:
				self.is_running = False
		ended_at_tick = int(getattr(self.world_state.game_time, "total_ticks", 0) or 0)
		return {
			"events": all_events,
			"event_count": len(all_events),
			"ticks_requested": requested,
			"ticks_advanced": completed,
			"started_at_tick": started_at_tick,
			"ended_at_tick": ended_at_tick,
			"stopped": bool(stopped_early),
			"stop_info": dict(self.last_stop_info or {}),
		}

	def _record_runtime_frame(self, events_in_tick: list[dict[str, Any]]) -> None:
		self._capture_snapshot(events_in_tick=events_in_tick)
		self._save_checkpoint()
		self._save_simulation_log()

	def _capture_snapshot(self, events_in_tick: list[dict[str, Any]]) -> None:
		"""
		Capture full world state snapshot for visualization/debugging.
		"""
		ws = self.world_state
		
		# 1. Entities snapshot
		entities_snap = {}
		for eid, ent in ws.entities.items():
			# Basic info
			ent_data = {
				"template_id": ent.template_id,
				"name": ent.entity_name,
				"components": {}
			}
			
			# Component data (Selectively serialize important components)
			# CreatureComponent: Nutrition/Energy
			cc = ent.get_component("CreatureComponent")
			if cc:
				ent_data["components"]["CreatureComponent"] = {
					"nutrition": getattr(cc, "current_nutrition", 0),
					"energy": getattr(cc, "current_energy", 0),
					"state": getattr(cc, "current_state", "Idle"),
				}
			
			# WorkerComponent: Current Task
			wc = ent.get_component("WorkerComponent")
			if wc:
				task_id = getattr(wc, "current_task_id", "")
				task_desc = ""
				if task_id:
					task = ws.get_task_by_id(task_id)
					if task:
						task_desc = f"{task.task_type}"
				ent_data["components"]["WorkerComponent"] = {
					"current_task_id": task_id,
					"current_action_desc": task_desc
				}

			container = ent.get_component("ContainerComponent")
			if container and hasattr(container, "slots"):
				slots_data = {}
				for slot_id, slot in container.slots.items():
					slots_data[str(slot_id)] = {
						"items": list(getattr(slot, "items", []) or []),
						"config": dict(getattr(slot, "config", {}) or {}),
					}
				ent_data["components"]["ContainerComponent"] = {
					"slots": slots_data
				}

			# Location info
			loc = ws.get_location_of_entity(eid)
			ent_data["location_id"] = loc.location_id if loc else None
			
			entities_snap[eid] = ent_data

		# 2. Locations snapshot (Entities in location)
		locations_snap = {}
		for lid, loc in ws.locations.items():
			locations_snap[lid] = {
				"entities": list(loc.entities_in_location)
			}

		# 3. Construct frame
		# Also collect interaction logs for this tick
		current_interactions = []
		if hasattr(ws, "interaction_log") and ws.interaction_log:
			# Filter interactions that happened in this tick
			# Note: tick in interaction_log is int
			current_tick = int(ws.game_time.total_ticks)
			for item in ws.interaction_log:
				if item.get("tick") == current_tick:
					current_interactions.append(item)

		snapshot = {
			"tick": ws.game_time.total_ticks,
			"time_str": ws.game_time.time_to_string(),
			"entities": entities_snap,
			"locations": locations_snap,
			"events": [dict(e) for e in events_in_tick], # Deep copy events to avoid reference issues
			"interactions": [dict(i) for i in current_interactions]
		}
		
		self.snapshots.append(snapshot)

	def _build_simulation_log_payload(self) -> dict[str, Any]:
		return build_simulation_log_payload_from_world_state(self.world_state, run_id=str(self.run_id or "").strip())

	def _save_checkpoint(self) -> None:
		if not self.checkpoint_enabled:
			return
		if self.archive_recorder is None:
			return
		try:
			self.archive_recorder.record_tick(self.world_state)
			logger = get_logger()
			tick = int(getattr(self.world_state.game_time, "total_ticks", 0) or 0)
			logger.debug("checkpoint", "archive_recorded", context={"tick": tick, "path": str(self.checkpoint_dir)})
		except Exception as e:
			logger = get_logger()
			tick = int(getattr(self.world_state.game_time, "total_ticks", 0) or 0)
			logger.warn("checkpoint", "archive_record_failed", context={"tick": tick, "path": str(self.checkpoint_dir), "error": str(e)})

	def _save_simulation_log(self) -> None:
		if not self.checkpoint_enabled or not self.checkpoint_write_global_log:
			return
		logger = get_logger()
		ws = self.world_state
		tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
		log_path = resolve_global_log_file(self.checkpoint_dir)
		log_path.parent.mkdir(parents=True, exist_ok=True)
		tmp_path = log_path.with_suffix(".tmp")
		payload = self._build_simulation_log_payload()
		try:
			with tmp_path.open("w", encoding="utf-8") as f:
				json.dump(payload, f, ensure_ascii=False, indent=2)
			tmp_path.replace(log_path)
			logger.debug("checkpoint", "global_log_saved", context={"tick": tick, "path": str(log_path)})
		except Exception as e:
			logger.warn("checkpoint", "global_log_save_failed", context={"tick": tick, "path": str(log_path), "error": str(e)})

	def stop(self) -> None:
		self.is_running = False

	def request_stop(self, info: dict[str, Any] | None = None) -> None:
		self.is_running = False
		self.last_stop_info = dict(info or {})

	def step(self) -> list[dict[str, Any]]:
		"""
		Advance one simulation tick (Turn-based).
		"""
		logger = get_logger()
		ws = self.world_state
		start_event_seq = int(getattr(ws, "_event_seq", 0) or 0)

		# 1) Inject runtime services for effect execution stack.
		# TODO(architecture): Deliberately keep ws.services for now.
		# Do not spread new keys casually; plan a single migration to typed RuntimeContext later.
		if self.trigger_system is not None:
			self.trigger_system.begin_tick()

		self.world_state.services = {
			"interaction_engine": self.interaction_engine,
			"default_action_provider": self.action_provider,
			"action_providers": dict(self.action_providers or {}),
			"request_stop": self.request_stop,
		}
		from .models.runtime_state import RuntimeState
		self.world_state.runtime_state = RuntimeState(
			dialogue_budget_limit_per_location=int(self.dialogue_budget_limit_per_location),
			dialogue_budget_used_per_location={},
			dialogue_log_full=bool(self.dialogue_log_full),
			workflow_contract_on_error=str(self.workflow_contract_on_error or "fail_fast"),
			abort_requested=False,
			abort_reason="",
			abort_detail="",
			abort_severity="",
			abort_actor_id="",
		)

		def stop_for_settlement_failure(fatal: dict[str, Any]) -> None:
			fatal_type = str(fatal.get("type", "") or "")
			reason = "reaction_depth_exceeded" if fatal_type == "ReactionDepthExceeded" else "reaction_failed"
			ws.runtime_state.abort_requested = True
			ws.runtime_state.abort_reason = reason
			ws.runtime_state.abort_detail = str(fatal)
			ws.runtime_state.abort_severity = "fatal"
			self.request_stop({"reason": reason, **dict(fatal)})

		settlement = WorldSettlement(
			ws=ws,
			executor=self.executor,
			trigger_system=self.trigger_system,
			max_reaction_depth=self.max_trigger_depth,
			on_fatal=stop_for_settlement_failure,
		)
		ws.services["execute"] = settlement.execute_bundle

		# 2) Advance time and dispatch the world-level tick through reactions.
		self.world_state.game_time.advance_ticks(self.ticks_per_step)
		world_tick_event = {
			"type": "WorldTickAdvanced",
			"total_ticks": ws.game_time.total_ticks,
			"time": ws.game_time.time_to_string(),
		}
		world_tick_ctx = {"actor_id": ""}
		logger.debug("tick", "tick_advanced", context=dict(world_tick_event))
		world_result = settlement.publish_event(world_tick_event, world_tick_ctx)
		if world_result.fatal_error is not None:
			logger.error("reaction", "settlement_failed", context=dict(world_result.fatal_error))

		# 3) Dispatch AdvanceTick events per entity, then let Reactions decide which effects to run.
		for ent_id in list(ws.entities.keys()):
			if not bool(self.is_running):
				break
			tick_event = {
				"type": "AdvanceTick",
				"entity_id": ent_id,
				"ticks": int(self.ticks_per_step),
			}
			tick_ctx = {"entity_id": ent_id, "event_entity_id": ent_id, "self_id": ent_id}
			tick_result = settlement.publish_event(tick_event, tick_ctx)
			if tick_result.fatal_error is not None:
				logger.error("reaction", "settlement_failed", context=dict(tick_result.fatal_error))

		events_in_tick_records: list[dict[str, Any]] = []
		for rec in list(getattr(ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			seq = int(rec.get("seq", 0) or 0)
			if seq > int(start_event_seq):
				events_in_tick_records.append(dict(rec))
		return events_in_tick_records
