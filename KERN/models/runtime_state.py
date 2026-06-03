from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
	dialogue_budget_limit_per_location: int = 4
	dialogue_budget_used_per_location: dict[str, int] = field(default_factory=dict)
	dialogue_log_full: bool = False

	workflow_contract_on_error: str = "fail_fast"

	abort_requested: bool = False
	abort_reason: str = ""
	abort_detail: str = ""
	abort_severity: str = ""
	abort_actor_id: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"dialogue_budget_limit_per_location": self.dialogue_budget_limit_per_location,
			"dialogue_budget_used_per_location": dict(self.dialogue_budget_used_per_location),
			"dialogue_log_full": self.dialogue_log_full,
			"workflow_contract_on_error": self.workflow_contract_on_error,
			"abort_requested": self.abort_requested,
			"abort_reason": self.abort_reason,
			"abort_detail": self.abort_detail,
			"abort_severity": self.abort_severity,
			"abort_actor_id": self.abort_actor_id,
		}

	@staticmethod
	def from_dict(data: dict[str, Any]) -> RuntimeState:
		return RuntimeState(
			dialogue_budget_limit_per_location=int(data.get("dialogue_budget_limit_per_location", 4) or 4),
			dialogue_budget_used_per_location=dict(data.get("dialogue_budget_used_per_location", {}) or {}),
			dialogue_log_full=bool(data.get("dialogue_log_full", False)),
			workflow_contract_on_error=str(data.get("workflow_contract_on_error", "fail_fast") or "fail_fast"),
			abort_requested=bool(data.get("abort_requested", False)),
			abort_reason=str(data.get("abort_reason", "") or ""),
			abort_detail=str(data.get("abort_detail", "") or ""),
			abort_severity=str(data.get("abort_severity", "") or ""),
			abort_actor_id=str(data.get("abort_actor_id", "") or ""),
		)
