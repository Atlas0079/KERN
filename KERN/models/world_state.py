from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .entity import Entity
from .gametime import GameTime
from .environment import EnvironmentScope
from .location import Location
from .components import ContainerComponent
from .task import Task
from .path import Path
from .runtime_state import RuntimeState


@dataclass
class WorldState:
	"""
	Single Source of Truth for backend world state.
	Align with Godot's `WorldManager.gd` core indexing capabilities, but this is a pure data structure.
	"""

	game_time: GameTime = field(default_factory=GameTime)

	entities: dict[str, Entity] = field(default_factory=dict)
	locations: dict[str, Location] = field(default_factory=dict)
	environment_scopes: dict[str, EnvironmentScope] = field(default_factory=dict)
	tasks: dict[str, Task] = field(default_factory=dict)

	paths: dict[str, Path] = field(default_factory=dict)

	# Named bundle registry: loaded from Bundles.json, referenced by InvokeBundle via ref
	named_bundles: dict[str, Any] = field(default_factory=dict)

	# Runtime service registry (Injected by WorldManager, used by executor/effects and systems)
	# Convention keys (Extensible):
	# - "interaction_engine"
	# - "workflow_registry"
	# - "default_action_provider"
	# - "action_providers"
	# - "request_stop"
	# - "execute"
	services: dict[str, Any] = field(default_factory=dict)

	runtime_state: RuntimeState = field(default_factory=RuntimeState)




	# World event log (For observation/debug)
	# Convention: Each record contains tick + location (For "visible in same location" filtering)
	event_log: list[dict[str, Any]] = field(default_factory=list)
	_event_seq: int = 0

	# Interaction/Recipe level log (Structured source of "readable event stream" for LLM/Planner)
	# Explanation:
	# - Record every ActionAttempt (Both success/failure)
	# - Record necessary "name snapshots" to avoid inability to render narrative after entity destruction
	interaction_log: list[dict[str, Any]] = field(default_factory=list)
	_interaction_seq: int = 0

	def record_interaction_attempt(
		self,
		actor_id: str,
		verb: str,
		target_id: str,
		status: str,
		reason: str = "",
		recipe_id: str = "",
		extra: dict[str, Any] | None = None,
		task_id: str = "",
	) -> dict[str, Any]:
		"""
		Record an action attempt (ActionAttempt / InteractionAttempt).

		Convention fields:
		- actor_id/target_id/verb/recipe_id/status/reason
		- actor_name/target_name: Name snapshots (For multi-perspective rendering after entity destruction)
		- location_id: Location snapshot (For "visible in same location" filtering)
		"""

		aid = str(actor_id or "")
		target_identifier = str(target_id or "")
		v = str(verb or "")
		st = str(status or "")
		rs = str(reason or "")
		rid = str(recipe_id or "")
		task_identifier = str(task_id or "")

		actor = self.get_entity_by_id(aid) if aid else None
		target = self.get_entity_by_id(target_identifier) if target_identifier else None

		actor_name = str(getattr(actor, "entity_name", "") or aid)
		if actor is not None:
			actor_setting = actor.get_component("AgentSetting")
			if actor_setting is not None:
				actor_name = str(getattr(actor_setting, "agent_name", "") or actor_name)
		target_name = str(getattr(target, "entity_name", "") or target_identifier)
		if target is not None:
			target_setting = target.get_component("AgentSetting")
			if target_setting is not None:
				target_name = str(getattr(target_setting, "agent_name", "") or target_name)

		loc_id = ""
		if aid:
			loc = self.get_location_of_entity(aid)
			if loc is not None:
				loc_id = str(getattr(loc, "location_id", "") or "")

		self._interaction_seq += 1
		interaction_id = f"interaction_{int(self._interaction_seq)}"
		record: dict[str, Any] = {
				"seq": int(self._interaction_seq),
				"interaction_id": interaction_id,
				"tick": int(getattr(self.game_time, "total_ticks", 0)),
				"time_str": str(getattr(self.game_time, "time_to_string", lambda: "")() or ""),
				"location_id": loc_id,
				"actor_id": aid,
				"actor_name": actor_name,
				"verb": v,
				"target_id": target_identifier,
				"target_name": target_name,
				"recipe_id": rid,
				"task_id": task_identifier,
				"status": st,
				"reason": rs,
		}
		if isinstance(extra, dict) and extra:
			for k, val in extra.items():
				if str(k) in {
					"seq",
					"interaction_id",
					"tick",
					"time_str",
					"location_id",
					"actor_id",
					"actor_name",
					"verb",
					"target_id",
					"target_name",
					"recipe_id",
					"task_id",
					"status",
					"reason",
					"perceived_by_agent_ids",
				}:
					continue
				record[str(k)] = deepcopy(val)
		self.interaction_log.append(record)
		return record

	def record_event(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> None:
		"""
		Record a world event to event_log.

		Explanation:
		- event is the event dict returned by executor (e.g., PropertyModified/EntityDestroyed/TaskFinished)
		- context is mainly used to supplement actor_id (usually agent_id) and location info
		"""

		if not isinstance(event, dict):
			return

		ctx = context or {}
		actor_id = str(ctx.get("self_id", "") or ctx.get("actor_id", "") or "")

		loc_id = ""
		if actor_id:
			loc = self.get_location_of_entity(actor_id)
			if loc is not None:
				loc_id = str(getattr(loc, "location_id", "") or "")

		self._event_seq += 1
		record = {
			"seq": int(self._event_seq),
			"tick": int(getattr(self.game_time, "total_ticks", 0)),
			"location_id": loc_id,
			"actor_id": actor_id,
			"event": dict(event),
		}
		self.event_log.append(record)

	def register_entity(self, entity: Entity) -> None:
		if entity.entity_id in self.entities:
			raise ValueError(f"entity id already exists: {entity.entity_id}")
		self.entities[entity.entity_id] = entity

	def register_location(self, location: Location) -> None:
		if location.location_id in self.locations:
			raise ValueError(f"location id already exists: {location.location_id}")
		self.locations[location.location_id] = location

	def register_environment_scope(self, scope: EnvironmentScope) -> None:
		if scope.scope_id in self.environment_scopes:
			raise ValueError(f"environment scope id already exists: {scope.scope_id}")
		self.environment_scopes[scope.scope_id] = scope

	def register_task(self, task: Task) -> None:
		if task.task_id in self.tasks:
			raise ValueError(f"task id already exists: {task.task_id}")
		self.tasks[task.task_id] = task

	def get_entity_by_id(self, entity_id: str) -> Entity | None:
		return self.entities.get(entity_id)

	def get_location_by_id(self, location_id: str) -> Location | None:
		return self.locations.get(location_id)

	def get_environment_scope_by_id(self, scope_id: str) -> EnvironmentScope | None:
		return self.environment_scopes.get(scope_id)

	def get_environment_for_location(self, location_id: str) -> dict[str, Any]:
		lid = str(location_id or "").strip()
		if not lid:
			return {}
		merged: dict[str, Any] = {}
		scopes = sorted(
			[
				scope
				for scope in list(self.environment_scopes.values())
				if scope is not None and scope.covers_location(lid)
			],
			key=lambda scope: (int(getattr(scope, "priority", 0) or 0), str(getattr(scope, "scope_id", "") or "")),
		)
		for scope in scopes:
			fields = getattr(scope, "fields", {}) or {}
			if isinstance(fields, dict):
				for key, value in fields.items():
					merged[str(key)] = value
		return merged

	def get_environment_field(self, location_id: str, key: str, default: Any = None) -> Any:
		name = str(key or "").strip()
		if not name:
			return default
		env = self.get_environment_for_location(location_id)
		return env.get(name, default)

	def get_task_by_id(self, task_id: str) -> Task | None:
		return self.tasks.get(task_id)

	def register_path(self, path: Path) -> None:
		if path.path_id in self.paths:
			raise ValueError(f"path id already exists: {path.path_id}")
		self.paths[path.path_id] = path

	def get_path_by_id(self, path_id: str) -> Path | None:
		return self.paths.get(path_id)

	def get_paths_from(self, location_id: str) -> list[Path]:
		return [p for p in self.paths.values() if p.from_location_id == location_id]

	def unregister_task(self, task_id: str) -> None:
		self.tasks.pop(task_id, None)

	# --- Location Resolution (Align with Godot WorldManager.get_location_of_entity) ---
	# locations store only direct/top-level entity IDs. Nested entities derive their
	# physical location through the container chain.
	def get_location_of_entity(self, entity_id: str) -> Location | None:
		visited: set[str] = set()
		return self._resolve_location_for_entity(entity_id, visited)

	def _resolve_location_for_entity(self, entity_id: str, visited: set[str]) -> Location | None:
		if not entity_id:
			return None
		if entity_id in visited:
			return None
		visited.add(entity_id)

		# 1) Search directly in location list
		for loc in self.locations.values():
			if entity_id in loc.entities_in_location:
				return loc

		# 2) If not in location, try to find its direct container entity
		parent_container = self._find_container_entity_holding_item(entity_id)
		if parent_container is not None:
			return self._resolve_location_for_entity(parent_container.entity_id, visited)

		return None

	def _find_container_entity_holding_item(self, item_id: str) -> Entity | None:
		for ent in self.entities.values():
			comp = ent.get_component("ContainerComponent")
			if isinstance(comp, ContainerComponent):
				if item_id in comp.get_all_item_ids():
					return ent
		return None

	def get_top_level_entity_ids_in_location(self, location_id: str) -> list[str]:
		loc = self.get_location_by_id(location_id)
		if loc is None:
			return []
		return [str(x) for x in list(loc.entities_in_location or []) if str(x)]

	def get_all_entity_ids_in_location(self, location_id: str, include_nested: bool = True) -> list[str]:
		out: list[str] = []
		seen: set[str] = set()
		for entity_id in self.get_top_level_entity_ids_in_location(location_id):
			if entity_id in seen:
				continue
			seen.add(entity_id)
			out.append(entity_id)
			if include_nested:
				for child_id in self.collect_descendant_item_ids(entity_id):
					if child_id in seen:
						continue
					seen.add(child_id)
					out.append(child_id)
		return out

	def remove_entity_from_all_locations(self, entity_id: str) -> None:
		eid = str(entity_id or "")
		if not eid:
			return
		for loc in self.locations.values():
			while eid in loc.entities_in_location:
				loc.entities_in_location.remove(eid)

	# --- Location Index Maintenance (top-level placement only) ---
	def ensure_entity_in_location(self, entity_id: str, location_id: str) -> None:
		loc = self.get_location_by_id(location_id)
		if loc is None:
			return
		if entity_id not in loc.entities_in_location:
			loc.entities_in_location.append(entity_id)



	def collect_descendant_item_ids(self, root_entity_id: str) -> list[str]:
		"""
		Recursively collect descendant item IDs of container entity (Align with Godot collect_descendant_item_ids).
		"""
		collected: list[str] = []
		root = self.get_entity_by_id(root_entity_id)
		if root is None:
			return collected
		comp = root.get_component("ContainerComponent")
		if not isinstance(comp, ContainerComponent):
			return collected
		for child_id in comp.get_all_item_ids():
			collected.append(child_id)
			collected.extend(self.collect_descendant_item_ids(child_id))
		return collected
