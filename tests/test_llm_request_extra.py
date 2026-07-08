from __future__ import annotations

import unittest
from typing import Any

from KERN.llm.openai_compat_client import DualModelLLM


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
	def test_dual_model_passes_request_extra_to_planner_and_grounder(self) -> None:
		client = CapturingChatClient()
		llm = DualModelLLM(
			client=client,
			planner_model="planner",
			grounder_model="grounder",
			request_extra={"thinking": {"type": "disabled"}},
		)

		self.assertEqual(llm.planner_text([{"role": "user", "content": "hi"}]), "ok")
		self.assertEqual(llm.grounder_text([{"role": "user", "content": "hi"}]), "ok")

		self.assertEqual(client.calls[0]["extra"], {"thinking": {"type": "disabled"}})
		self.assertEqual(client.calls[1]["extra"], {"thinking": {"type": "disabled"}})


if __name__ == "__main__":
	unittest.main()
