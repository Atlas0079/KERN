from __future__ import annotations

from typing import Any

from ..agent_workflow.action_plan_adapter import as_agent_workflow
from ..agent_workflow.interrupt_runtime import check_if_interrupt_is_needed
from ..agent_workflow.provider_routing import resolve_workflow_provider
from ..execution_errors import KernFailure
from ..models.components import AgentWakePolicyComponent, resolve_enabled_controller_component
from ..agent_workflow.trace import LLMTraceRecorder
from .turn_runner import TurnContext, TurnRunner


class TurnScheduler:
	"""Grant deterministic active turns; action execution belongs to TurnRunner."""

	def __init__(
		self,
		*,
		max_actions_per_turn: int = 99,
		max_replans_per_turn: int = 5,
		trace_recorder: LLMTraceRecorder | None = None,
	) -> None:
		self.max_actions_per_turn = max(1, int(max_actions_per_turn))
		self.max_replans_per_turn = max(0, int(max_replans_per_turn))
		self.runner = TurnRunner(
			max_actions_per_turn=self.max_actions_per_turn,
			max_replans_per_turn=self.max_replans_per_turn,
			trace_recorder=trace_recorder,
		)

	def run_active_phase(self, ws: Any, settlement: Any) -> None:
		candidate_ids = sorted(
			str(entity_id)
			for entity_id, entity in dict(getattr(ws, "entities", {}) or {}).items()
			if self._controller(entity) is not None
		)
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		for turn_index, actor_id in enumerate(candidate_ids):
			if self._abort_requested(ws):
				return
			if not self._is_turn_eligible(ws, actor_id):
				continue
			self._grant_turn(
				ws,
				settlement,
				TurnContext(
					turn_id=f"tick:{tick}:turn:{turn_index}",
					tick=tick,
					turn_index=turn_index,
					actor_id=actor_id,
				),
			)

	def _grant_turn(self, ws: Any, settlement: Any, turn: TurnContext) -> None:
		entity = ws.get_entity_by_id(turn.actor_id)
		wake_policy = entity.get_component("AgentWakePolicyComponent") if entity is not None else None
		if not isinstance(wake_policy, AgentWakePolicyComponent):
			raise KernFailure(
				"AGENT_WAKE_POLICY_MISSING",
				"controlled entity has no AgentWakePolicyComponent",
				origin="scheduler",
				phase="turn_assessment",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			)
		assessment = check_if_interrupt_is_needed(ws=ws, agent_id=turn.actor_id, wake_policy=wake_policy)
		if not bool(getattr(assessment, "interrupt", False)):
			return
		controller = self._controller(entity)
		provider = resolve_workflow_provider(getattr(ws, "services", {}) or {}, controller)
		if provider is None:
			raise KernFailure(
				"WORKFLOW_PROVIDER_MISSING",
				f"No workflow provider for controlled entity: {turn.actor_id}",
				origin="workflow",
				phase="decision",
				context={"actor_id": turn.actor_id, "turn_id": turn.turn_id},
			)
		mode = "task_interrupt" if TurnRunner._current_task_id(ws, turn.actor_id) else "normal"
		self.runner.run(
			ws,
			settlement,
			turn,
			as_agent_workflow(provider),
			reason=str(getattr(assessment, "reason", "") or ""),
			mode=mode,
			is_turn_eligible=self._is_turn_eligible,
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


__all__ = ["TurnScheduler"]
