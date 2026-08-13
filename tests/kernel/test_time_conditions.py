from __future__ import annotations

import unittest

from KERN.models.world_state import WorldState
from KERN.query import evaluate_predicate, resolve_value


def _world_at(tick: int, tick0: str = "2026-06-19T09:00:00") -> WorldState:
	ws = WorldState()
	ws.game_time.total_ticks = int(tick)
	ws.game_time.set_tick0_datetime(tick0)
	return ws


class TimeConditionTests(unittest.TestCase):
	def test_resolve_time_fields_from_game_time(self) -> None:
		ws = _world_at(30)

		self.assertEqual(resolve_value(ws, "time.hour", {}), 9)
		self.assertEqual(resolve_value(ws, "time.minute", {}), 30)
		self.assertEqual(resolve_value(ws, "time.day_tick", {}), 570)
		self.assertEqual(resolve_value(ws, "time.weekday", {}), 4)
		self.assertEqual(resolve_value(ws, "time.date", {}), "2026-06-19")

	def test_time_match_eq_only_matches_exact_minute(self) -> None:
		predicate = {
			"type": "time_match",
			"weekday": ["fri"],
			"time": "09:30",
			"op": "==",
		}

		self.assertFalse(evaluate_predicate(_world_at(29), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(30), predicate, {}))
		self.assertFalse(evaluate_predicate(_world_at(31), predicate, {}))

	def test_time_match_gte_stays_true_after_target_time(self) -> None:
		predicate = {
			"type": "time_match",
			"weekday": ["fri"],
			"hour": 9,
			"minute": 30,
			"op": ">=",
		}

		self.assertFalse(evaluate_predicate(_world_at(29), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(30), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(90), predicate, {}))

	def test_time_match_weekday_filters(self) -> None:
		predicate = {
			"type": "time_match",
			"weekday": ["mon", "tue", "wed", "thu"],
			"time": "09:30",
			"op": "==",
		}

		self.assertFalse(evaluate_predicate(_world_at(30), predicate, {}))

	def test_time_between_default_includes_start_excludes_end(self) -> None:
		predicate = {
			"type": "time_between",
			"weekday": ["fri"],
			"start": "09:30",
			"end": "10:20",
		}

		self.assertFalse(evaluate_predicate(_world_at(29), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(30), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(79), predicate, {}))
		self.assertFalse(evaluate_predicate(_world_at(80), predicate, {}))

	def test_time_every_uses_offset(self) -> None:
		predicate = {
			"type": "time_every",
			"weekday": ["fri"],
			"minutes": 15,
			"offset": "09:30",
		}

		self.assertFalse(evaluate_predicate(_world_at(29), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(30), predicate, {}))
		self.assertFalse(evaluate_predicate(_world_at(44), predicate, {}))
		self.assertTrue(evaluate_predicate(_world_at(45), predicate, {}))

	def test_time_between_supports_overnight_windows(self) -> None:
		ws = _world_at(23 * 60 + 30, tick0="2026-06-19T00:00:00")
		predicate = {
			"type": "time_between",
			"weekday": ["fri"],
			"start": "22:00",
			"end": "06:00",
		}

		self.assertTrue(evaluate_predicate(ws, predicate, {}))


if __name__ == "__main__":
	unittest.main()
