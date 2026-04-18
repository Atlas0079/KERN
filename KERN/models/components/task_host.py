from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..task import Task


@dataclass
class TaskHostComponent:
	"""
	Responsibility: Holds task list and provides "claimable task" query.
	"""

	# task_id -> Task
	tasks: dict[str, Task] = field(default_factory=dict)

	def per_tick(self, _ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		# Host does not progress tasks, progression is handled by Worker/Manager.
		return

	def add_task(self, task: Task) -> None:
		if task.task_id in self.tasks:
			raise ValueError(f"task already exists on host: {task.task_id}")
		self.tasks[task.task_id] = task

	def remove_task(self, task_id: str) -> None:
		self.tasks.pop(task_id, None)

	def get_task(self, task_id: str) -> Task | None:
		return self.tasks.get(task_id)

	def get_all_tasks(self) -> list[Task]:
		return list(self.tasks.values())

	def get_available_tasks(self) -> list[Task]:
		available: list[Task] = []
		for t in self.tasks.values():
			if not t.assigned_agent_ids:
				available.append(t)
		return available
