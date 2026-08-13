from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ..agent_workflow.contracts import ActionFeedback, EndTurn, SubmitAction, TurnFrame, TurnStart
from ..agent_workflow.interrupt_runtime import check_if_interrupt_is_needed
from ..agent_workflow.provider_routing import resolve_workflow_provider
from ..agent_workflow.trace import LLMTraceRecorder
from ..execution_errors import KernFailure
from ..interaction.action_resolver import resolve_action_intent
from ..models.components import AgentWakePolicyComponent, resolve_enabled_controller_component
from .turn_runner import TurnContext, TurnRunner
from .turn_scheduler import TurnScheduler


@dataclass
class _BatchTurn:
	context: TurnContext
	session: Any
	reason: str
	mode: str
	feedback: ActionFeedback | None = None
	ended: bool = False


class SerialActivePhaseStrategy:
	def __init__(
		self,
		*,
		max_actions_per_turn: int,
		max_replans_per_turn: int,
		trace_recorder: LLMTraceRecorder | None = None,
	) -> None:
		self.scheduler = TurnScheduler(
			max_actions_per_turn=max_actions_per_turn,
			max_replans_per_turn=max_replans_per_turn,
			trace_recorder=trace_recorder,
		)

	def run_active_phase(self, ws: Any, settlement: Any) -> None:
		self.scheduler.run_active_phase(ws, settlement)


