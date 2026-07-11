from __future__ import annotations

import argparse
from pathlib import Path

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.log_manager import get_logger
from KERN.runtime import KernRuntime


def _first_controllable_agent_id(runtime: KernRuntime) -> str:
	for ent in runtime.world_state.entities.values():
		if ent.get_component("AgentControlComponent") is not None:
			return str(ent.entity_id)
	return ""


def _log_initial_runtime_state(runtime: KernRuntime) -> str:
	logger = get_logger()
	ws = runtime.world_state
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
	agent_id = _first_controllable_agent_id(runtime)
	if not agent_id:
		raise ValueError("No controllable agent found in world")
	loc = ws.get_location_of_entity(agent_id)
	logger.info("system", "agent_location", context={"agent_id": agent_id, "location_id": loc.location_id if loc else None})

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

	perception = build_agent_perception(build_full_ws_view(ws, agent_id, "", {}), agent_id)
	logger.info(
		"interaction",
		"perception_snapshot",
		context={
			"agent_id": agent_id,
			"visible_entity_ids": [e.get("id") for e in perception.get("entities", [])],
			"visible_entities": [
				{"id": e.get("id"), "name": e.get("name"), "tags": list(e.get("tags", []) or [])}
				for e in perception.get("entities", [])
			],
			"hidden_entity_count": perception.get("hidden_entity_count"),
		},
	)
	return agent_id


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", dest="config_path", default="", help="runtime config file path")
	parser.add_argument("--skip-validation", action="store_true", help="skip startup scenario data validation")
	args = parser.parse_args(argv)

	project_root = Path(__file__).resolve().parent
	runtime = KernRuntime.from_config(project_root, str(args.config_path or ""), validate=not bool(args.skip_validation))
	logger = get_logger()
	logger.info("system", "runtime_config_loaded", context={"path": str(runtime.config_path)})

	agent_id = _log_initial_runtime_state(runtime)

	events = runtime.run_configured()
	logger.info("system", "run_finished", context={"event_count": len(events), "ticks": int(runtime.world_state.game_time.total_ticks)})

	if str(runtime.runtime_config.get("USE_LLM", "") or "").strip().lower() in {"1", "true", "yes", "on"}:
		perception = build_agent_perception(build_full_ws_view(runtime.world_state, agent_id, "", {}), agent_id)
		logger.info(
			"interaction",
			"short_term_memory_rendered",
			context={"agent_id": agent_id, "short_term_memory_text": str((perception or {}).get("short_term_memory_text", "") or "")},
		)


if __name__ == "__main__":
	main()
