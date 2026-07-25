from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agent_workflow.dialogue import DialogueFrame, Pass, Speak, as_dialogue_policy
from ..agent_workflow.full_ws_view_builder import build_full_ws_view
from ..agent_workflow.observer import build_agent_perception
from ..agent_workflow.provider_routing import resolve_workflow_provider
from ..execution_errors import KernFailure
from ..models.components import resolve_enabled_controller_component


@dataclass(frozen=True)
class ConversationRequest:
	conversation_id: str
	initiator_id: str
	location_id: str
	opening_text: str
	max_utterances: int


@dataclass(frozen=True)
class ConversationUtterance:
	speaker_id: str
	text: str
	utterance_index: int

	def to_dict(self) -> dict[str, Any]:
		return {"speaker_id": self.speaker_id, "text": self.text, "utterance_index": int(self.utterance_index)}


@dataclass(frozen=True)
class ConversationResult:
	conversation_id: str
	location_id: str
	participants: tuple[str, ...]
	utterances: tuple[ConversationUtterance, ...] = field(default_factory=tuple)
	skipped_reason: str = ""


class ConversationEngine:
	"""Generate one bounded transcript without mutating WorldState."""

	def conduct(self, ws: Any, request: ConversationRequest) -> ConversationResult:
		location = ws.get_location_by_id(request.location_id) if hasattr(ws, "get_location_by_id") else None
		if location is None:
			return ConversationResult(request.conversation_id, request.location_id, (), skipped_reason="location_missing")
		participants = self._participants(ws, location, request.initiator_id)
		if request.initiator_id not in participants:
			return ConversationResult(request.conversation_id, request.location_id, participants, skipped_reason="initiator_ineligible")
		if len(participants) < 2:
			return ConversationResult(request.conversation_id, request.location_id, participants, skipped_reason="no_participants")
		limit = max(0, int(request.max_utterances))
		opening = str(request.opening_text or "").strip()
		if limit <= 0 or not opening:
			return ConversationResult(request.conversation_id, request.location_id, participants, skipped_reason="empty_budget")

		utterances: list[ConversationUtterance] = [ConversationUtterance(request.initiator_id, opening, 0)]
		services = getattr(ws, "services", {}) or {}
		for speaker_id in participants:
			if speaker_id == request.initiator_id or len(utterances) >= limit:
				continue
			entity = ws.get_entity_by_id(speaker_id)
			_name, controller = resolve_enabled_controller_component(entity)
			provider = resolve_workflow_provider(services, controller)
			policy = as_dialogue_policy(provider)
			frame = DialogueFrame(
				conversation_id=request.conversation_id,
				tick=int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0),
				location_id=request.location_id,
				initiator_id=request.initiator_id,
				speaker_id=speaker_id,
				participants=participants,
				transcript=tuple(item.to_dict() for item in utterances),
				perception=self._perception(ws, speaker_id, utterances),
				utterance_index=len(utterances),
				remaining_utterances=limit - len(utterances),
			)
			try:
				step = policy.decide_utterance(frame)
			except KernFailure:
				raise
			except Exception as exc:
				raise KernFailure(
					"DIALOGUE_POLICY_EXCEPTION",
					str(exc),
					origin="workflow",
					phase="dialogue",
					context={"speaker_id": speaker_id, "conversation_id": request.conversation_id},
				) from exc
			if isinstance(step, Pass):
				continue
			if not isinstance(step, Speak):
				raise KernFailure(
					"DIALOGUE_POLICY_INVALID_STEP",
					"DialoguePolicy.decide_utterance must return Speak or Pass",
					origin="workflow",
					phase="dialogue",
					context={"speaker_id": speaker_id, "conversation_id": request.conversation_id},
				)
			text = str(step.text or "").strip()
			if text:
				utterances.append(ConversationUtterance(speaker_id, text, len(utterances)))
		return ConversationResult(request.conversation_id, request.location_id, participants, tuple(utterances))

	@staticmethod
	def _participants(ws: Any, location: Any, initiator_id: str) -> tuple[str, ...]:
		eligible: list[str] = []
		for entity_id in sorted(str(item) for item in list(getattr(location, "entities_in_location", []) or [])):
			entity = ws.get_entity_by_id(entity_id) if hasattr(ws, "get_entity_by_id") else None
			_name, controller = resolve_enabled_controller_component(entity)
			if controller is not None:
				eligible.append(entity_id)
		initiator = str(initiator_id or "")
		if initiator not in eligible:
			return tuple(eligible)
		return tuple([initiator, *[item for item in eligible if item != initiator]])

	@staticmethod
	def _perception(ws: Any, speaker_id: str, transcript: list[ConversationUtterance]) -> dict[str, Any]:
		full_view = build_full_ws_view(ws, speaker_id, "", {})
		perception = build_agent_perception(full_view, speaker_id)
		perception["conversation_transcript"] = [item.to_dict() for item in transcript]
		return perception


__all__ = ["ConversationEngine", "ConversationRequest", "ConversationResult", "ConversationUtterance"]
