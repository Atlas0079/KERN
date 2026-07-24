from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionRejected:
	"""A valid action proposal that cannot be executed in the current world."""

	code: str
	message: str
	command_index: int = -1
	command: dict[str, Any] = field(default_factory=dict)
	details: dict[str, Any] = field(default_factory=dict)
	narrative: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"code": str(self.code or "ACTION_REJECTED"),
			"message": str(self.message or "action rejected"),
			"command_index": int(self.command_index),
			"command": dict(self.command or {}),
			"details": dict(self.details or {}),
			"narrative": str(self.narrative or ""),
		}
