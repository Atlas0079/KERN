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


@dataclass
class LegacyDialoguePolicyAdapter:
	provider: Any

	def decide_utterance(self, frame: DialogueFrame) -> DialogueStep:
		context = {
			"conversation_id": frame.conversation_id,
			"location_id": frame.location_id,
			"participants": list(frame.participants),
			"utterance_index": int(frame.utterance_index),
			"max_utterances_per_tick": int(frame.utterance_index + frame.remaining_utterances),
			"transcript": [dict(item) for item in frame.transcript],
			"dialogue_phase": "join_decision",
			"initiator_id": frame.initiator_id,
		}
		try:
			raw = self.provider.decide_dialogue(
				perception=dict(frame.perception),
				conversation_context=context,
				self_id=frame.speaker_id,
			)
		except KernFailure:
			raise
		except Exception as exc:
			raise KernFailure(
				"DIALOGUE_POLICY_EXCEPTION",
				str(exc),
				origin="workflow",
				phase="dialogue",
				context={"speaker_id": frame.speaker_id, "conversation_id": frame.conversation_id},
			) from exc
		text = str(raw or "").strip()
		return Pass() if not text or text.upper() == "PASS" else Speak(text)


def as_dialogue_policy(provider: Any) -> DialoguePolicy:
	if provider is not None and callable(getattr(provider, "decide_utterance", None)):
		return provider
	if provider is not None and callable(getattr(provider, "decide_dialogue", None)):
		return LegacyDialoguePolicyAdapter(provider)
	return PassDialoguePolicy()


__all__ = [
	"DialogueFrame",
	"DialoguePolicy",
	"DialogueStep",
	"LegacyDialoguePolicyAdapter",
	"Pass",
	"PassDialoguePolicy",
	"Speak",
	"as_dialogue_policy",
]
