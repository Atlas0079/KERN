from __future__ import annotations

import unittest
from types import SimpleNamespace

from KERN.dynamic_text import DynamicTextError
from KERN.dynamic_text import render_dynamic_payload_text_fields, render_dynamic_text
from KERN.executor._effect_entity import execute_create_entity
from KERN.executor._effect_event import execute_emit_event
from KERN.executor._effect_memory import execute_add_memory_note
from KERN.executor.executor import WorldExecutor
from KERN.models.entity import Entity


class FakeLocation:
	def __init__(self, location_id: str) -> None:
		self.location_id = location_id
		self.entities_in_location: list[str] = []

	def add_entity_id(self, entity_id: str) -> None:
		if entity_id not in self.entities_in_location:
			self.entities_in_location.append(entity_id)


class FakeWorld:
	def __init__(self) -> None:
		self.entities: dict[str, Entity] = {}
		self.locations = {"medbay": FakeLocation("medbay")}
		self.game_time = SimpleNamespace(total_ticks=7)

	def get_entity_by_id(self, entity_id: str):
		return self.entities.get(str(entity_id))

	def register_entity(self, entity: Entity) -> None:
		self.entities[str(entity.entity_id)] = entity

	def get_location_by_id(self, location_id: str):
		return self.locations.get(str(location_id))

	def ensure_entity_in_location(self, entity_id: str, location_id: str) -> None:
		loc = self.get_location_by_id(location_id)
		if loc is not None:
			loc.add_entity_id(entity_id)

	def get_location_of_entity(self, entity_id: str):
		for loc in self.locations.values():
			if str(entity_id) in loc.entities_in_location:
				return loc
		return None


class DynamicTextTests(unittest.TestCase):
	def setUp(self) -> None:
		self.ws = FakeWorld()
		self.actor = Entity(entity_id="actor_01", template_id="Agent", entity_name="Eris")
		self.target = Entity(entity_id="target_01", template_id="Agent", entity_name="Mira")
		self.ws.register_entity(self.actor)
		self.ws.register_entity(self.target)
		self.ws.ensure_entity_in_location("actor_01", "medbay")
		self.ws.ensure_entity_in_location("target_01", "medbay")
		self.context = {
			"self_id": "actor_01",
			"target_id": "target_01",
			"event": {"location_id": "medbay"},
			"parameters": {"note": "met {target.entity_name}"},
		}

	def test_render_dynamic_text_reuses_context_refs(self) -> None:
		text = render_dynamic_text(
			self.ws,
			self.context,
			"{self.entity_name} saw {target.entity_name} in {event.location_id}: {param:note}",
		)
		self.assertEqual(text, "Eris saw Mira in medbay: met {target.entity_name}")

	def test_payload_renderer_only_touches_text_keys(self) -> None:
		payload = render_dynamic_payload_text_fields(
			self.ws,
			self.context,
			{"source_ref": "target", "message": "hello {target.entity_name}", "entity_id": "{target.entity_id}"},
		)
		self.assertEqual(payload["source_ref"], "target")
		self.assertEqual(payload["message"], "hello Mira")
		self.assertEqual(payload["entity_id"], "{target.entity_id}")

	def test_unknown_placeholder_fails_in_text_field(self) -> None:
		with self.assertRaises(DynamicTextError):
			render_dynamic_text(self.ws, self.context, "hello {unknown.value}")

	def test_create_entity_spawn_name_renders_once(self) -> None:
		executor = WorldExecutor(entity_templates={"Corpse": {"name": "Corpse", "components": {}}})
		events = execute_create_entity(
			executor,
			self.ws,
			{
				"effect": "CreateEntity",
				"template": "Corpse",
				"instance_id": "corpse_01",
				"destination": {"type": "location", "target": "medbay"},
				"spawn_patch": {"name": "{target.entity_name} corpse"},
			},
			self.context,
		)
		self.assertEqual(events[0]["type"], "EntityCreated")
		self.assertEqual(self.ws.get_entity_by_id("corpse_01").entity_name, "Mira corpse")

	def test_memory_note_text_renders_before_storage(self) -> None:
		executor = WorldExecutor()
		events = execute_add_memory_note(
			executor,
			self.ws,
			{"effect": "AddMemoryNote", "target": "self", "text": "remember {target.entity_name}"},
			self.context,
		)
		self.assertEqual(events[0]["type"], "MemoryNoteAdded")
		self.assertEqual(events[0]["text"], "remember Mira")

	def test_emit_event_payload_text_key_renders(self) -> None:
		executor = WorldExecutor()
		events = execute_emit_event(
			executor,
			self.ws,
			{
				"effect": "EmitEvent",
				"event_type": "MessageBroadcasted",
				"payload": {"source_ref": "target", "message": "hello {target.entity_name}"},
			},
			self.context,
		)
		self.assertEqual(events[0]["type"], "MessageBroadcasted")
		self.assertEqual(events[0]["source_id"], "target_01")
		self.assertEqual(events[0]["message"], "hello Mira")


if __name__ == "__main__":
	unittest.main()
