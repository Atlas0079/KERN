from __future__ import annotations
import json

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from ..data.checkpoint import build_checkpoint_payload_from_world_state
from ..log_manager import get_logger
from ..models.world_state import WorldState
from .memory_capture import MemoryCaptureSystem
from .trigger_system import TriggerSystem


@dataclass
class WorldManager:
	"""
	Python version of WorldManager (Automatic simulation loop scheduler).

	Responsibilities:
	- Advance time (tick)
	- Dispatch AdvanceTick per entity
	- Build reaction effects via TriggerSystem
	- Execute effects through executor and chain follow-up reactions

	Explanation:
	- This class does not directly write WorldState details; specific writes should be done by executor.
	"""

	world_state: WorldState
	interaction_engine: Any
	executor: Any
	perception_system: Any
	action_provider: Any

	is_running: bool = False
	ticks_per_step: int = 1
	max_trigger_depth: int = 4

	# Optional: Route different action providers by provider_id (Player/LLM/Script/Replay, etc.)
	# If an entity's controller provider_id is not in this table, the entity will not produce actions in the decision loop (Safe default).
	action_providers: dict[str, Any] = field(default_factory=dict)
	reaction_rules: list[dict[str, Any]] = field(default_factory=list)
	trigger_system: TriggerSystem | None = None
	memory_capture_system: MemoryCaptureSystem | None = None

	# Snapshot storage
	snapshots: list[dict[str, Any]] = field(default_factory=list)
	checkpoint_enabled: bool = True
	checkpoint_dir: str = ""
	checkpoint_include_logs: bool = True
	dialogue_log_full: bool = False

	def __post_init__(self) -> None:
		if self.trigger_system is None:
			self.trigger_system = TriggerSystem(rules=list(self.reaction_rules or []))
		if self.memory_capture_system is None:
			self.memory_capture_system = MemoryCaptureSystem()
		if self.checkpoint_enabled:
			base_dir = str(self.checkpoint_dir or "").strip()
			if not base_dir:
				base_dir = str(Path.cwd() / "checkpoints")
			self.checkpoint_dir = base_dir
			Path(self.checkpoint_dir).mkdir(parents=True, exist_ok=True)

	def run(self, max_ticks: int = 100) -> list[dict[str, Any]]:
		self.is_running = True
		all_events: list[dict[str, Any]] = []

		# Initial snapshot (Tick 0)
		self._capture_snapshot(events_in_tick=[])
		self._save_checkpoint()

		while self.is_running and self.world_state.game_time.total_ticks < max_ticks:
			tick_events = self.step()
			all_events.extend(tick_events)
			
			# Capture snapshot at end of tick
			self._capture_snapshot(events_in_tick=tick_events)
			self._save_checkpoint()

		return all_events

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

	def _serialize_any(self, value: Any) -> Any:
		if value is None or isinstance(value, (str, int, float, bool)):
			return value
		if str(getattr(getattr(value, "__class__", None), "__name__", "")) == "DecisionArbiterComponent":
			return self._serialize_arbiter_component(value)
		if isinstance(value, dict):
			return {str(k): self._serialize_any(v) for k, v in value.items()}
		if isinstance(value, (list, tuple, set)):
			return [self._serialize_any(v) for v in value]
		if is_dataclass(value):
			return self._serialize_any(asdict(value))
		if hasattr(value, "__dict__"):
			return self._serialize_any(dict(vars(value)))
		return str(value)

	def _serialize_arbiter_component(self, arb: Any) -> dict[str, Any]:
		rules_out: list[dict[str, Any]] = []
		for r in list(getattr(arb, "ruleset", []) or []):
			if isinstance(r, dict):
				rule_type = str(r.get("type", "") or "").strip()
				if rule_type:
					rules_out.append({str(k): self._serialize_any(v) for k, v in r.items()})
				continue
			rule_class = str(getattr(getattr(r, "__class__", None), "__name__", "") or "")
			priority = int(getattr(r, "priority", 999) or 999)
			if rule_class == "LowNutritionRule":
				rules_out.append(
					{
						"type": "LowNutrition",
						"priority": priority,
						"threshold": float(getattr(r, "threshold", 50.0) or 50.0),
					}
				)
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
				rules_out.append(
					{
						"type": "CorpseSighted",
						"priority": priority,
						"trigger_on_new_corpse": bool(getattr(r, "trigger_on_new_corpse", True)),
					}
				)
				continue
			if rule_class == "IdleRule":
				rules_out.append({"type": "Idle", "priority": priority})
		return {
			"rules": rules_out,
			"active_interrupt_preset_id": str(getattr(arb, "active_interrupt_preset_id", "") or ""),
			"interrupt_presets": self._serialize_any(dict(getattr(arb, "interrupt_presets", {}) or {})),
			"interrupt_preset_descriptions": self._serialize_any(dict(getattr(arb, "interrupt_preset_descriptions", {}) or {})),
			"interrupt_runtime_state": self._serialize_any(dict(getattr(arb, "interrupt_runtime_state", {}) or {})),
			"_runtime_preset_id": str(getattr(arb, "_runtime_preset_id", "") or ""),
		}

	def _build_checkpoint_payload(self) -> dict[str, Any]:
		return build_checkpoint_payload_from_world_state(self.world_state, include_logs=bool(self.checkpoint_include_logs))

	def _save_checkpoint(self) -> None:
		if not self.checkpoint_enabled:
			return
		logger = get_logger()
		ws = self.world_state
		tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
		dir_path = Path(str(self.checkpoint_dir))
		dir_path.mkdir(parents=True, exist_ok=True)
		target_path = dir_path / f"tick_{tick:06d}.json"
		tmp_path = dir_path / f"tick_{tick:06d}.tmp"
		payload = self._build_checkpoint_payload()
		try:
			with tmp_path.open("w", encoding="utf-8") as f:
				json.dump(payload, f, ensure_ascii=False, indent=2)
			tmp_path.replace(target_path)
			logger.debug("checkpoint", "saved", context={"tick": tick, "path": str(target_path)})
		except Exception as e:
			logger.warn("checkpoint", "save_failed", context={"tick": tick, "path": str(target_path), "error": str(e)})

	def stop(self) -> None:
		self.is_running = False

	def step(self) -> list[dict[str, Any]]:
		"""
		Advance one simulation tick (Turn-based).
		"""
		events: list[dict[str, Any]] = []
		logger = get_logger()
		ws = self.world_state
		start_event_seq = int(getattr(ws, "_event_seq", 0) or 0)

		# 1) Inject runtime services for effect execution stack.
		if self.trigger_system is not None:
			self.trigger_system.begin_tick()

		self.world_state.services = {
			"perception_system": self.perception_system,
			"interaction_engine": self.interaction_engine,
			"default_action_provider": self.action_provider,
			"action_providers": dict(self.action_providers or {}),
			"dialogue_budget_limit_per_location": 4,
			"dialogue_budget_used_per_location": {},
			"dialogue_log_full": bool(self.dialogue_log_full),
			"memory_capture_system": self.memory_capture_system,
		}

		# 2) Advance time
		self.world_state.game_time.advance_ticks(self.ticks_per_step)
		events.append(
			{
				"type": "TickAdvanced",
				"total_ticks": ws.game_time.total_ticks,
				"time": ws.game_time.time_to_string(),
			}
		)
		logger.debug("tick", "tick_advanced", context=dict(events[-1]))
		ws.record_event(events[-1], {"actor_id": ""})

		# Effect execution wrapper with recursive reaction chaining.
		def execute_wrapper(effect: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
			collected_events: list[dict[str, Any]] = []
			def execute_with_reactions(eff: dict[str, Any], ctx: dict[str, Any], depth: int) -> None:
				logger.debug("effect", "execute", context={"effect": dict(eff or {}), "context": dict(ctx or {}), "depth": int(depth)})
				result_events = self.executor.execute(ws, eff, ctx)
				reaction_rule_id = str((ctx or {}).get("reaction_rule_id", "") or "")
				reaction_failed = False
				reaction_fail_reason = ""
				for _ev in list(result_events or []):
					if not isinstance(_ev, dict):
						continue
					if str(_ev.get("type", "") or "") == "ExecutorError":
						reaction_failed = True
						reaction_fail_reason = str(_ev.get("message", "") or "ExecutorError")
						logger.warn(
							"executor",
							"effect_failed",
							context={
								"effect": dict(eff or {}),
								"context": dict(ctx or {}),
								"error_event": dict(_ev),
								"depth": int(depth),
							},
						)
						break
				if reaction_rule_id and hasattr(ws, "record_interaction_attempt"):
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
							"effect_type": str((eff or {}).get("effect", "") or ""),
						},
					)
				for ev in list(result_events or []):
					if not isinstance(ev, dict):
						continue
					collected_events.append(dict(ev))
					ws.record_event(ev, ctx)
					events.append(ev)
					logger.trace("event", "record", context={"event": dict(ev), "context": dict(ctx or {}), "depth": int(depth)})
					if depth >= int(self.max_trigger_depth):
						limit_event = {
							"type": "ReactionDepthExceeded",
							"depth": int(depth),
							"max_trigger_depth": int(self.max_trigger_depth),
							"source_event_type": str(ev.get("type", "") or ""),
							"source_event_entity_id": str(ev.get("entity_id", "") or ""),
						}
						ws.record_event(limit_event, ctx)
						events.append(limit_event)
						continue
					if self.trigger_system is None:
						continue
					reqs = self.trigger_system.build_reaction_effects(ws, ev, ctx)
					for req in list(reqs or []):
						reff = req.get("effect", {}) or {}
						rctx = req.get("context", {}) or {}
						if isinstance(reff, dict) and isinstance(rctx, dict):
							execute_with_reactions(reff, rctx, depth + 1)

			execute_with_reactions(effect, context, 0)
			return collected_events

		ws.services["execute"] = execute_wrapper

		# 3) Dispatch AdvanceTick events per entity, then let Reactions decide which effects to run.
		for ent_id in list(ws.entities.keys()):
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
				reff = req.get("effect", {}) or {}
				rctx = req.get("context", {}) or {}
				if isinstance(reff, dict) and isinstance(rctx, dict):
					execute_wrapper(reff, rctx)

		if self.memory_capture_system is not None and hasattr(self.memory_capture_system, "summarize_all"):
			self.memory_capture_system.summarize_all(ws)

		events_in_tick_records: list[dict[str, Any]] = []
		for rec in list(getattr(ws, "event_log", []) or []):
			if not isinstance(rec, dict):
				continue
			seq = int(rec.get("seq", 0) or 0)
			if seq > int(start_event_seq):
				events_in_tick_records.append(dict(rec))
		return events_in_tick_records
