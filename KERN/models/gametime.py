from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


DEFAULT_TICK0_DATETIME = "0001-01-01T00:00:00"


def _parse_datetime(value: str) -> datetime:
	text = str(value or "").strip()
	if not text:
		text = DEFAULT_TICK0_DATETIME
	text = text.replace("Z", "+00:00")
	try:
		parsed = datetime.fromisoformat(text)
	except ValueError as exc:
		raise ValueError(f"invalid tick0_datetime: {value!r}") from exc
	if parsed.tzinfo is not None:
		parsed = parsed.replace(tzinfo=None)
	return parsed


@dataclass
class GameTime:
	"""
	Simulation time.

	`total_ticks` is the elapsed simulation time. `tick0_datetime` anchors tick 0
	to a real calendar date/time, so calendar fields are derived instead of
	hand-rolled.
	"""

	total_ticks: int = 0
	tick0_datetime: str = DEFAULT_TICK0_DATETIME

	# --- Constants (Consistent with GDScript version) ---
	TICKS_PER_MINUTE: int = 1
	MINUTES_PER_HOUR: int = 60
	HOURS_PER_DAY: int = 24
	DAYS_PER_WEEK: int = 7
	WEEKS_PER_MONTH: int = 4
	MONTHS_PER_YEAR: int = 12

	@property
	def ticks_per_hour(self) -> int:
		return self.TICKS_PER_MINUTE * self.MINUTES_PER_HOUR

	@property
	def ticks_per_day(self) -> int:
		return self.ticks_per_hour * self.HOURS_PER_DAY

	@property
	def tick0(self) -> datetime:
		return _parse_datetime(self.tick0_datetime)

	def current_datetime(self) -> datetime:
		minutes = int(self.total_ticks) / int(self.TICKS_PER_MINUTE or 1)
		return self.tick0 + timedelta(minutes=minutes)

	def set_tick0_datetime(self, value: str) -> None:
		parsed = _parse_datetime(value)
		self.tick0_datetime = parsed.isoformat(timespec="minutes")

	def advance_ticks(self, ticks_to_add: int) -> bool:
		old_day = self.current_datetime().date()
		self.total_ticks += int(ticks_to_add)
		new_day = self.current_datetime().date()
		return new_day > old_day

	def get_year(self) -> int:
		return self.current_datetime().year

	def get_month(self) -> int:
		return self.current_datetime().month

	def get_day_of_month(self) -> int:
		return self.current_datetime().day

	def get_weekday(self) -> int:
		"""Return Monday=0 ... Sunday=6, matching datetime.weekday()."""
		return self.current_datetime().weekday()

	def get_day_tick(self) -> int:
		current = self.current_datetime()
		return (current.hour * self.MINUTES_PER_HOUR + current.minute) * self.TICKS_PER_MINUTE

	def get_hour(self) -> int:
		return self.current_datetime().hour

	def get_minute(self) -> int:
		return self.current_datetime().minute

	def to_dict(self) -> dict[str, int | str]:
		current = self.current_datetime()
		return {
			"total_ticks": int(self.total_ticks),
			"tick0_datetime": self.tick0.isoformat(timespec="minutes"),
			"datetime": current.isoformat(timespec="minutes"),
			"year": current.year,
			"month": current.month,
			"day": current.day,
			"weekday": current.weekday(),
			"hour": current.hour,
			"minute": current.minute,
			"day_tick": self.get_day_tick(),
		}

	def time_to_string(self) -> str:
		return "%04d-%02d-%02d %02d:%02d" % (
			self.get_year(),
			self.get_month(),
			self.get_day_of_month(),
			self.get_hour(),
			self.get_minute(),
		)
