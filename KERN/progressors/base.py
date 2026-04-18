from __future__ import annotations

from typing import Protocol, Any


class Progressor(Protocol):
	"""
	Task Progressor Interface:
	- Input: world_state, agent_id, task, ticks
	- Output: progress delta added this tick (float)
	"""

	progressor_id: str

	def compute_progress_delta(self, ws: Any, agent_id: str, task: Any, ticks: int) -> float:
		...

