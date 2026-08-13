from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..agent_workflow.contracts import ActionFeedback, EndTurn, SubmitAction, TurnFrame, TurnStart
from ..execution_errors import KernFailure
from ..interaction.action_resolver import resolve_action_intent
from ..agent_workflow.trace import LLMTraceRecorder


@dataclass
class TurnContext:
	turn_id: str
	tick: int
	turn_index: int
	actor_id: str
	actions_committed: int = 0
	replans: int = 0
	attempts: int = 0


class TurnRunner:
	"""Drive one granted turn while KERN retains execution authority."""

	def __init__(
		self,
		*,
		max_actions_per_turn: int,
		max_replans_per_turn: int,
		trace_recorder: LLMTraceRecorder | None = None,
	) -> None:
		self.max_actions_per_turn = max(1, int(max_actions_per_turn))
		self.max_replans_per_turn = max(0, int(max_replans_per_turn))
		self.trace_recorder = trace_recorder

	def run(
		self,
		ws: Any,
		settlement: Any,
		turn: TurnContext,
		workflow: Any,
		*,
		reason: str,
		mode: str,
		is_turn_eligible: Callable[[Any, str], bool],
	) -> None:
		start = TurnStart(
			turn_id=turn.turn_id,
			tick=turn.tick,
			turn_index=turn.turn_index,
			actor_id=turn.actor_id,
			wake_reason=str(reason or ""),
			mode="task_interrupt" if mode == "task_interrupt" else "normal",
		)
		try:
			session = workflow.begin_turn(ws, start)
		except KernFailure:
			raise
		except Exception as exc:
			raise KernFailure(
				"WORKFLOW_PROVIDER_EXCEPTION",
				str(exc),
				origin="workflow",
				phase="turn_start",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			) from exc
		if session is None or not callable(getattr(session, "next_step", None)):
			raise KernFailure(
				"WORKFLOW_SESSION_INVALID",
				"workflow.begin_turn must return an AgentTurnSession",
				origin="workflow",
				phase="turn_start",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			)

		feedback: ActionFeedback | None = None
		while turn.actions_committed < self.max_actions_per_turn:
			if self._abort_requested(ws) or not is_turn_eligible(ws, turn.actor_id):
				return
			mode_context = {
				"turn_id": turn.turn_id,
				"turn_mode": mode,
				"interrupt_decision_mode": mode == "task_interrupt",
				"interrupt_reason": str(reason or ""),
				"rejection": self._rejection_context(feedback),
			}
			frame = TurnFrame(
				actor_id=turn.actor_id,
				reason=str(reason or ""),
				mode_context=mode_context,
				previous_action=feedback,
				actions_committed=turn.actions_committed,
				replans=turn.replans,
			)
			try:
				step = session.next_step(ws, frame)
			except KernFailure:
				raise
			except Exception as exc:
				raise KernFailure(
					"WORKFLOW_PROVIDER_EXCEPTION",
					str(exc),
					origin="workflow",
					phase="decision",
					context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
				) from exc
			if not isinstance(step, (SubmitAction, EndTurn)):
				raise KernFailure(
					"WORKFLOW_SESSION_INVALID_STEP",
					"AgentTurnSession.next_step must return SubmitAction or EndTurn",
					origin="workflow",
					phase="turn_execution",
					context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
				)
			if self._abort_requested(ws) or not is_turn_eligible(ws, turn.actor_id):
				return
			if isinstance(step, EndTurn):
				return

			action = dict(step.intent)
			trace_id = str(step.meta.get("llm_trace_id", "") or "").strip()
			action_id = f"tick:{turn.tick}:turn:{turn.turn_index}:attempt:{turn.attempts}"
			turn.attempts += 1
			before_task_id = self._current_task_id(ws, turn.actor_id)
			resolved = resolve_action_intent(ws, turn.actor_id, str(reason or ""), action)
			status = str(resolved.get("status", "") or "")
			if status == "rejected":
				rejection = dict(resolved.get("rejection", {}) or {})
				self._commit_rejection(settlement, turn, action_id, action, rejection)
				turn.replans += 1
				feedback = ActionFeedback(
					action_id=action_id,
					intent=action,
					status="rejected",
					rejection_code=str(rejection.get("code", "ACTION_REJECTED") or "ACTION_REJECTED"),
					message=str(rejection.get("message", "action rejected") or "action rejected"),
				)
				self._record_action_trace(trace_id, feedback)
				if self._abort_requested(ws):
					return
				if turn.replans > self.max_replans_per_turn:
					raise KernFailure(
						"TURN_REPLAN_BUDGET_EXCEEDED",
						"action rejection replan budget exceeded",
						origin="scheduler",
						phase="turn_execution",
						context={
							"actor_id": turn.actor_id,
							"turn_id": turn.turn_id,
							"max_replans_per_turn": self.max_replans_per_turn,
							"rejection": self._rejection_context(feedback),
						},
					)
				continue
			if status != "ready":
				raise KernFailure(
					"ACTION_RESOLUTION_INVALID",
					"action resolver returned an invalid status",
					origin="interaction",
					phase="action_resolution",
				)

			context = dict(resolved["context"])
			context.update({"action_id": action_id, "turn_id": turn.turn_id})
			settlement.execute_bundle(dict(resolved["bundle"]), context)
			turn.actions_committed += 1
			feedback = ActionFeedback(action_id=action_id, intent=action, status="committed")
			self._record_action_trace(trace_id, feedback)
			if self._abort_requested(ws) or not is_turn_eligible(ws, turn.actor_id):
				return
			after_task_id = self._current_task_id(ws, turn.actor_id)
			if not before_task_id and after_task_id:
				return
			mode = "task_interrupt" if after_task_id else "normal"

	@staticmethod
	def _abort_requested(ws: Any) -> bool:
		return bool(ws.runtime_state.abort_requested)

	def _record_action_trace(self, trace_id: str, feedback: ActionFeedback) -> None:
		if self.trace_recorder is None or not str(trace_id or "").strip():
			return
		self.trace_recorder.record_action_result(
			trace_id,
			action_id=feedback.action_id,
			intent=feedback.intent,
			status=feedback.status,
			rejection_code=feedback.rejection_code,
			message=feedback.message,
		)

	@staticmethod
	def _current_task_id(ws: Any, actor_id: str) -> str:
		entity = ws.get_entity_by_id(actor_id)
		worker = entity.get_component("WorkerComponent") if entity is not None else None
		return str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""

	@staticmethod
	def _rejection_context(feedback: ActionFeedback | None) -> dict[str, Any]:
		if feedback is None or feedback.status != "rejected":
			return {}
		return {
			"action_id": feedback.action_id,
			"action_intent": dict(feedback.intent),
			"code": feedback.rejection_code,
			"message": feedback.message,
		}

	@staticmethod
	def _commit_rejection(
		settlement: Any,
		turn: TurnContext,
		action_id: str,
		action: dict[str, Any],
		rejection: dict[str, Any],
	) -> None:
		code = str(rejection.get("code", "ACTION_REJECTED") or "ACTION_REJECTED")
		message = str(rejection.get("message", "action rejected") or "action rejected")
		narrative = str(rejection.get("narrative", "") or "")
		settlement.execute_bundle(
			{
				"effects": [
					{
						"effect": "RecordInteraction",
						"actor_id": turn.actor_id,
						"verb": str(action.get("verb", "") or ""),
						"target_id": str(action.get("target_id", "") or turn.actor_id),
						"status": "rejected",
						"reason": code,
						"interaction_origin": "action_rejection",
						"extra": {
							"narrative": narrative,
							"rejection_code": code,
							"message": message,
							"action_id": action_id,
							"action_intent": dict(action),
						},
					}
				]
			},
			{"self_id": turn.actor_id, "actor_id": turn.actor_id, "action_id": action_id, "turn_id": turn.turn_id},
		)


__all__ = ["TurnContext", "TurnRunner"]
