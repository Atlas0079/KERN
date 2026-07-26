from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..execution_errors import KernFailure


@dataclass(frozen=True)
class DialogueFrame:
	conversation_id: str
	tick: int
	location_id: str
	initiator_id: str
	speaker_id: str
	participants: tuple[str, ...]
	transcript: tuple[dict[str, Any], ...]
	perception: dict[str, Any]
	utterance_index: int
	remaining_utterances: int


@dataclass(frozen=True)
class Speak:
	text: str


@dataclass(frozen=True)
class Pass:
	pass


DialogueStep = Speak | Pass


class DialoguePolicy(Protocol):
	def decide_utterance(self, frame: DialogueFrame) -> DialogueStep:
		...


class PassDialoguePolicy:
	def decide_utterance(self, _frame: DialogueFrame) -> DialogueStep:
		return Pass()


def as_dialogue_policy(provider: Any) -> DialoguePolicy:
	if provider is not None and callable(getattr(provider, "decide_utterance", None)):
		return provider
	raise KernFailure(
		"DIALOGUE_POLICY_MISSING",
		"workflow must implement DialoguePolicy.decide_utterance()",
		origin="workflow",
		phase="dialogue",
	)


__all__ = [
	"DialogueFrame",
	"DialoguePolicy",
	"DialogueStep",
	"Pass",
	"PassDialoguePolicy",
	"Speak",
	"as_dialogue_policy",
]
