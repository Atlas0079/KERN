from __future__ import annotations

import unittest

from KERN.data.builder import build_world_state
from KERN.data.checkpoint import _world_dict_from_world_state
from KERN.models.gametime import GameTime


class GameTimeTests(unittest.TestCase):
	def test_tick0_datetime_anchors_calendar_time(self) -> None:
		gt = GameTime(total_ticks=60)
		gt.set_tick0_datetime("2026-06-19T09:00:00")

		self.assertEqual(gt.get_year(), 2026)
		self.assertEqual(gt.get_month(), 6)
		self.assertEqual(gt.get_day_of_month(), 19)
		self.assertEqual(gt.get_hour(), 10)
		self.assertEqual(gt.get_minute(), 0)
		self.assertEqual(gt.get_weekday(), 4)
		self.assertEqual(gt.get_day_tick(), 600)
		self.assertEqual(gt.time_to_string(), "2026-06-19 10:00")

	def test_datetime_uses_real_month_lengths_and_leap_years(self) -> None:
		gt = GameTime(total_ticks=2)
		gt.set_tick0_datetime("2024-02-28T23:59:00")

		self.assertEqual(gt.get_year(), 2024)
		self.assertEqual(gt.get_month(), 2)
		self.assertEqual(gt.get_day_of_month(), 29)
		self.assertEqual(gt.get_hour(), 0)
		self.assertEqual(gt.get_minute(), 1)

	def test_build_world_state_reads_tick0_datetime(self) -> None:
		world = {
			"world_state": {
				"current_tick": 30,
				"tick0_datetime": "2026-06-19T09:00:00",
			},
			"locations": [],
		}

		ws = build_world_state(world, {}, {}).world_state

		self.assertEqual(ws.game_time.time_to_string(), "2026-06-19 09:30")

	def test_checkpoint_serializes_tick0_datetime(self) -> None:
		world = {
			"world_state": {
				"current_tick": 30,
				"tick0_datetime": "2026-06-19T09:00:00",
			},
			"locations": [],
		}
		ws = build_world_state(world, {}, {}).world_state

		snapshot = _world_dict_from_world_state(ws)

		self.assertEqual(snapshot["world_state"]["current_tick"], 30)
		self.assertEqual(snapshot["world_state"]["tick0_datetime"], "2026-06-19T09:00")


if __name__ == "__main__":
	unittest.main()
