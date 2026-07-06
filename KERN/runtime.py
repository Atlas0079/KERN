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
from .effect_bundle import effect_bundle_from_raw
from .execution_errors import executor_error, is_execution_error_event
from .executor.executor import WorldExecutor
from .external_runtime import ExternalRuntimeBridge
from .external_runtimes import SQLiteSocialPlatformRuntime
from .external_runtimes.social_seed import seed_social_platform_runtime_from_file
from .interaction.engine import InteractionEngine
from .log_manager import configure_logger, get_logger
from .models.world_state import WorldState
from .sim.trigger_system import TriggerSystem


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


def _truthy_config_value(value: Any) -> bool:
	if isinstance(value, bool):
		return bool(value)
	text = str(value or "").strip().lower()
	return text in {"1", "true", "yes", "on"}


def _resolve_config_relative_path(project_root: Path, config_path: Path, value: str) -> Path:
	raw = str(value or "").strip()
	if not raw:
		return Path()
	path = Path(raw)
	if path.is_absolute():
		return path
	base = config_path.parent if config_path.parent.exists() else project_root
	return (base / path).resolve()


def _build_configured_external_runtimes(
	project_root: Path,
	config_path: Path,
	cfg: dict[str, str],
) -> dict[str, Any]:
	raw = _cfg_get(cfg, "EXTERNAL_RUNTIMES_JSON", "")
	if not raw:
		return {}
	try:
		specs = json.loads(raw)
	except Exception as exc:
		raise ValueError(f"EXTERNAL_RUNTIMES_JSON must be valid JSON: {exc}") from exc
	if not isinstance(specs, dict):
		raise ValueError("EXTERNAL_RUNTIMES_JSON must be a JSON object")
	out: dict[str, Any] = {}
	for runtime_id, spec_raw in specs.items():
		rid = str(runtime_id or "").strip()
		if not rid:
			raise ValueError("EXTERNAL_RUNTIMES_JSON contains blank runtime id")
		spec = dict(spec_raw or {}) if isinstance(spec_raw, dict) else {}
		rtype = str(spec.get("type", "") or "").strip()
		if rtype not in {"sqlite_social_platform", "social_platform_sqlite"}:
			raise ValueError(f"unsupported external runtime type for {rid}: {rtype}")
		db_path_raw = str(spec.get("db_path", "") or "").strip()
		if not db_path_raw:
			raise ValueError(f"external runtime {rid} missing db_path")
		db_path = _resolve_config_relative_path(project_root, config_path, db_path_raw)
		if _truthy_config_value(spec.get("reset_db", False)) and db_path.exists():
			db_path.unlink()
		runtime = SQLiteSocialPlatformRuntime(db_path, runtime_id=rid)
		seed_path_raw = str(spec.get("seed_json", "") or "").strip()
		if seed_path_raw:
			seed_path = _resolve_config_relative_path(project_root, config_path, seed_path_raw)
			seed_social_platform_runtime_from_file(runtime, seed_path)
		out[rid] = runtime
	return out


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
	external_runtimes: dict[str, Any] = field(default_factory=dict)
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
		external_runtimes: dict[str, Any] | None = None,
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
		external_runtime_map = _build_configured_external_runtimes(root, resolved_config_path, cfg)
		external_runtime_map.update(dict(external_runtimes or {}))
		external_runtime_bridge = ExternalRuntimeBridge(external_runtime_map)
		if restore_path is not None:
			ws = restore_world_state_from_checkpoint(restore_path, bundle.entity_templates, bundle.named_bundles)
			if not ws.entities or not ws.locations:
				raise ValueError(f"Invalid checkpoint format or empty world state: {restore_path}")
			restore_events = external_runtime_bridge.restore_checkpoint(
				cls._build_checkpoint_context_for_world(
					ws,
					run_id=str(getattr(ws, "_checkpoint_run_id", "") or ""),
					phase="restore",
				)
			)
			cls._raise_on_external_checkpoint_error(restore_events, "restore")
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
			external_runtimes=external_runtime_map,
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

	@staticmethod
	def _build_checkpoint_context_for_world(
		ws: WorldState,
		*,
		run_id: str,
		phase: str = "",
	) -> dict[str, Any]:
		return {
			"run_id": str(run_id or ""),
			"tick": int(getattr(ws.game_time, "total_ticks", 0) or 0),
			"time_str": ws.game_time.time_to_string(),
			"phase": str(phase or ""),
		}

	@staticmethod
	def _raise_on_external_checkpoint_error(events: list[dict[str, Any]], phase: str) -> None:
		for ev in list(events or []):
			if is_execution_error_event(ev):
				raise RuntimeError(f"External runtime checkpoint {phase} failed: {ev.get('message', ev)}")

	def _build_checkpoint_context(self, phase: str) -> dict[str, Any]:
		return self._build_checkpoint_context_for_world(
			self.world_state,
			run_id=str(self.run_id or ""),
			phase=str(phase or ""),
		)

	def _save_checkpoint(self) -> None:
		if not self.checkpoint_enabled:
			return
		if self.archive_recorder is None:
			return
		logger = get_logger()
		tick = int(getattr(self.world_state.game_time, "total_ticks", 0) or 0)
		try:
			self.archive_recorder.record_tick(self.world_state)
			logger.debug("checkpoint", "archive_recorded", context={"tick": tick, "path": str(self.checkpoint_dir)})
			bridge = ExternalRuntimeBridge(dict(self.external_runtimes or {}))
			events = bridge.save_checkpoint(self._build_checkpoint_context("save"))
			self._raise_on_external_checkpoint_error(events, "save")
			if events:
				logger.debug("checkpoint", "external_runtime_checkpoint_saved", context={"tick": tick, "event_count": len(events)})
		except Exception as e:
			logger.warn("checkpoint", "checkpoint_record_failed", context={"tick": tick, "path": str(self.checkpoint_dir), "error": str(e)})
			raise

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
		events: list[dict[str, Any]] = []
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
			"external_runtime_bridge": ExternalRuntimeBridge(dict(self.external_runtimes or {})),
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

		# Runtime execution entrypoint used by effects/workflow.
		# It executes a bundle, records emitted events, and recursively runs reactions
		# triggered by those events until no more reactions match or max depth is reached.
		def execute_with_reactions(bundle_data: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
			collected_events: list[dict[str, Any]] = []

			def _record_reaction_attempt(ctx: dict[str, Any], reaction_failed: bool, reaction_fail_reason: str, effect_type: str) -> None:
				reaction_rule_id = str((ctx or {}).get("reaction_rule_id", "") or "")
				if not reaction_rule_id or not hasattr(ws, "record_interaction_attempt"):
					return
				actor_id = str((ctx or {}).get("self_id", "") or "")
				target_id = str((ctx or {}).get("target_id", "") or "")
				ws.record_interaction_attempt(
					actor_id=actor_id,
					verb=f"ReactionApplied:{reaction_rule_id}",
					target_id=target_id,
					status="failed" if reaction_failed else "success",
					reason=reaction_fail_reason if reaction_failed else "",
					recipe_id=f"reaction_applied:{reaction_rule_id}",
					extra={
						"is_reaction": True,
						"reaction_phase": "failed" if reaction_failed else "applied",
						"reaction_rule_id": reaction_rule_id,
						"trigger_event": str((ctx or {}).get("reaction_trigger_event_type", "") or ""),
						"effect_type": str(effect_type or ""),
					},
				)

			def _record_events_and_run_reactions(result_events: list[dict[str, Any]], ctx: dict[str, Any], depth: int, effect_type: str) -> None:
				reaction_failed = False
				reaction_fail_reason = ""
				for _ev in list(result_events or []):
					if is_execution_error_event(_ev):
						reaction_failed = True
						reaction_fail_reason = str(_ev.get("message", "") or _ev.get("type", "") or "")
						logger.warn(
							"executor",
							"effect_failed",
							context={
								"effect_type": str(effect_type or ""),
								"context": dict(ctx or {}),
								"error_event": dict(_ev),
								"depth": int(depth),
							},
						)
						break
				_record_reaction_attempt(ctx, reaction_failed, reaction_fail_reason, effect_type)
				for ev in list(result_events or []):
					if not isinstance(ev, dict):
						continue
					clean_ev = dict(ev)
					collected_events.append(dict(clean_ev))
					ws.record_event(clean_ev, ctx)
					events.append(clean_ev)
					logger.trace("event", "record", context={"event": dict(clean_ev), "context": dict(ctx or {}), "depth": int(depth)})
					if ws.runtime_state.abort_requested:
						return
					if depth >= int(self.max_trigger_depth):
						limit_event = {
							"type": "ReactionDepthExceeded",
							"depth": int(depth),
							"max_trigger_depth": int(self.max_trigger_depth),
							"source_event_type": str(clean_ev.get("type", "") or ""),
							"source_event_entity_id": str(clean_ev.get("entity_id", "") or ""),
						}
						ws.record_event(limit_event, ctx)
						events.append(limit_event)
						continue
					if self.trigger_system is None:
						continue
					reqs = self.trigger_system.build_reaction_effects(ws, clean_ev, ctx)
					for req in list(reqs or []):
						rbundle = req.get("bundle", {}) or {}
						rctx = req.get("context", {}) or {}
						if isinstance(rctx, dict):
							_execute_bundle_with_reactions(rbundle, rctx, depth + 1)
							if ws.runtime_state.abort_requested:
								return

			def _execute_effect_with_reactions(eff: dict[str, Any], ctx: dict[str, Any], depth: int) -> None:
				if not bool(self.is_running):
					return
				logger.debug("effect", "execute", context={"effect": dict(eff or {}), "context": dict(ctx or {}), "depth": int(depth)})
				result_events = self.executor.execute(ws, eff, ctx)
				_record_events_and_run_reactions(result_events, ctx, depth, str((eff or {}).get("effect", "") or ""))

			def _execute_bundle_with_reactions(raw_bundle: Any, ctx: dict[str, Any], depth: int) -> None:
				if not bool(self.is_running):
					return
				try:
					bundle = effect_bundle_from_raw(raw_bundle)
				except Exception as exc:
					result_events = executor_error(f"invalid bundle ({exc})")
					_record_events_and_run_reactions(result_events, ctx, depth, "Bundle")
					return
				logger.debug("bundle", "execute", context={"bundle": bundle.to_dict(), "context": dict(ctx or {}), "depth": int(depth)})
				result_events = self.executor.execute_bundle(ws, bundle, ctx)
				_record_events_and_run_reactions(result_events, ctx, depth, "Bundle")

			_execute_bundle_with_reactions(bundle_data, context, 0)
			if ws.runtime_state.abort_requested:
				self.request_stop(
					{
						"reason": ws.runtime_state.abort_reason,
						"detail": ws.runtime_state.abort_detail,
						"severity": ws.runtime_state.abort_severity,
						"actor_id": ws.runtime_state.abort_actor_id,
					}
				)
			return collected_events

		ws.services["execute"] = execute_with_reactions

		# 2) Advance time and dispatch the world-level tick through reactions.
		self.world_state.game_time.advance_ticks(self.ticks_per_step)
		world_tick_event = {
			"type": "WorldTickAdvanced",
			"total_ticks": ws.game_time.total_ticks,
			"time": ws.game_time.time_to_string(),
		}
		world_tick_ctx = {"actor_id": ""}
		logger.debug("tick", "tick_advanced", context=dict(world_tick_event))
		ws.record_event(world_tick_event, world_tick_ctx)
		events.append(dict(world_tick_event))
		if self.trigger_system is not None:
			reqs = self.trigger_system.build_reaction_effects(ws, world_tick_event, world_tick_ctx)
			for req in list(reqs or []):
				rbundle = req.get("bundle", {}) or {}
				rctx = req.get("context", {}) or {}
				if isinstance(rctx, dict):
					execute_with_reactions(rbundle, rctx)
					if ws.runtime_state.abort_requested or not bool(self.is_running):
						break

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
			ws.record_event(tick_event, tick_ctx)
			events.append(dict(tick_event))
			if self.trigger_system is None:
				continue
			reqs = self.trigger_system.build_reaction_effects(ws, tick_event, tick_ctx)
			for req in list(reqs or []):
				rbundle = req.get("bundle", {}) or {}
				rctx = req.get("context", {}) or {}
				if isinstance(rctx, dict):
					execute_with_reactions(rbundle, rctx)

		events_in_tick_records: list[dict[str, Any]] = []
		for rec in list(getattr(ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			seq = int(rec.get("seq", 0) or 0)
			if seq > int(start_event_seq):
				events_in_tick_records.append(dict(rec))
		return events_in_tick_records
