from __future__ import annotations

import unittest

from KERN.dynamic_text import DynamicTextError, render_dynamic_text
from KERN.interaction.narrative import render_interaction_narrative
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState


class InteractionDynamicTextTests(unittest.TestCase):
	def setUp(self) -> None:
		self.ws = WorldState()
		self.ws.register_entity(Entity(entity_id="actor", template_id="Agent", entity_name="Alice"))
		self.ws.register_entity(Entity(entity_id="target", template_id="Thing", entity_name="Lantern"))

	def test_shared_renderer_supports_interaction_aliases_and_paths(self) -> None:
		context = {
			"self_id": "actor",
			"target_id": "target",
			"parameters": {"to_location_id": "forest"},
			"event": {"input": {"value": 7}},
			"reason": "blocked",
		}
		self.assertEqual(
			render_dynamic_text(
				self.ws,
				context,
				"{actor} -> {target} -> {to_location_id} -> {event.input.value} -> {reason}",
			),
			"Alice -> Lantern -> forest -> 7 -> blocked",
		)

	def test_interaction_adapter_uses_shared_renderer(self) -> None:
		self.assertEqual(
			render_interaction_narrative(
				self.ws,
				"{actor}看见了{target}，原因是{reason}",
				{"self_id": "actor", "target_id": "target", "reason": "夜间"},
			),
			"Alice看见了Lantern，原因是夜间",
		)

	def test_unknown_interaction_placeholder_is_fatal_at_renderer_seam(self) -> None:
		with self.assertRaises(DynamicTextError):
			render_interaction_narrative(self.ws, "{event.missing}", {"self_id": "actor"})


if __name__ == "__main__":
	 unittest.main()
