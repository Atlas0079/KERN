from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from KERN.data.archive import (
	ArchiveRecorder,
	apply_state_delta,
	archive_state_from_world_state,
	build_state_delta,
	materialize_archive_state,
	state_hash,
)
from KERN.data.checkpoint import resolve_checkpoint_file, restore_world_state_from_checkpoint
from KERN.models.components import MemoryComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime


def _world() -> WorldState:
	ws = WorldState()
	loc = Location(location_id="camp", location_name="Camp", description="")
	ws.register_location(loc)
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ent.add_component("MemoryComponent", MemoryComponent())
	ws.register_entity(ent)
	loc.add_entity_id(ent.entity_id)
	return ws


class ArchiveTests(unittest.TestCase):
	def test_explicit_missing_restore_source_is_rejected(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			with self.assertRaisesRegex(FileNotFoundError, "restore file not found"):
				resolve_checkpoint_file(str(root / "missing.json.gz"), "")
			with self.assertRaisesRegex(FileNotFoundError, "restore directory has no snapshots"):
				resolve_checkpoint_file("", str(root))
			with self.assertRaisesRegex(ValueError, "only one"):
				resolve_checkpoint_file(str(root / "missing.json.gz"), str(root))

	def test_list_append_diff_round_trips(self) -> None:
		before = {"entities": {"agent_01": {"memory": [{"tick": 1, "text": "a"}]}}}
		after = {"entities": {"agent_01": {"memory": [{"tick": 1, "text": "a"}, {"tick": 2, "text": "b"}]}}}

		changes = build_state_delta(before, after)

		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0]["op"], "append")
		self.assertEqual(apply_state_delta(before, changes), after)

	def test_archive_materialize_matches_recorded_state(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws = _world()
			recorder = ArchiveRecorder(
				archive_dir=td,
				run_id="test_run",
				snapshot_interval_ticks=2,
				include_logs=False,
			)

			recorder.record_tick(ws)
			mem = ws.get_entity_by_id("agent_01").get_component("MemoryComponent")
			self.assertIsInstance(mem, MemoryComponent)
			mem.add_entry("first", tick=1)
			ws.game_time.total_ticks = 1
			recorder.record_tick(ws)

			expected_state = archive_state_from_world_state(ws)
			materialized = materialize_archive_state(Path(td), 1)

			self.assertEqual(state_hash(materialized), state_hash(expected_state))
			self.assertEqual(materialized, expected_state)

	def test_restore_latest_archive_snapshot_from_directory(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws = _world()
			ws.record_event({"type": "Probe"}, {"self_id": "agent_01"})
			recorder = ArchiveRecorder(
				archive_dir=td,
				run_id="test_run",
				snapshot_interval_ticks=1,
				include_logs=True,
			)
			recorder.record_tick(ws)

			path = resolve_checkpoint_file("", td)
			self.assertIsNotNone(path)
			restored = restore_world_state_from_checkpoint(
				path,
				{"Agent": {"name": "Agent", "components": {"MemoryComponent": {}}}},
			)

			self.assertEqual(restored.game_time.total_ticks, 0)
			self.assertGreaterEqual(restored._event_seq, 1)
			self.assertEqual(len(restored.entities), 1)

	def test_runtime_rejects_restore_output_that_would_overwrite_the_source_archive(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		with tempfile.TemporaryDirectory() as td:
			base_runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.camping.package.smoke.json",
				validate=False,
				configure_logging=False,
				overrides={"CHECKPOINT_EVERY_TICK": "0"},
			)
			recorder = ArchiveRecorder(archive_dir=td, run_id="restore_run", snapshot_interval_ticks=1, include_logs=True)
			recorder.record_tick(base_runtime.world_state)
			snapshot = next((Path(td) / "snapshots").glob("snapshot_*.json.gz"))

			with self.assertRaisesRegex(ValueError, "CHECKPOINT_DIR must differ"):
				KernRuntime.from_config(
					project_root,
					"runtime_config.camping.package.smoke.json",
					validate=False,
					configure_logging=False,
					overrides={
						"CHECKPOINT_RESTORE_DIR": td,
						"CHECKPOINT_DIR": td,
						"CHECKPOINT_EVERY_TICK": "1",
					},
				)

			self.assertTrue(snapshot.exists())
			self.assertTrue((Path(td) / "manifest.json").exists())


if __name__ == "__main__":
	unittest.main()
