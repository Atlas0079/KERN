from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from tools.simulation_timeline import TimelineFilters, build_timeline, format_timeline_text


class SimulationTimelineTests(unittest.TestCase):
	def test_timeline_merges_trace_interaction_and_non_machine_events(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			run = Path(td)
			(run / "llm_traces" / "tick_000001" / "agent").mkdir(parents=True)
			(run / "simulation_log.json").write_text(
				json.dumps(
					{
						"meta": {"schema_version": "simlog.v1", "last_tick": 1},
						"log": [
							{"kind": "event", "seq": 1, "tick": 1, "actor_id": "", "event": {"type": "AdvanceTick", "payload": {"entity_id": "agent"}}},
							{
								"kind": "event",
								"seq": 2,
								"tick": 1,
								"actor_id": "agent",
								"event": {"type": "InteractionRecorded", "action_id": "tick:1:turn:0:attempt:0", "payload": {"interaction_id": "i1"}},
							},
							{
								"kind": "interaction",
								"seq": 1,
								"tick": 1,
								"actor_id": "agent",
								"action_id": "tick:1:turn:0:attempt:0",
								"verb": "Observe",
								"target_id": "target",
								"status": "success",
							},
						],
					},
					ensure_ascii=False,
				),
				encoding="utf-8",
			)
			trace_path = run / "llm_traces" / "tick_000001" / "agent" / "trace.json.gz"
			with gzip.open(trace_path, "wt", encoding="utf-8") as stream:
				json.dump(
					{
						"trace_id": "trace",
						"tick": 1,
						"actor_id": "agent",
						"context_type": "llm_decision",
						"status": "completed",
						"attempts": [{"planner": {"intent": "observe target"}}],
						"actions": [{"verb": "Observe", "target_id": "target", "parameters": {}}],
						"action_results": [{"action_id": "tick:1:turn:0:attempt:0", "status": "committed", "intent": {"verb": "Observe"}}],
					},
					stream,
				)
			(run / "llm_traces" / "index.jsonl").write_text(
				json.dumps(
					{"trace_id": "trace", "tick": 1, "actor_id": "agent", "context_type": "llm_decision", "path": "tick_000001/agent/trace.json.gz"},
					ensure_ascii=False,
				)
				+ "\n",
				encoding="utf-8",
			)

			items = build_timeline(run, TimelineFilters(agent_id="agent"))

			self.assertEqual([item["kind"] for item in items], ["trace", "event", "interaction"])
			self.assertEqual(items[0]["payload"]["planner_intent"], "observe target")
			self.assertNotIn("AdvanceTick", format_timeline_text(items))

	def test_machine_events_are_opt_in(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			run = Path(td)
			(run / "simulation_log.json").write_text(
				json.dumps({"log": [{"kind": "event", "seq": 1, "tick": 1, "event": {"type": "WorkerTick", "payload": {}}}]}),
				encoding="utf-8",
			)

			self.assertEqual(build_timeline(run), [])
			items = build_timeline(run, TimelineFilters(include_machine_events=True))
			self.assertEqual(items[0]["payload"]["type"], "WorkerTick")


if __name__ == "__main__":
	unittest.main()
