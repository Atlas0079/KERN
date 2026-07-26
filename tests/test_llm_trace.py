from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from KERN.agent_workflow.trace import LLMTraceRecorder
from KERN.runtime import KernRuntime


class _SuccessfulLLM:
	base_url = "https://example.test"
	api_prefix = "/v1"

	def chat_text(self, *, model: str, **_kwargs):
		if model == "planner":
			return "THOUGHT: observe\nINTENT: observe the organizer"
		if model == "grounder":
			return '[{"verb":"Observe","target_id":"camper_organizer","parameters":{}}]'
		return "PASS"


class LLMTraceTests(unittest.TestCase):
	def test_full_trace_is_filtered_persisted_and_extended_with_action_result(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			recorder = LLMTraceRecorder(
				mode="full",
				output_dir=Path(td),
				agent_ids=frozenset({"agent_a"}),
				ticks=frozenset({2}),
			)
			recorder.record({"trace_id": "ignored_agent", "actor_id": "agent_b", "tick": 2, "context_type": "llm_decision"})
			recorder.record({"trace_id": "ignored_tick", "actor_id": "agent_a", "tick": 3, "context_type": "llm_decision"})
			recorder.record(
				{
					"trace_id": "trace_1",
					"actor_id": "agent_a",
					"tick": 2,
					"context_type": "llm_decision",
					"attempts": [{"planner": {"request": {"messages": [{"role": "user", "content": "context"}]}, "response": "intent"}}],
				}
			)
			recorder.record_action_result(
				"trace_1",
				action_id="action_1",
				intent={"verb": "Observe", "parameters": {}},
				status="committed",
			)

			files = list(Path(td).rglob("*.json.gz"))
			self.assertEqual(len(files), 1)
			with gzip.open(files[0], "rt", encoding="utf-8") as stream:
				payload = json.load(stream)
			self.assertEqual(payload["trace_id"], "trace_1")
			self.assertEqual(payload["action_results"][0]["status"], "committed")
			index_rows = (Path(td) / "index.jsonl").read_text(encoding="utf-8").splitlines()
			self.assertEqual(len(index_rows), 1)

	def test_off_mode_does_not_write(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			recorder = LLMTraceRecorder(mode="off", output_dir=Path(td))
			recorder.record({"trace_id": "trace_1", "actor_id": "agent", "tick": 1})
			self.assertEqual(list(Path(td).iterdir()), [])

	def test_filtered_trace_does_not_publish_an_unresolvable_trace_id(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			recorder = LLMTraceRecorder(mode="full", output_dir=Path(td), agent_ids=frozenset({"other"}))
			self.assertEqual(recorder.record({"trace_id": "trace_1", "actor_id": "agent", "tick": 1}), "")

	def test_runtime_trace_captures_provider_context_and_committed_feedback(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = KernRuntime.from_config(
				Path(__file__).resolve().parents[1],
				"runtime_config.camping.package.smoke.json",
				validate=True,
				configure_logging=False,
				overrides={
					"USE_LLM": "1",
					"CHECKPOINT_EVERY_TICK": "0",
					"CHECKPOINT_DIR": td,
					"MAX_ACTIONS_PER_TURN": "1",
					"LLM_WORKFLOW_CONFIG_JSON": json.dumps(
						{
							"llm_providers": {
								"main": {
									"protocol": "openai_compat",
									"base_url": "https://example.test",
									"api_prefix": "/v1",
									"api_key": "test-key",
								}
							},
							"workflows": {
								"default": {
									"kind": "llm",
									"roles": {
										"planner": {"provider_id": "main", "model": "planner"},
										"grounder": {"provider_id": "main", "model": "grounder"},
										"dialogue": {"provider_id": "main", "model": "dialogue"},
									},
								}
							},
							"default_workflow_id": "default",
						}
					),
					"LLM_TRACE_MODE": "full",
					"LLM_TRACE_AGENT_IDS": "camper_organizer",
					"LLM_TRACE_TICKS": "1",
				},
			)
			runtime.action_provider.providers["main"] = _SuccessfulLLM()
			runtime.is_running = True

			runtime.step()

			files = list((Path(td) / "llm_traces").rglob("*.json.gz"))
			self.assertEqual(len(files), 1)
			with gzip.open(files[0], "rt", encoding="utf-8") as stream:
				payload = json.load(stream)
			self.assertEqual(payload["actor_id"], "camper_organizer")
			self.assertEqual(payload["actions"][0]["verb"], "Observe")
			self.assertEqual(payload["action_results"][0]["status"], "committed")
			self.assertGreaterEqual(payload["attempts"][0]["planner"]["duration_ms"], 0)
			self.assertGreaterEqual(payload["attempts"][0]["grounder"]["duration_ms"], 0)


if __name__ == "__main__":
	unittest.main()
