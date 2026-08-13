from __future__ import annotations

import unittest

from tools.checkpoint_viewer_server import ArchiveViewerData, MISSING_TIME_PLACEHOLDER


class CheckpointViewerServerTests(unittest.TestCase):
	def test_time_str_from_world_prefers_stored_time(self) -> None:
		viewer = ArchiveViewerData.__new__(ArchiveViewerData)

		self.assertEqual(
			viewer._time_str_from_world({"world_state": {"time_str": "2026-06-19 09:30", "current_tick": 1}}),
			"2026-06-19 09:30",
		)

	def test_time_str_from_world_uses_placeholder_without_stored_time(self) -> None:
		viewer = ArchiveViewerData.__new__(ArchiveViewerData)

		self.assertEqual(
			viewer._time_str_from_world({"world_state": {"current_tick": 60, "tick0_datetime": "2026-06-19T09:00"}}),
			MISSING_TIME_PLACEHOLDER,
		)


if __name__ == "__main__":
	unittest.main()
