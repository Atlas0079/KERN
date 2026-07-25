from __future__ import annotations
import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_workflow.provider_catalog import build_workflow_provider_catalog
from .agent_workflow.registry import WorkflowRegistry
from .agent_workflow.simple_policy import SimplePolicyActionProvider
from .agent_workflow.trace import LLMTraceRecorder
from .agent_workflow.view_profile import normalize_workflow_view_profile
from .sim.turn_scheduler import TurnScheduler
from .component_catalog import ComponentCatalog, build_core_component_catalog
from .data.archive import ArchiveRecorder
from .data.builder import build_world_state
from .data.checkpoint import (
	build_simulation_log_payload_from_world_state,
	load_checkpoint_meta,
	resolve_checkpoint_file,
	resolve_global_log_file,
	restore_world_state_from_checkpoint,
)
from .execution_errors import KernFailure
from .effect_record import build_runtime_event
from .failure_report import FailureReportWriter
from .executor.executor import WorldExecutor
from .external_runtime import ExternalRuntimeBridge
from .interaction.engine import InteractionEngine
from .log_manager import configure_logger, get_logger
from .models.world_state import WorldState
from .package import (
	LoadedPackages,
	load_packages_from_config,
	loaded_package_selection_identity,
	package_identity,
	package_selection_identity,
)
from .package_identity import verify_checkpoint_identity
from .runtime_snapshot import RuntimeSnapshotBuilder
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


def _resolve_config_relative_path(project_root: Path, config_path: Path, value: str) -> Path:
	raw = str(value or "").strip()
	if not raw:
		return Path()
	path = Path(raw)
	if path.is_absolute():
		return path
	base = config_path.parent if config_path.parent.exists() else project_root
	return (base / path).resolve()


