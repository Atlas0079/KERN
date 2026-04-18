from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any


@dataclass
class Task:
	"""
	Align with Godot `Task.gd` data structure (Resource -> Python dataclass).
	"""

	task_id: str = field(default_factory=lambda: f"task_{uuid4().hex}")
	task_type: str = ""
	action_type: str = "Action"  # Action, Task
	target_entity_id: str = ""

	progress: float = 0.0
	required_progress: float = 100.0

	multiple_entity: bool = False
	assigned_agent_ids: list[str] = field(default_factory=list)

	task_status: str = "Inactive"  # Inactive/InProgress/Paused/Completed/Cancelled/Failed
	parameters: dict[str, Any] = field(default_factory=dict)

	# --- Progressor configuration: Solidified into task by recipe ---
	progressor_id: str = ""
	progressor_params: dict[str, Any] = field(default_factory=dict)
	tick_effects: list[dict[str, Any]] = field(default_factory=list)

	# List of effects to execute upon task completion (Written at creation, read at completion)
	completion_effects: list[dict[str, Any]] = field(default_factory=list)

	def is_complete(self) -> bool:
		return float(self.progress) >= float(self.required_progress)

	def get_remaining_progress(self) -> float:
		return max(0.0, float(self.required_progress) - float(self.progress))
