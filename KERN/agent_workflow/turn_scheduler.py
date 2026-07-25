from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..execution_errors import KernFailure
from ..models.components import DecisionArbiterComponent, resolve_enabled_controller_component
from .interrupt_runtime import check_if_interrupt_is_needed
from .provider_routing import resolve_workflow_provider
from .runtime import resolve_action_intent, run_workflow_cycle


@dataclass
class TurnContext:
	turn_id: str
	tick: int
	turn_index: int
	actor_id: str
	actions_committed: int = 0
	replans: int = 0
	attempts: int = 0


class TurnScheduler:
	"""Run the active phase of one tick through a single deterministic seam."""

	def __init__(self, *, max_actions_per_turn: int = 99, max_replans_per_turn: int = 5) -> None:
		self.max_actions_per_turn = max(1, int(max_actions_per_turn))
		self.max_replans_per_turn = max(0, int(max_replans_per_turn))

	def run_active_phase(self, ws: Any, settlement: Any) -> None:
		candidate_ids = sorted(
			str(entity_id)
			for entity_id, entity in dict(getattr(ws, "entities", {}) or {}).items()
			if self._controller(entity) is not None
		)
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		for turn_index, actor_id in enumerate(candidate_ids):
			if bool(getattr(getattr(ws, "runtime_state", None), "abort_requested", False)):
				return
			if not self._is_turn_eligible(ws, actor_id):
				continue
			self._run_turn(ws, settlement, TurnContext(
				turn_id=f"tick:{tick}:turn:{turn_index}",
				tick=tick,
				turn_index=turn_index,
				actor_id=actor_id,
			))

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

	@staticmethod
	def _current_task_id(ws: Any, actor_id: str) -> str:
		entity = ws.get_entity_by_id(actor_id) if hasattr(ws, "get_entity_by_id") else None
		worker = entity.get_component("WorkerComponent") if entity is not None and hasattr(entity, "get_component") else None
		return str(getattr(worker, "current_task_id", "") or "") if worker is not None else ""

	def _run_turn(self, ws: Any, settlement: Any, turn: TurnContext) -> None:
		entity = ws.get_entity_by_id(turn.actor_id)
		arbiter = entity.get_component("DecisionArbiterComponent") if entity is not None else None
		if not isinstance(arbiter, DecisionArbiterComponent):
			raise KernFailure(
				"DECISION_ARBITER_MISSING",
				"controlled entity has no DecisionArbiterComponent",
				origin="scheduler",
				phase="turn_assessment",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			)
		assessment = check_if_interrupt_is_needed(ws=ws, agent_id=turn.actor_id, arb=arbiter)
		if not bool(getattr(assessment, "interrupt", False)):
			return
		controller = self._controller(entity)
		workflow = resolve_workflow_provider(getattr(ws, "services", {}) or {}, controller)
		if workflow is None or not hasattr(workflow, "decide"):
			raise KernFailure(
				"WORKFLOW_PROVIDER_MISSING",
				f"No workflow provider for controlled entity: {turn.actor_id}",
				origin="workflow",
				phase="decision",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			)

		reason = str(getattr(assessment, "reason", "") or "")
		mode = "task_interrupt" if self._current_task_id(ws, turn.actor_id) else "normal"
		rejection_context: dict[str, Any] = {}
		while turn.actions_committed < self.max_actions_per_turn:
			if self._abort_requested(ws):
				return
			if not self._is_turn_eligible(ws, turn.actor_id):
				return
			mode_context = {
				"turn_id": turn.turn_id,
				"turn_mode": mode,
				"interrupt_decision_mode": mode == "task_interrupt",
				"interrupt_reason": reason,
				"rejection": dict(rejection_context),
			}
			decision = run_workflow_cycle(ws, turn.actor_id, workflow, reason, mode_context)
			decision_type = str(decision.get("type", "") or "")
			if decision_type == "end_turn":
				return
			if decision_type != "action_plan":
				raise KernFailure(
					"WORKFLOW_RUNTIME_INVALID_DECISION",
					f"unsupported workflow decision type: {decision_type}",
					origin="workflow",
					phase="turn_execution",
					context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
				)
			rejection_context = {}
			plan_rejected = False
			for action in list(decision.get("actions", []) or []):
				if self._abort_requested(ws):
					return
				if turn.actions_committed >= self.max_actions_per_turn:
					return
				action_id = f"tick:{turn.tick}:turn:{turn.turn_index}:attempt:{turn.attempts}"
				turn.attempts += 1
				before_task_id = self._current_task_id(ws, turn.actor_id)
				resolved = resolve_action_intent(ws, turn.actor_id, reason, dict(action))
				if str(resolved.get("status", "") or "") == "rejected":
					rejection_context = self._commit_rejection(
						settlement,
						turn,
						action_id,
						dict(action),
						dict(resolved.get("rejection", {}) or {}),
					)
					turn.replans += 1
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
								"rejection": rejection_context,
							},
						)
					plan_rejected = True
					break
				if str(resolved.get("status", "") or "") != "ready":
					raise KernFailure("ACTION_RESOLUTION_INVALID", "action resolver returned an invalid status", origin="interaction", phase="action_resolution")
				context = dict(resolved.get("context", {}) or {})
				context.update({"action_id": action_id, "turn_id": turn.turn_id})
				settlement.execute_bundle(dict(resolved.get("bundle", {}) or {}), context)
				turn.actions_committed += 1
				if self._abort_requested(ws):
					return
				if not self._is_turn_eligible(ws, turn.actor_id):
					return
				after_task_id = self._current_task_id(ws, turn.actor_id)
				if not before_task_id and after_task_id:
					return
				mode = "task_interrupt" if after_task_id else "normal"
			if plan_rejected:
				continue

	@staticmethod
	def _commit_rejection(
		settlement: Any,
		turn: TurnContext,
		action_id: str,
		action: dict[str, Any],
		rejection: dict[str, Any],
	) -> dict[str, Any]:
		code = str(rejection.get("code", "ACTION_REJECTED") or "ACTION_REJECTED")
		message = str(rejection.get("message", "action rejected") or "action rejected")
		narrative = str(rejection.get("narrative", "") or "")
		context = {
			"action_id": action_id,
			"action_intent": dict(action),
			"code": code,
			"message": message,
		}
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
		return context
