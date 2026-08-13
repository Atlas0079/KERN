from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class TurnStart:
	turn_id: str
	tick: int
	turn_index: int
	actor_id: str
	wake_reason: str
	mode: Literal["normal", "task_interrupt"]


@dataclass(frozen=True)
class ActionFeedback:
	action_id: str
	intent: dict[str, Any]
	status: Literal["committed", "rejected"]
	rejection_code: str = ""
	message: str = ""


@dataclass(frozen=True)
class TurnFrame:
	actor_id: str
	reason: str
	mode_context: dict[str, Any]
	previous_action: ActionFeedback | None = None
	actions_committed: int = 0
	replans: int = 0


@dataclass(frozen=True)
class SubmitAction:
	intent: dict[str, Any]
	meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EndTurn:
	meta: dict[str, Any] = field(default_factory=dict)


WorkflowStep = SubmitAction | EndTurn


class AgentTurnSession(Protocol):
	def next_step(self, ws: Any, frame: TurnFrame) -> WorkflowStep:
		...


class AgentWorkflow(Protocol):
	def begin_turn(self, ws: Any, start: TurnStart) -> AgentTurnSession:
		...


__all__ = [
	"ActionFeedback",
	"AgentTurnSession",
	"AgentWorkflow",
	"EndTurn",
	"SubmitAction",
	"TurnFrame",
	"TurnStart",
	"WorkflowStep",
]
