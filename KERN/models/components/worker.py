from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerComponent:
	"""
	Align with core field shape of Godot `WorkerComponent.gd`:
	- current_task_id: Currently progressing task (occupies action rights)
	"""

	current_task_id: str = ""

	def has_task(self) -> bool:
		return bool(self.current_task_id)

	def assign_task(self, task_id: str) -> None:
		self.current_task_id = str(task_id or "")

	def stop_task(self) -> None:
		self.current_task_id = ""

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		return