class ParallelBatchActivePhaseStrategy:
	"""Advance eligible turn sessions in parallel decision rounds; commit serially."""

	def __init__(
		self,
		*,
		max_actions_per_turn: int,
		max_replans_per_turn: int,
		trace_recorder: LLMTraceRecorder | None = None,
		max_workers: int = 4,
	) -> None:
		self.max_actions_per_turn = max(1, int(max_actions_per_turn))
		self.max_replans_per_turn = max(0, int(max_replans_per_turn))
		self.trace_recorder = trace_recorder
		self.max_workers = max(1, int(max_workers))

	def run_active_phase(self, ws: Any, settlement: Any) -> None:
		turns = self._begin_turns(ws)
		if not turns:
			return
		while turns:
			if self._abort_requested(ws):
				return
			live_turns = [
				turn
				for turn in turns
				if (
					not turn.ended
					and turn.context.actions_committed < self.max_actions_per_turn
					and self._is_turn_eligible(ws, turn.context.actor_id)
				)
			]
			if not live_turns:
				return
			steps = self._next_steps(ws, live_turns)
			for turn, step in steps:
				if self._abort_requested(ws) or not self._is_turn_eligible(ws, turn.context.actor_id):
					turn.ended = True
					continue
				if isinstance(step, EndTurn):
					turn.ended = True
					continue
				if not isinstance(step, SubmitAction):
					raise KernFailure(
						"WORKFLOW_SESSION_INVALID_STEP",
						"AgentTurnSession.next_step must return SubmitAction or EndTurn",
						origin="workflow",
						phase="turn_execution",
						context={"actor_id": turn.context.actor_id, "turn_id": turn.context.turn_id},
					)
				self._commit_step(ws, settlement, turn, step)
				if turn.context.actions_committed >= self.max_actions_per_turn:
					turn.ended = True
			turns = [turn for turn in turns if not turn.ended]

	def _begin_turns(self, ws: Any) -> list[_BatchTurn]:
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		out: list[_BatchTurn] = []
		for turn_index, actor_id in enumerate(self._candidate_ids(ws)):
			if self._abort_requested(ws):
				break
			if not self._is_turn_eligible(ws, actor_id):
				continue
			entity = ws.get_entity_by_id(actor_id)
			wake_policy = entity.get_component("AgentWakePolicyComponent") if entity is not None else None
			if not isinstance(wake_policy, AgentWakePolicyComponent):
				raise KernFailure(
					"AGENT_WAKE_POLICY_MISSING",
					"controlled entity has no AgentWakePolicyComponent",
					origin="scheduler",
					phase="turn_assessment",
					context={"actor_id": actor_id, "turn_id": f"tick:{tick}:turn:{turn_index}"},
				)
			assessment = check_if_interrupt_is_needed(ws=ws, agent_id=actor_id, wake_policy=wake_policy)
			if not bool(getattr(assessment, "interrupt", False)):
				continue
			controller = self._controller(entity)
			provider = resolve_workflow_provider(getattr(ws, "services", {}) or {}, controller)
			if provider is None:
				raise KernFailure(
					"WORKFLOW_PROVIDER_MISSING",
					f"No workflow provider for controlled entity: {actor_id}",
					origin="workflow",
					phase="decision",
					context={"actor_id": actor_id, "turn_id": f"tick:{tick}:turn:{turn_index}"},
				)
			context = TurnContext(
				turn_id=f"tick:{tick}:turn:{turn_index}",
				tick=tick,
				turn_index=turn_index,
				actor_id=actor_id,
			)
			start = TurnStart(
				turn_id=context.turn_id,
				tick=context.tick,
				turn_index=context.turn_index,
				actor_id=context.actor_id,
				wake_reason=str(getattr(assessment, "reason", "") or ""),
				mode="task_interrupt" if TurnRunner._current_task_id(ws, actor_id) else "normal",
			)
			try:
				session = provider.begin_turn(ws, start)
			except KernFailure:
				raise
			except Exception as exc:
				raise KernFailure(
					"WORKFLOW_PROVIDER_EXCEPTION",
					str(exc),
					origin="workflow",
					phase="turn_start",
					context={"actor_id": actor_id, "turn_id": context.turn_id},
				) from exc
			if session is None or not callable(getattr(session, "next_step", None)):
				raise KernFailure(
					"WORKFLOW_SESSION_INVALID",
					"workflow.begin_turn must return an AgentTurnSession",
					origin="workflow",
					phase="turn_start",
					context={"actor_id": actor_id, "turn_id": context.turn_id},
				)
			out.append(
				_BatchTurn(
					context=context,
					session=session,
					reason=str(getattr(assessment, "reason", "") or ""),
					mode="task_interrupt" if TurnRunner._current_task_id(ws, actor_id) else "normal",
				)
			)
		return out

	def _next_steps(self, ws: Any, turns: list[_BatchTurn]) -> list[tuple[_BatchTurn, Any]]:
		prepared_by_index: dict[int, Any] = {}
		out_by_index: dict[int, tuple[_BatchTurn, Any]] = {}
		for index, turn in enumerate(turns):
			frame = self._frame_for(turn)
			prepare = getattr(turn.session, "prepare_parallel_next_step", None)
			if callable(prepare):
				try:
					prepared = prepare(ws, frame)
				except KernFailure:
					raise
				except Exception as exc:
					raise self._workflow_exception(turn, exc, phase="decision") from exc
				if prepared is not None:
					if isinstance(prepared, (SubmitAction, EndTurn)):
						out_by_index[index] = (turn, prepared)
					else:
						prepared_by_index[index] = prepared
					continue
			out_by_index[index] = (turn, self._next_step_with_frame(ws, turn, frame))
		if prepared_by_index:
			with ThreadPoolExecutor(max_workers=min(self.max_workers, len(prepared_by_index))) as pool:
				future_by_index = {}
				for index, prepared in prepared_by_index.items():
					run = getattr(prepared, "run", None)
					if not callable(run):
						raise self._workflow_exception(turns[index], TypeError("parallel prepared step must expose run()"), phase="decision")
					future_by_index[index] = pool.submit(run)
				for index, future in future_by_index.items():
					turn = turns[index]
					try:
						result = future.result()
					except KernFailure:
						raise
					except Exception as exc:
						raise self._workflow_exception(turn, exc, phase="decision") from exc
					complete = getattr(prepared_by_index[index], "complete", None)
					if not callable(complete):
						raise self._workflow_exception(turn, TypeError("parallel prepared step must expose complete()"), phase="decision")
					try:
						out_by_index[index] = (turn, complete(result))
					except KernFailure:
						raise
					except Exception as exc:
						raise self._workflow_exception(turn, exc, phase="decision") from exc
		return [out_by_index[index] for index in range(len(turns))]

	def _frame_for(self, turn: _BatchTurn) -> TurnFrame:
		return TurnFrame(
			actor_id=turn.context.actor_id,
			reason=str(turn.reason or ""),
			mode_context=self._mode_context(turn),
			previous_action=turn.feedback,
			actions_committed=turn.context.actions_committed,
			replans=turn.context.replans,
		)

	def _next_step_with_frame(self, ws: Any, turn: _BatchTurn, frame: TurnFrame) -> Any:
		try:
			return turn.session.next_step(ws, frame)
		except KernFailure:
			raise
		except Exception as exc:
			raise KernFailure(
				"WORKFLOW_PROVIDER_EXCEPTION",
				str(exc),
				origin="workflow",
				phase="decision",
				context={"actor_id": turn.context.actor_id, "turn_id": turn.context.turn_id},
			) from exc

	@staticmethod
	def _workflow_exception(turn: _BatchTurn, exc: Exception, *, phase: str) -> KernFailure:
		return KernFailure(
			"WORKFLOW_PROVIDER_EXCEPTION",
			str(exc),
			origin="workflow",
			phase=phase,
			context={"actor_id": turn.context.actor_id, "turn_id": turn.context.turn_id},
		)

	def _commit_step(self, ws: Any, settlement: Any, turn: _BatchTurn, step: SubmitAction) -> None:
		if turn.context.actions_committed >= self.max_actions_per_turn:
			turn.ended = True
			return
		action = dict(step.intent)
		trace_id = str(step.meta.get("llm_trace_id", "") or "").strip()
		action_id = f"tick:{turn.context.tick}:turn:{turn.context.turn_index}:attempt:{turn.context.attempts}"
		turn.context.attempts += 1
		before_task_id = TurnRunner._current_task_id(ws, turn.context.actor_id)
		resolved = resolve_action_intent(ws, turn.context.actor_id, str(turn.reason or ""), action)
		status = str(resolved.get("status", "") or "")
		if status == "rejected":
			rejection = dict(resolved.get("rejection", {}) or {})
			TurnRunner._commit_rejection(settlement, turn.context, action_id, action, rejection)
			turn.context.replans += 1
			turn.feedback = ActionFeedback(
				action_id=action_id,
				intent=action,
				status="rejected",
				rejection_code=str(rejection.get("code", "ACTION_REJECTED") or "ACTION_REJECTED"),
				message=str(rejection.get("message", "action rejected") or "action rejected"),
			)
			self._record_action_trace(trace_id, turn.feedback)
			if turn.context.replans > self.max_replans_per_turn:
				raise KernFailure(
					"TURN_REPLAN_BUDGET_EXCEEDED",
					"action rejection replan budget exceeded",
					origin="scheduler",
					phase="turn_execution",
					context={
						"actor_id": turn.context.actor_id,
						"turn_id": turn.context.turn_id,
						"max_replans_per_turn": self.max_replans_per_turn,
						"rejection": TurnRunner._rejection_context(turn.feedback),
					},
				)
			return
		if status != "ready":
			raise KernFailure(
				"ACTION_RESOLUTION_INVALID",
				"action resolver returned an invalid status",
				origin="interaction",
				phase="action_resolution",
			)
		context = dict(resolved["context"])
		context.update({"action_id": action_id, "turn_id": turn.context.turn_id})
		settlement.execute_bundle(dict(resolved["bundle"]), context)
		turn.context.actions_committed += 1
		turn.feedback = ActionFeedback(action_id=action_id, intent=action, status="committed")
		self._record_action_trace(trace_id, turn.feedback)
		if self._abort_requested(ws):
			turn.ended = True
			return
		after_task_id = TurnRunner._current_task_id(ws, turn.context.actor_id)
		if not before_task_id and after_task_id:
			turn.ended = True
			return
		turn.mode = "task_interrupt" if after_task_id else "normal"

	def _record_action_trace(self, trace_id: str, feedback: ActionFeedback) -> None:
		if self.trace_recorder is None or not trace_id:
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
	def _mode_context(turn: _BatchTurn) -> dict[str, Any]:
		return {
			"turn_id": turn.context.turn_id,
			"turn_mode": turn.mode,
			"interrupt_decision_mode": turn.mode == "task_interrupt",
			"interrupt_reason": str(turn.reason or ""),
			"rejection": TurnRunner._rejection_context(turn.feedback),
		}

	@staticmethod
	def _candidate_ids(ws: Any) -> list[str]:
		return sorted(
			str(entity_id)
			for entity_id, entity in dict(getattr(ws, "entities", {}) or {}).items()
			if ParallelBatchActivePhaseStrategy._controller(entity) is not None
		)

	@staticmethod
	def _controller(entity: Any) -> Any | None:
		_name, component = resolve_enabled_controller_component(entity)
		return component

	@staticmethod
	def _abort_requested(ws: Any) -> bool:
		return bool(getattr(getattr(ws, "runtime_state", None), "abort_requested", False))

	@classmethod
	def _is_turn_eligible(cls, ws: Any, actor_id: str) -> bool:
		entity = ws.get_entity_by_id(actor_id) if hasattr(ws, "get_entity_by_id") else None
		return entity is not None and cls._controller(entity) is not None


def build_active_phase_strategy(
	mode: str,
	*,
	max_actions_per_turn: int,
	max_replans_per_turn: int,
	trace_recorder: LLMTraceRecorder | None = None,
	parallel_workers: int = 4,
) -> Any:
	clean = str(mode or "serial").strip().lower()
	if clean in {"", "serial"}:
		return SerialActivePhaseStrategy(
			max_actions_per_turn=max_actions_per_turn,
			max_replans_per_turn=max_replans_per_turn,
			trace_recorder=trace_recorder,
		)
	if clean == "parallel_batch":
		return ParallelBatchActivePhaseStrategy(
			max_actions_per_turn=max_actions_per_turn,
			max_replans_per_turn=max_replans_per_turn,
			trace_recorder=trace_recorder,
			max_workers=parallel_workers,
		)
	raise ValueError(f"unsupported ACTIVE_PHASE_MODE: {mode}")


__all__ = [
	"ParallelBatchActivePhaseStrategy",
	"SerialActivePhaseStrategy",
	"build_active_phase_strategy",
]
