from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from newserver.log_manager import configure_logger, get_logger
from newserver.data.loader import load_data_bundle
from newserver.data.checkpoint import resolve_checkpoint_file, restore_world_state_from_checkpoint
from newserver.data.validator import validate_bundle
from newserver.data.builder import build_world_state
from newserver.sim.manager import WorldManager
from newserver.sim.perception import PerceptionSystem
from newserver.interaction.engine import InteractionEngine
from newserver.executor.executor import WorldExecutor
from newserver.agents.simple_policy import SimplePolicyActionProvider
from newserver.agents.llm_action_provider import build_default_llm_provider


def _resolve_runtime_config_path(project_root: Path, cli_config_path: str = "") -> Path:
	raw_cli = str(cli_config_path or "").strip()
	raw_env = str(os.environ.get("RUNTIME_CONFIG_FILE", "") or "").strip()
	raw = raw_cli or raw_env or "runtime_config.json"
	p = Path(raw)
	if p.is_absolute():
		return p
	return project_root / p


def _load_runtime_config(project_root: Path, cli_config_path: str = "") -> tuple[dict[str, str], Path]:
	config_path = _resolve_runtime_config_path(project_root, cli_config_path)
	if not config_path.exists():
		raise FileNotFoundError(f"runtime config not found: {config_path}")
	raw = json.loads(config_path.read_text(encoding="utf-8"))
	if not isinstance(raw, dict):
		raise ValueError(f"runtime config must be object with key 'env': {config_path}")
	env_raw = raw.get("env")
	if not isinstance(env_raw, dict):
		raise ValueError(f"runtime config must use {{'env': {{...}}}} format: {config_path}")
	env_map: dict[str, object] = dict(env_raw)
	out: dict[str, str] = {}
	for k, v in env_map.items():
		key = str(k or "").strip()
		if not key:
			continue
		if v is None:
			continue
		out[key] = str(v)
	return out, config_path


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


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", dest="config_path", default="", help="runtime config file path")
	args = parser.parse_args(argv)
	project_root = Path(__file__).resolve().parent
	cfg, cfg_path = _load_runtime_config(project_root, str(args.config_path or ""))
	configure_logger(
		level=_cfg_get(cfg, "LOG_LEVEL", "info"),
		categories=_cfg_get(cfg, "LOG_CATEGORIES", "*"),
		json_mode=_cfg_bool(cfg, "LOG_JSON", False),
		buffer_size=_cfg_int(cfg, "LOG_BUFFER_SIZE", 1000),
	)
	logger = get_logger()
	logger.info("system", "runtime_config_loaded", context={"path": str(cfg_path)})

	recipes_jsons = [x.strip() for x in _cfg_get(cfg, "RECIPES_JSONS", "Recipes.json").split(",") if x.strip()]
	reactions_jsons = [x.strip() for x in _cfg_get(cfg, "REACTIONS_JSONS", "Reactions.json").split(",") if x.strip()]
	entities_dirs = [x.strip() for x in _cfg_get(cfg, "ENTITIES_DIRS", "Entities").split(",") if x.strip()]
	world_json_name = _cfg_get(cfg, "WORLD_JSON", "World.json")

	bundle = load_data_bundle(
		project_root,
		recipes_jsons=recipes_jsons,
		reactions_jsons=reactions_jsons,
		entities_dirs=entities_dirs,
		world_json=world_json_name,
	)
	restore_file_env = _cfg_get(cfg, "CHECKPOINT_RESTORE_FILE", "")
	restore_dir_env = _cfg_get(cfg, "CHECKPOINT_RESTORE_DIR", "")
	restore_path = resolve_checkpoint_file(restore_file_env, restore_dir_env)
	if restore_path is not None:
		ws = restore_world_state_from_checkpoint(restore_path, bundle.entity_templates)
		if not ws.entities or not ws.locations:
			raise ValueError(f"Invalid checkpoint format or empty world state: {restore_path}")
		logger.info("checkpoint", "restored", context={"path": str(restore_path), "tick": int(ws.game_time.total_ticks)})
	else:
		validation_mode = _cfg_get(cfg, "VALIDATION_MODE", "fast").lower() or "fast"
		report = validate_bundle(bundle, mode=validation_mode)
		if not report.ok:
			raise ValueError("Data validation failed:\n" + "\n".join(report.errors))
		logger.info("system", "data_validated", context={"mode": report.mode, "warnings": len(report.warnings)})
		result = build_world_state(bundle.world, bundle.entity_templates, bundle.recipes)
		ws = result.world_state
	logger.info(
		"system",
		"world_loaded",
		context={
			"time": ws.game_time.time_to_string(),
			"ticks": int(ws.game_time.total_ticks),
			"locations": list(ws.locations.keys()),
			"entities": list(ws.entities.keys()),
		},
	)

	# Select first controllable agent in world
	agent_id = ""
	for ent in ws.entities.values():
		if ent.get_component("AgentControlComponent") is not None:
			agent_id = ent.entity_id
			break
	if not agent_id:
		raise ValueError("No controllable agent found in world")
	loc = ws.get_location_of_entity(agent_id)
	logger.info("system", "agent_location", context={"agent_id": agent_id, "location_id": loc.location_id if loc else None})

	# Task progression regression test (Sleep 60 ticks)
	agent = ws.get_entity_by_id(agent_id)
	worker = agent.get_component("WorkerComponent") if agent else None
	current_task_id = getattr(worker, "current_task_id", "") if worker else ""
	logger.info("system", "agent_task_state", context={"agent_id": agent_id, "current_task_id": str(current_task_id or "")})
	if current_task_id:
		task = ws.get_task_by_id(current_task_id)
		if task:
			logger.info(
				"task",
				"task_loaded",
				context={
					"task_id": str(task.task_id),
					"task_type": str(task.task_type),
					"progress": float(task.progress),
					"required_progress": float(task.required_progress),
					"progressor": str(task.progressor_id or "<default>"),
				},
			)

	# Print perception results once to confirm if container hiding is effective
	perception = PerceptionSystem().perceive(ws, agent_id)
	logger.info(
		"interaction",
		"perception_snapshot",
		context={
			"agent_id": agent_id,
			"visible_entity_ids": [e.get("id") for e in perception.get("entities", [])],
			"visible_entities": [
				{
					"id": e.get("id"),
					"name": e.get("name"),
					"tags": list(e.get("tags", []) or []),
				}
				for e in perception.get("entities", [])
			],
			"hidden_entity_count": perception.get("hidden_entity_count"),
		},
	)

	if _cfg_bool(cfg, "DEMO_DURATION_TEST", False):
		if worker is not None:
			worker.stop_task()
		logger.info("task", "task_stopped_for_demo", context={"current_task_id": getattr(worker, "current_task_id", "") if worker else ""})
		sleep_result = InteractionEngine(recipe_db=bundle.recipes).process_command(
			ws,
			agent_id,
			{"verb": "Wait", "target_id": agent_id, "parameters": {"wait_ticks": 6}},
		)
		logger.info(
			"interaction",
			"sleep_command_result",
			context={"status": sleep_result.get("status"), "reason": sleep_result.get("reason"), "message": sleep_result.get("message")},
		)
		if sleep_result.get("status") == "success":
			for effect in sleep_result.get("effects", []):
				WorldExecutor(entity_templates=bundle.entity_templates).execute(ws, effect, sleep_result.get("context", {}) or {})
		logger.info("task", "task_after_sleep", context={"current_task_id": getattr(worker, "current_task_id", "") if worker else ""})

	use_llm = _cfg_bool(cfg, "USE_LLM", False)
	action_provider = build_default_llm_provider(cfg) if use_llm else SimplePolicyActionProvider()
	max_ticks_env = _cfg_get(cfg, "MAX_TICKS", "")
	default_max_ticks_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_LLM", 15)
	default_max_ticks_no_llm = _cfg_int(cfg, "MAX_TICKS_DEFAULT_NO_LLM", 65)
	max_ticks = int(max_ticks_env) if max_ticks_env else (default_max_ticks_llm if use_llm else default_max_ticks_no_llm)
	max_trigger_depth = _cfg_int(cfg, "MAX_TRIGGER_DEPTH", 4)
	dialogue_budget_limit_per_location = _cfg_int(cfg, "DIALOGUE_BUDGET_LIMIT_PER_LOCATION", 4)
	checkpoint_enabled = _cfg_bool(cfg, "CHECKPOINT_EVERY_TICK", True)
	checkpoint_include_logs = _cfg_bool(cfg, "CHECKPOINT_INCLUDE_LOGS", True)
	dialogue_log_full = _cfg_bool(cfg, "DIALOGUE_LOG_FULL", False)
	default_checkpoint_dir = project_root / "checkpoints" / (world_json_name or "default")
	checkpoint_dir_env = _cfg_get(cfg, "CHECKPOINT_DIR", "")
	checkpoint_dir = checkpoint_dir_env if checkpoint_dir_env else str(default_checkpoint_dir)
	manager = WorldManager(
		world_state=ws,
		interaction_engine=InteractionEngine(recipe_db=bundle.recipes),
		executor=WorldExecutor(entity_templates=bundle.entity_templates),
		perception_system=PerceptionSystem(),
		action_provider=action_provider,
		reaction_rules=list((bundle.reactions or {}).get("rules", []) or []),
		max_trigger_depth=max_trigger_depth,
		dialogue_budget_limit_per_location=dialogue_budget_limit_per_location,
		checkpoint_enabled=checkpoint_enabled,
		checkpoint_dir=checkpoint_dir,
		checkpoint_include_logs=checkpoint_include_logs,
		dialogue_log_full=dialogue_log_full,
	)
	events = manager.run(max_ticks=max_ticks)
	logger.info("system", "run_finished", context={"event_count": len(events), "ticks": int(ws.game_time.total_ticks)})

	# LLM demo: Print a segment of "interactive narrative" to make behavior look more intuitive
	if use_llm:
		ps = PerceptionSystem()
		perception = ps.perceive(ws, agent_id)
		logger.info(
			"interaction",
			"short_term_memory_rendered",
			context={
				"agent_id": agent_id,
				"short_term_memory_text": str((perception or {}).get("short_term_memory_text", "") or ""),
			},
		)

	# Finally check if the task has been cleaned up
	if current_task_id:
		task_after = ws.get_task_by_id(current_task_id)
		logger.info("task", "task_after_run", context={"task_id": str(current_task_id), "task": str(task_after)})


if __name__ == "__main__":
	main()
