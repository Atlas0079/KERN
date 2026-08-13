from __future__ import annotations

import unittest

from KERN.agent_workflow.interrupt_runtime import check_if_interrupt_is_needed
from KERN.executor.executor import WorldExecutor
from KERN.models.components import AgentControlComponent, CreatureComponent, AgentWakePolicyComponent
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState


def _agent() -> Entity:
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ent.add_component("AgentControlComponent", AgentControlComponent())
	ent.add_component(
		"AgentWakePolicyComponent",
		AgentWakePolicyComponent.from_template_data(
			{
				"active_interrupt_preset_id": "focused",
				"interrupt_presets": {
					"focused": {"NoActiveTask": {"enabled": False}},
					"balanced": {"NoActiveTask": {"enabled": True}},
				},
				"interrupt_preset_descriptions": {
					"focused": "Focus on current work.",
					"balanced": "Normal responsiveness.",
				},
				"rules": [{"type": "NoActiveTask", "priority": 999}],
			}
		),
	)
	return ent


def _low_nutrition_agent() -> Entity:
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ent.add_component("AgentControlComponent", AgentControlComponent())
	ent.add_component("CreatureComponent", CreatureComponent(max_nutrition=100, current_nutrition=40))
	ent.add_component(
		"AgentWakePolicyComponent",
		AgentWakePolicyComponent.from_template_data(
			{
				"active_interrupt_preset_id": "balanced",
				"interrupt_presets": {
					"balanced": {
						"LowNutrition": {
							"enabled": True,
							"threshold_on": 0.5,
							"threshold_off": 0.6,
							"cooldown_ticks": 0,
						}
					}
				},
				"rules": [{"type": "LowNutrition", "priority": 10, "threshold": 30}],
			}
		),
	)
	return ent


class InterruptPresetTests(unittest.TestCase):
	def test_no_active_task_rule_is_not_controlled_by_preset(self) -> None:
		ws = WorldState()
		agent = _agent()
		ws.register_entity(agent)
		wake_policy = agent.get_component("AgentWakePolicyComponent")

		result = check_if_interrupt_is_needed(ws, "agent_01", wake_policy)
		self.assertTrue(result.interrupt)
		self.assertEqual(result.rule_type, "NoActiveTask")

		wake_policy.active_interrupt_preset_id = "balanced"
		result = check_if_interrupt_is_needed(ws, "agent_01", wake_policy)
		self.assertTrue(result.interrupt)
		self.assertEqual(result.rule_type, "NoActiveTask")

	def test_low_nutrition_threshold_on_comes_from_active_preset(self) -> None:
		ws = WorldState()
		agent = _low_nutrition_agent()
		ws.register_entity(agent)
		wake_policy = agent.get_component("AgentWakePolicyComponent")

		result = check_if_interrupt_is_needed(ws, "agent_01", wake_policy)

		self.assertTrue(result.interrupt)
		self.assertEqual(result.rule_type, "LowNutrition")
		self.assertEqual(result.data["threshold"], 50.0)


if __name__ == "__main__":
	unittest.main()
