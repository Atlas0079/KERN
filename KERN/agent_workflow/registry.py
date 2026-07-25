from __future__ import annotations

from typing import Any


class WorkflowRegistry:
	"""Runtime-scoped registry for replaceable Agent Workflow implementations."""

	def __init__(self, default_workflow: Any = None) -> None:
		self._default_workflow = default_workflow
		self._workflows: dict[str, Any] = {}
		self._frozen = False

	@property
	def default_workflow(self) -> Any:
		return self._default_workflow

	def set_default(self, workflow: Any) -> None:
		if self._frozen:
			raise RuntimeError("workflow registry is frozen")
		self._default_workflow = workflow

	def register(self, workflow_id: str, workflow: Any) -> None:
		if self._frozen:
			raise RuntimeError("workflow registry is frozen")
		clean_id = str(workflow_id or "").strip()
		if not clean_id:
			raise ValueError("workflow id must not be blank")
		if clean_id != str(workflow_id):
			raise ValueError(f"workflow id must not contain surrounding whitespace: {workflow_id!r}")
		if clean_id in self._workflows:
			raise ValueError(f"workflow id already registered: {clean_id}")
		self._workflows[clean_id] = workflow

	def freeze(self) -> None:
		self._frozen = True

	def resolve(self, controller: Any | None, requested_workflow_id: str = "") -> Any:
		for workflow_id in (
			str(requested_workflow_id or "").strip(),
			str(getattr(controller, "provider_id", "") or "").strip(),
		):
			if workflow_id and workflow_id in self._workflows:
				return self._workflows[workflow_id]
		return self._default_workflow

	def workflow_ids(self) -> frozenset[str]:
		return frozenset(self._workflows)

	@classmethod
	def from_legacy(cls, default_workflow: Any, workflows: dict[str, Any] | None = None) -> "WorkflowRegistry":
		registry = cls(default_workflow)
		for workflow_id, workflow in dict(workflows or {}).items():
			if str(workflow_id or "").strip():
				registry.register(str(workflow_id), workflow)
		return registry


__all__ = ["WorkflowRegistry"]
