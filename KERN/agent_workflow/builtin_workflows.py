from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from KERN.package import LoadedPackages

from .llm_action_provider import LLMWorkflow
from .provider_catalog import build_workflow_catalog
from .registry import WorkflowRegistry
from .simple_policy import SimplePolicyActionProvider
from .trace import LLMTraceRecorder


@dataclass(frozen=True)
class WorkflowBuildContext:
	project_root: Path
	config_path: Path
	checkpoint_dir: Path
	runtime_config: dict[str, str]
	loaded_packages: LoadedPackages
	trace_recorder: LLMTraceRecorder


WorkflowBuilder = Callable[[WorkflowBuildContext, dict[str, Any]], Any]


def _cfg_get(cfg: dict[str, str], key: str, default: str = "") -> str:
	return str(cfg.get(str(key), default) or default).strip()


def _build_simple_workflow(_context: WorkflowBuildContext, _options: dict[str, Any]) -> Any:
	return SimplePolicyActionProvider()


def _build_llm_workflow(context: WorkflowBuildContext, options: dict[str, Any]) -> Any:
	if options:
		raise ValueError("llm workflow does not accept per-provider options; use top-level llm_providers/workflows")
	workflow_config_raw = _cfg_get(context.runtime_config, "LLM_WORKFLOW_CONFIG_JSON")
	if not workflow_config_raw:
		raise ValueError("llm workflow requires top-level llm_providers, workflows, and default_workflow_id")
	default_workflow, named = build_workflow_catalog(json.loads(workflow_config_raw), trace_recorder=context.trace_recorder)
	return {"default": default_workflow, "named": named}


BUILTIN_WORKFLOW_BUILDERS: dict[str, WorkflowBuilder] = {
	"simple": _build_simple_workflow,
	"llm": _build_llm_workflow,
}


def build_builtin_workflow_registry(
	context: WorkflowBuildContext,
	provider_specs: list[dict[str, Any]],
	default_kind: str,
	default_options: dict[str, Any] | None = None,
) -> tuple[WorkflowRegistry, Any, dict[str, Any]]:
	default_spec = {"workflow_id": "default", "kind": default_kind, "options": dict(default_options or {})}
	default_result = _build_workflow_from_spec(context, default_spec)
	if isinstance(default_result, dict) and set(default_result) == {"default", "named"} and default_kind == "llm":
		default_workflow = default_result["default"]
		named_workflows = dict(default_result["named"])
	else:
		default_workflow = default_result
		named_workflows = {}
	registry = WorkflowRegistry(default_workflow)
	for workflow_id, workflow in named_workflows.items():
		registry.register(workflow_id, workflow)
	for raw in provider_specs:
		spec = dict(raw)
		workflow_id = str(spec.get("workflow_id", "") or "").strip()
		if not workflow_id:
			raise ValueError("workflow provider workflow_id must not be blank")
		if workflow_id in named_workflows:
			raise ValueError(f"workflow provider id already registered: {workflow_id}")
		registry.register(workflow_id, _build_workflow_from_spec(context, spec))
	return registry, default_workflow, named_workflows


def _build_workflow_from_spec(context: WorkflowBuildContext, spec: dict[str, Any]) -> Any:
	unknown = set(spec).difference({"workflow_id", "kind", "options"})
	if unknown:
		raise ValueError(f"workflow provider has unknown fields: {sorted(unknown)}")
	kind = str(spec.get("kind", "") or "").strip()
	if kind not in BUILTIN_WORKFLOW_BUILDERS:
		raise ValueError(f"unknown built-in workflow kind: {kind}")
	return BUILTIN_WORKFLOW_BUILDERS[kind](context, dict(spec.get("options", {}) or {}))


__all__ = [
	"BUILTIN_WORKFLOW_BUILDERS",
	"WorkflowBuildContext",
	"build_builtin_workflow_registry",
]
