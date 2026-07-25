from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..execution_errors import KernFailure
from .contracts import AgentTurnSession, DecisionFrame, EndTurn, SubmitAction, TurnStart, WorkflowStep
from .workflow_contract import validate_workflow_decision


@dataclass
class ActionPlanWorkflowAdapter:
	"""Adapt the legacy action-plan provider contract to a turn-scoped workflow."""

	provider: Any

	def begin_turn(self, start: TurnStart) -> AgentTurnSession:
		return _ActionPlanTurnSession(provider=self.provider, start=start)


@dataclass
class _ActionPlanTurnSession:
	provider: Any
	start: TurnStart
	pending_actions: list[dict[str, Any]] = field(default_factory=list)

	def next_step(self, frame: DecisionFrame) -> WorkflowStep:
		feedback = frame.previous_action
		if feedback is not None and feedback.status == "rejected":
			self.pending_actions.clear()
		if self.pending_actions:
			return SubmitAction(intent=self.pending_actions.pop(0))

		try:
			workflow_view = getattr(frame, "_legacy_workflow_view", None)
			if not isinstance(workflow_view, dict):
				raise KernFailure(
					"WORKFLOW_LEGACY_INPUT_MISSING",
					"legacy action-plan provider requires an internal workflow view",
					origin="workflow",
					phase="decision_input",
					context={"actor_id": frame.actor_id},
				)
			raw = self.provider.decide(
				workflow_view,
				frame.action_catalog,
				frame.actor_id,
				frame.reason,
				frame.mode_context,
			)
		except KernFailure:
			raise
		except Exception as exc:
			raise KernFailure(
				"WORKFLOW_PROVIDER_EXCEPTION",
				str(exc),
				origin="workflow",
				phase="decision",
				context={"actor_id": frame.actor_id, "reason": frame.reason},
			) from exc

		decision, error = validate_workflow_decision(raw)
		if decision is None:
			raise KernFailure(
				"WORKFLOW_CONTRACT_INVALID_DECISION",
				str(error),
				origin="workflow",
				phase="decision_validation",
				context={"actor_id": frame.actor_id, "raw_decision": raw},
			)
		meta = dict(decision.get("meta", {}) or {})
		if str(decision.get("type", "") or "") == "end_turn":
			return EndTurn(meta=meta)
		self.pending_actions = [dict(item) for item in list(decision.get("actions", []) or [])]
		return SubmitAction(intent=self.pending_actions.pop(0), meta=meta)


def as_agent_workflow(provider: Any) -> Any:
	if provider is not None and callable(getattr(provider, "begin_turn", None)):
		return provider
	return ActionPlanWorkflowAdapter(provider)


__all__ = ["ActionPlanWorkflowAdapter", "as_agent_workflow"]
