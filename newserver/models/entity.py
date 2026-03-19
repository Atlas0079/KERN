from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .components import (
	AgentSetting,
	AgentControlComponent,
	ContainerComponent,
	CreatureComponent,
	DecisionArbiterComponent,
	LogicControlComponent,
	MemoryComponent,
	PlayerControlComponent,
	TagComponent,
	TaskHostComponent,
	UnknownComponent,
	WorkerComponent,
)


ComponentValue = (
	TagComponent
	| ContainerComponent
	| CreatureComponent
	| AgentSetting
	| AgentControlComponent
	| PlayerControlComponent
	| LogicControlComponent
	| MemoryComponent
	| DecisionArbiterComponent
	| TaskHostComponent
	| UnknownComponent
	| WorkerComponent
)


@dataclass
class Entity:
	entity_id: str
	template_id: str
	entity_name: str = "Unnamed Entity"

	volume: float = 1.0
	weight: float = 1.0

	# component_name -> component_state
	components: dict[str, ComponentValue] = field(default_factory=dict)

	def add_component(self, component_name: str, component_value: ComponentValue) -> None:
		if component_name in self.components:
			raise ValueError(f"component already exists: {component_name}")
		self.components[component_name] = component_value

	def get_component(self, component_name: str) -> ComponentValue | None:
		return self.components.get(component_name)

	def has_component(self, component_name: str) -> bool:
		return component_name in self.components

	# --- Tag helpers (Align with Godot Entity.has_tag/get_all_tags) ---
	def has_tag(self, tag_name: str) -> bool:
		comp = self.components.get("TagComponent")
		if isinstance(comp, TagComponent):
			return comp.has_tag(tag_name)
		return False

	def get_all_tags(self) -> list[str]:
		comp = self.components.get("TagComponent")
		if isinstance(comp, TagComponent):
			return list(comp.tags)
		return []

	# --- Container helpers ---
	def get_container_item_ids(self) -> list[str]:
		comp = self.components.get("ContainerComponent")
		if isinstance(comp, ContainerComponent):
			return comp.get_all_item_ids()
		return []

	# --- Minimal sanity hooks ---
	def ensure_initialized(self) -> None:
		creature = self.components.get("CreatureComponent")
		if isinstance(creature, CreatureComponent):
			creature.ensure_initialized()
