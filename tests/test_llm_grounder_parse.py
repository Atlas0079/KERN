from __future__ import annotations

import unittest

from KERN.agent_workflow.llm_action_provider import LLMWorkflow


class LLMGrounderParseTests(unittest.TestCase):
	def test_accepts_action_object_array(self) -> None:
		workflow = LLMWorkflow(providers={}, roles={})

		actions = workflow._parse_actions('[{"verb":"OpenContainer","target_id":"camp_storage","parameters":{}}]')

		self.assertEqual(actions, [{"verb": "OpenContainer", "target_id": "camp_storage", "parameters": {}}])

	def test_rejects_tuple_style_action_array(self) -> None:
		workflow = LLMWorkflow(providers={}, roles={})

		with self.assertRaisesRegex(ValueError, r"action\[0\] must be an object"):
			workflow._parse_actions('["OpenContainer", {"target_id": "camp_storage"}]')

	def test_rejects_action_missing_parameters(self) -> None:
		workflow = LLMWorkflow(providers={}, roles={})

		with self.assertRaisesRegex(ValueError, r"parameters is required"):
			workflow._parse_actions('[{"verb":"OpenContainer","target_id":"camp_storage"}]')


if __name__ == "__main__":
	unittest.main()
