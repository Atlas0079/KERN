from __future__ import annotations

from copy import deepcopy
from typing import Any

from .component_catalog import ComponentCatalog
from .models.world_state import WorldState


class RuntimeSnapshotBuilder:
	"""Build complete, detached runtime debug snapshots through one catalog."""

	def __init__(self, component_catalog: ComponentCatalog) -> None:
		self._component_catalog = component_catalog

	def capture(self, ws: WorldState, events_in_tick: list[dict[str, object]]) -> dict[str, object]:
		entities: dict[str, dict[str, object]] = {}
		for entity_id, entity in ws.entities.items():
			component_state: dict[str, object] = {}
			for component_id, component in entity.components.items():
				try:
					component_state[str(component_id)] = deepcopy(self._component_catalog.serialize(str(component_id), component))
				except Exception as exc:
					raise ValueError(f"runtime snapshot serialization failed for entity {entity_id}, component {component_id}: {exc}") from exc
			location = ws.get_location_of_entity(entity_id)
			entities[entity_id] = {
				"template_id": entity.template_id,
				"name": entity.entity_name,
				"location_id": location.location_id if location else None,
				"component_state": component_state,
				"components": self._core_display_projection(ws, entity),
			}

		locations = {
			location_id: {"entities": list(location.entities_in_location)}
			for location_id, location in ws.locations.items()
		}
		current_tick = int(ws.game_time.total_ticks)
		interactions = [dict(item) for item in list(getattr(ws, "interaction_log", []) or []) if item.get("tick") == current_tick]
		return {
			"schema_version": "runtime_snapshot.v2",
			"tick": ws.game_time.total_ticks,
			"time_str": ws.game_time.time_to_string(),
			"entities": entities,
			"locations": locations,
			"events": [deepcopy(dict(event)) for event in events_in_tick],
			"interactions": [deepcopy(item) for item in interactions],
		}

	@staticmethod
	def _core_display_projection(ws: WorldState, entity: Any) -> dict[str, object]:
		components: dict[str, object] = {}
		creature = entity.get_component("CreatureComponent")
		if creature:
			components["CreatureComponent"] = {
				"nutrition": getattr(creature, "current_nutrition", 0),
				"energy": getattr(creature, "current_energy", 0),
				"state": getattr(creature, "current_state", "Idle"),
			}
		worker = entity.get_component("WorkerComponent")
		if worker:
			task_id = getattr(worker, "current_task_id", "")
			task = ws.get_task_by_id(task_id) if task_id else None
			components["WorkerComponent"] = {
				"current_task_id": task_id,
				"current_action_desc": str(getattr(task, "task_type", "") or ""),
			}
		container = entity.get_component("ContainerComponent")
		if container and hasattr(container, "slots"):
			components["ContainerComponent"] = {
				"slots": {
					str(slot_id): {"items": list(getattr(slot, "items", []) or []), "config": dict(getattr(slot, "config", {}) or {})}
					for slot_id, slot in container.slots.items()
				}
			}
		return components