def _build_workflow_view_profile(project_root: Path, config_path: Path, cfg: dict[str, str]) -> dict[str, Any]:
	profile_id = _cfg_get(cfg, "WORKFLOW_VIEW_PROFILE", "")
	override: dict[str, Any] = {}
	profile_path_raw = _cfg_get(cfg, "WORKFLOW_VIEW_PROFILE_JSON", "")
	if profile_path_raw:
		profile_path = _resolve_config_relative_path(project_root, config_path, profile_path_raw)
		data = json.loads(profile_path.read_text(encoding="utf-8"))
		if not isinstance(data, dict):
			raise ValueError(f"WORKFLOW_VIEW_PROFILE_JSON must be a JSON object: {profile_path}")
		override = data
		if not profile_id:
			profile_id = str(data.get("profile_id", "") or "")
	return normalize_workflow_view_profile(profile_id, override)


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
	action_provider: Any = None
	component_catalog: ComponentCatalog | None = None
	workflow_registry: WorkflowRegistry | None = None

	is_running: bool = False
	ticks_per_step: int = 1
	max_trigger_depth: int = 4
	max_actions_per_turn: int = 99
	max_replans_per_turn: int = 5

	# Named workflows are selected by provider_id; unresolved IDs fall back to
	# action_provider so existing single-provider scenarios keep working.
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
	loaded_packages: LoadedPackages | None = None
	configured_max_ticks: int = 100
	workflow_view_profile: dict[str, Any] = field(default_factory=dict)
	llm_trace_recorder: LLMTraceRecorder | None = None
	failure_report_writer: FailureReportWriter | None = None
	is_terminal: bool = False
	terminal_error: str = ""
	snapshot_builder: RuntimeSnapshotBuilder | None = field(default=None, init=False, repr=False)

	def __post_init__(self) -> None:
		if self.workflow_registry is None:
			self.workflow_registry = WorkflowRegistry.from_legacy(self.action_provider, self.action_providers)
		self.workflow_registry.freeze()
		catalog = self.component_catalog or getattr(self.executor, "component_catalog", None) or build_core_component_catalog()
		catalog.freeze()
		self.component_catalog = catalog
		self.snapshot_builder = RuntimeSnapshotBuilder(catalog)
		if hasattr(self.executor, "component_catalog"):
			self.executor.component_catalog = catalog
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
		if self.failure_report_writer is None:
			report_root = str(self.checkpoint_dir or "").strip()
			if not report_root:
				report_root = str(Path.cwd() / "failures" / self.run_id)
			self.failure_report_writer = FailureReportWriter(report_root, self.run_id)
		if self.checkpoint_enabled:
			self.archive_recorder = ArchiveRecorder(
				archive_dir=str(self.checkpoint_dir),
				run_id=str(self.run_id or ""),
				snapshot_interval_ticks=int(self.checkpoint_snapshot_interval_ticks or 60),
				include_logs=bool(self.checkpoint_include_logs),
				component_catalog=catalog,
				package_identity={"package_identity": package_identity(self.loaded_packages)} if self.loaded_packages is not None else {},
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
		workflow_registry: WorkflowRegistry | None = None,
		_loaded_packages: LoadedPackages | None = None,
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

		if _loaded_packages is not None and loaded_package_selection_identity(_loaded_packages) != package_selection_identity(root, resolved_config_path):
			raise ValueError("loaded packages do not match the config package selection")
		loaded_packages = _loaded_packages or load_packages_from_config(root, resolved_config_path)
		bundle = loaded_packages.data_bundle
		world_data = loaded_packages.world_package.manifest.data
		if world_data is None:
			raise ValueError("loaded package composition has no world data")
		recipes_jsons = list(world_data.recipes)
		reactions_jsons = list(world_data.reactions)
		entities_dirs = list(world_data.entities)
		bundles_jsons = list(world_data.bundles)
		world_json_name = world_data.world
		effect_catalog = loaded_packages.effect_catalog
		component_catalog = loaded_packages.component_catalog
		restore_path = resolve_checkpoint_file(_cfg_get(cfg, "CHECKPOINT_RESTORE_FILE", ""), _cfg_get(cfg, "CHECKPOINT_RESTORE_DIR", ""))
		external_runtime_map = dict(external_runtimes or {})
		external_runtime_bridge = ExternalRuntimeBridge(external_runtime_map)
		workflow_view_profile = _build_workflow_view_profile(root, resolved_config_path, cfg)
		if restore_path is not None:
			checkpoint_meta = load_checkpoint_meta(restore_path)
			verify_checkpoint_identity(checkpoint_meta, loaded_packages)
			ws = restore_world_state_from_checkpoint(
				restore_path,
				bundle.entity_templates,
				bundle.named_bundles,
				component_catalog=component_catalog,
			)
			if not ws.entities or not ws.locations:
				raise ValueError(f"Invalid checkpoint format or empty world state: {restore_path}")
			external_runtime_bridge.restore_checkpoint(
				cls._build_checkpoint_context_for_world(
					ws,
					run_id=str(getattr(ws, "_checkpoint_run_id", "") or ""),
					phase="restore",
				)
			)
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
					effect_catalog=effect_catalog,
					component_catalog=component_catalog,
				)
				errors = [x for x in lint.issues if x.severity == "ERROR"]
				if errors:
					raise ValueError("Data validation failed:\n" + "\n".join(f"{x.where}: {x.message}" for x in errors))
			result = build_world_state(
				bundle.world,
				bundle.entity_templates,
				bundle.recipes,
				named_bundles=bundle.named_bundles,
				component_catalog=component_catalog,
			)
			ws = result.world_state

		default_checkpoint_dir = root / "checkpoints" / (world_json_name or "default")
		checkpoint_dir_env = _cfg_get(cfg, "CHECKPOINT_DIR", "")
		resolved_checkpoint_dir = checkpoint_dir_env if checkpoint_dir_env else str(default_checkpoint_dir)
		trace_recorder = LLMTraceRecorder.from_config(cfg, Path(resolved_checkpoint_dir) / "llm_traces")

		use_llm = _cfg_bool(cfg, "USE_LLM", False)
		if use_llm:
			action_provider, action_providers = build_workflow_provider_catalog(cfg, trace_recorder=trace_recorder)
		else:
			action_provider, action_providers = SimplePolicyActionProvider(), {}
		max_ticks_env = _cfg_get(cfg, "MAX_TICKS", "")
		default_max_ticks_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_LLM", 15)
		default_max_ticks_no_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_NO_LLM", 65)
		configured_max_ticks = int(max_ticks_env) if max_ticks_env else (default_max_ticks_llm if use_llm else default_max_ticks_no_llm)

		return cls(
			world_state=ws,
			interaction_engine=InteractionEngine(recipe_db=bundle.recipes),
			executor=WorldExecutor(
				entity_templates=bundle.entity_templates,
				effect_catalog=effect_catalog,
				component_catalog=component_catalog,
			),
			action_provider=action_provider,
			component_catalog=component_catalog,
			workflow_registry=workflow_registry,
			action_providers=action_providers,
			external_runtimes=external_runtime_map,
			reaction_rules=list((bundle.reactions or {}).get("rules", []) or []),
			max_trigger_depth=_cfg_int(cfg, "MAX_TRIGGER_DEPTH", 4),
			max_actions_per_turn=_cfg_int(cfg, "MAX_ACTIONS_PER_TURN", 99),
			max_replans_per_turn=_cfg_int(cfg, "MAX_REPLANS_PER_TURN", 5),
			dialogue_budget_limit_per_location=_cfg_int(cfg, "DIALOGUE_BUDGET_LIMIT_PER_LOCATION", 4),
			workflow_contract_on_error="fail_fast",
			checkpoint_enabled=_cfg_bool(cfg, "CHECKPOINT_EVERY_TICK", True),
			checkpoint_dir=resolved_checkpoint_dir,
			checkpoint_include_logs=_cfg_bool(cfg, "CHECKPOINT_INCLUDE_LOGS", True),
			checkpoint_snapshot_interval_ticks=_cfg_int(cfg, "CHECKPOINT_SNAPSHOT_INTERVAL_TICKS", 60),
			dialogue_log_full=_cfg_bool(cfg, "DIALOGUE_LOG_FULL", False),
			workflow_view_profile=workflow_view_profile,
			llm_trace_recorder=trace_recorder,
			project_root=root,
			config_path=resolved_config_path,
			runtime_config=dict(cfg),
			data_bundle=bundle,
			loaded_packages=loaded_packages,
			configured_max_ticks=int(configured_max_ticks),
		)

	@classmethod
	def from_loaded_packages(
		cls,
		loaded_packages: LoadedPackages,
		project_root: str | Path,
		config_path: str | Path = "",
		**kwargs: Any,
	) -> "KernRuntime":
		"""Assemble a runtime from an already validated package composition."""
		return cls.from_config(
			project_root,
			config_path,
			_loaded_packages=loaded_packages,
			**kwargs,
		)

	def run_configured(self) -> list[dict[str, Any]]:
		"""Run until the `MAX_TICKS` value resolved from runtime config."""
		return self.run(max_ticks=int(self.configured_max_ticks or 100))

	def run(self, max_ticks: int = 100) -> list[dict[str, Any]]:
		self._raise_if_terminal()
		self.is_running = True
		all_events: list[dict[str, Any]] = []
		try:
			self.record_initial_state()
			while self.is_running and self.world_state.game_time.total_ticks < max_ticks:
				tick_events = self.step_and_record()
				all_events.extend(tick_events)
			return all_events
		except Exception as exc:
			self._mark_failure(exc)
			self._write_failure_report(exc)
			raise

	def record_initial_state(self) -> None:
		"""Record the current world state before runtime advancement."""
		self._raise_if_terminal()
		try:
			self._record_runtime_frame(events_in_tick=[])
		except Exception as exc:
			self._mark_failure(exc)
			self._write_failure_report(exc)
			raise

	def step_and_record(self) -> list[dict[str, Any]]:
		"""Advance one runtime tick and record snapshot/checkpoint/log outputs."""
		self._raise_if_terminal()
		try:
			tick_events = self.step()
			self._record_runtime_frame(events_in_tick=tick_events)
			return tick_events
		except Exception as exc:
			self._mark_failure(exc)
			self._write_failure_report(exc)
			raise

	def advance_ticks(self, count: int) -> dict[str, Any]:
		"""
		Advance up to count runtime ticks, recording outputs after each tick.

		This is the public API for app/server layers that manually drive KERN.
		"""
		self._raise_if_terminal()
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
		if self.snapshot_builder is None:
			raise RuntimeError("runtime snapshot builder is not initialized")
		self.snapshots.append(self.snapshot_builder.capture(self.world_state, events_in_tick))

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
			if events:
				logger.debug("checkpoint", "external_runtime_checkpoint_saved", context={"tick": tick, "event_count": len(events)})
		except KernFailure as exc:
			exc.add_context(tick=tick, path=str(self.checkpoint_dir), phase="checkpoint_record")
			raise
		except Exception as e:
			raise KernFailure(
				"CHECKPOINT_RECORD_FAILED",
				str(e),
				origin="persistence",
				phase="checkpoint_record",
				context={"tick": tick, "path": str(self.checkpoint_dir)},
			) from e

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
		except KernFailure as exc:
			exc.add_context(tick=tick, path=str(log_path), phase="simulation_log_write")
			raise
		except Exception as e:
			raise KernFailure(
			"SIMULATION_LOG_WRITE_FAILED",
			str(e),
			origin="persistence",
			phase="simulation_log_write",
			context={"tick": tick, "path": str(log_path)},
		) from e

	def stop(self) -> None:
		self.is_running = False

	def _mark_failure(self, error: BaseException) -> None:
		self.is_terminal = True
		self.terminal_error = str(error)
		if isinstance(error, KernFailure):
			info = error.to_dict()
		else:
			info = {
				"code": "UNEXPECTED_EXCEPTION",
				"message": str(error),
				"origin": "kernel",
			}
		self.request_stop({"reason": "failure", **dict(info)})

	def _write_failure_report(self, error: BaseException) -> None:
		writer = self.failure_report_writer
		if writer is None:
			return
		writer.write_failure(
			error,
			tick=int(getattr(getattr(self.world_state, "game_time", None), "total_ticks", 0) or 0),
			context={
				"run_id": str(self.run_id or ""),
				"terminal_error": str(self.terminal_error or ""),
				"runtime_config": dict(self.runtime_config or {}),
				"last_stop_info": dict(self.last_stop_info or {}),
				"event_seq": int(getattr(self.world_state, "_event_seq", 0) or 0),
				"interaction_seq": int(getattr(self.world_state, "_interaction_seq", 0) or 0),
			},
		)
		if writer.last_write_error:
			error.add_note(f"failure report write failed: {writer.last_write_error}")

	def _raise_if_terminal(self) -> None:
		if self.is_terminal:
			raise KernFailure(
				"RUNTIME_TERMINAL",
				f"runtime is terminal: {self.terminal_error or 'runtime failure'}",
				origin="runtime",
				phase="lifecycle",
				context={"terminal_error": str(self.terminal_error or "")},
			)

	def request_stop(self, info: dict[str, Any] | None = None) -> None:
		self.is_running = False
		self.last_stop_info = dict(info or {})

	def step(self) -> list[dict[str, Any]]:
		self._raise_if_terminal()
		try:
			return self._step()
		except Exception as exc:
			self._mark_failure(exc)
			self._write_failure_report(exc)
			raise

	def _step(self) -> list[dict[str, Any]]:
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
			"workflow_registry": self.workflow_registry,
			"default_action_provider": self.action_provider,
			"action_providers": dict(self.action_providers or {}),
			"external_runtime_bridge": ExternalRuntimeBridge(dict(self.external_runtimes or {})),
			"workflow_view_profile": dict(self.workflow_view_profile or {}),
			"request_stop": self.request_stop,
		}
		from .models.runtime_state import RuntimeState
		self.world_state.runtime_state = RuntimeState(
			dialogue_budget_limit_per_location=int(self.dialogue_budget_limit_per_location),
			dialogue_budget_used_per_location={},
			dialogue_log_full=bool(self.dialogue_log_full),
			workflow_contract_on_error="fail_fast",
			abort_requested=False,
			abort_reason="",
			abort_detail="",
			abort_severity="",
			abort_actor_id="",
		)

		settlement = WorldSettlement(
			ws=ws,
			executor=self.executor,
			trigger_system=self.trigger_system,
			max_reaction_depth=self.max_trigger_depth,
		)
		ws.services["execute"] = settlement.execute_bundle

		# 2) Advance time and dispatch the world-level tick through reactions.
		self.world_state.game_time.advance_ticks(self.ticks_per_step)
		world_tick_event = build_runtime_event(
			"WorldTickAdvanced",
			{"total_ticks": ws.game_time.total_ticks, "time": ws.game_time.time_to_string()},
		)
		world_tick_ctx = {"actor_id": ""}
		logger.debug("tick", "tick_advanced", context=dict(world_tick_event))
		settlement.publish_event(world_tick_event, world_tick_ctx)

		# 3) Queue every entity tick before settling passive reactions.
		tick_events = [
			build_runtime_event(
				"AdvanceTick",
				{"entity_id": ent_id, "ticks": int(self.ticks_per_step)},
				{"entity_id": ent_id, "event_entity_id": ent_id, "self_id": ent_id},
			)
			for ent_id in sorted(str(entity_id) for entity_id in ws.entities.keys())
		]
		settlement.publish_events(tick_events)

		# 4) Only the scheduler can grant active turns.
		if not bool(getattr(ws.runtime_state, "abort_requested", False)):
			TurnScheduler(
				max_actions_per_turn=self.max_actions_per_turn,
				max_replans_per_turn=self.max_replans_per_turn,
				trace_recorder=self.llm_trace_recorder,
			).run_active_phase(ws, settlement)

		events_in_tick_records: list[dict[str, Any]] = []
		for rec in list(getattr(ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			seq = int(rec.get("seq", 0) or 0)
			if seq > int(start_event_seq):
				events_in_tick_records.append(dict(rec))
		return events_in_tick_records
