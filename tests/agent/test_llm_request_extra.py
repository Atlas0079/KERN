from __future__ import annotations

import unittest
from typing import Any

from KERN.agent_workflow.dialogue import DialogueFrame, Speak
from KERN.agent_workflow.llm_action_provider import build_llm_workflow


class CapturingChatClient:
	def __init__(self) -> None:
		self.calls: list[dict[str, Any]] = []

	def chat_text(
		self,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> str:
		self.calls.append(
			{
				"messages": messages,
				"model": model,
				"temperature": temperature,
				"max_tokens": max_tokens,
				"response_format": response_format,
				"extra": dict(extra or {}),
			}
		)
		return "ok"


class LLMRequestExtraTests(unittest.TestCase):
	def test_workflow_role_passes_request_extra_to_chat_provider(self) -> None:
		client = CapturingChatClient()
		workflow = build_llm_workflow(
			client=client,
			planner_model="planner",
			grounder_model="grounder",
		)
		workflow.roles["planner"]["request_extra"] = {"thinking": {"type": "disabled"}}
		workflow.roles["grounder"]["request_extra"] = {"seed": 1}

		self.assertEqual(workflow._ask("planner", messages=[{"role": "user", "content": "hi"}]), "ok")
		self.assertEqual(workflow._ask("grounder", messages=[{"role": "user", "content": "hi"}]), "ok")

		self.assertEqual(client.calls[0]["extra"], {"thinking": {"type": "disabled"}})
		self.assertEqual(client.calls[1]["extra"], {"seed": 1})

	def test_dialogue_uses_dialogue_role_model(self) -> None:
		client = CapturingChatClient()
		workflow = build_llm_workflow(
			client=client,
			planner_model="planner",
			grounder_model="grounder",
			dialogue_model="dialogue",
		)
		frame = DialogueFrame(
			conversation_id="conversation",
			tick=1,
			location_id="room",
			initiator_id="agent_a",
			speaker_id="agent_b",
			participants=("agent_a", "agent_b"),
			transcript=({"speaker_id": "agent_a", "text": "hi", "utterance_index": 0},),
			perception={"tick": 1, "location": {"id": "room", "name": "Room"}},
			utterance_index=1,
			remaining_utterances=1,
		)

		step = workflow.decide_utterance(frame)

		self.assertIsInstance(step, Speak)
		self.assertEqual(client.calls[0]["model"], "dialogue")


if __name__ == "__main__":
	unittest.main()
