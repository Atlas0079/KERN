from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from KERN.llm.provider_factory import build_chat_provider
from KERN.package import LoadedPackages

from .llm_action_provider import LLMWorkflow
from .provider_catalog import build_workflow_catalog
from .registry import WorkflowRegistry
from .simple_policy import SimplePolicyActionProvider
from .social_platform import ActorPlatformBinding, SocialPlatformWorkflow
from .trace import LLMTraceRecorder


@dataclass(frozen=True)
class WorkflowBuildContext:
	project_root: Path
	config_path: Path
	checkpoint_dir: Path
	runtime_config: dict[str, str]
	loaded_packages: LoadedPackages
	trace_recorder: LLMTraceRecorder


class JsonActivationSchedule:
	def __init__(self, active_by_tick: dict[str, Any]) -> None:
		self._active_by_tick = {
			int(tick): frozenset(str(actor_id) for actor_id in list(actor_ids or []))
			for tick, actor_ids in dict(active_by_tick or {}).items()
		}

	def is_active(self, actor_id: str, tick: int) -> bool:
		return str(actor_id) in self._active_by_tick.get(int(tick), frozenset())


WorkflowBuilder = Callable[[WorkflowBuildContext, dict[str, Any]], Any]


def _cfg_get(cfg: dict[str, str], key: str, default: str = "") -> str:
	return str(cfg.get(str(key), default) or default).strip()


def _load_json(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(value, dict):
		raise ValueError(f"workflow data JSON root must be an object: {path}")
	return value


def _world_data_file(context: WorkflowBuildContext, relative_path: str) -> Path:
	path = (context.loaded_packages.world_package.root / "Data" / relative_path).resolve()
	data_root = (context.loaded_packages.world_package.root / "Data").resolve()
	try:
		path.relative_to(data_root)
	except ValueError as exc:
		raise ValueError(f"workflow data path escaped world package Data directory: {relative_path}") from exc
	if not path.is_file():
		raise FileNotFoundError(f"workflow data file not found: {path}")
	return path


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


def _chat_provider_from_runtime_config(cfg: dict[str, str]):
	api_key = _cfg_get(cfg, "LLM_API_KEY")
	if not api_key:
		api_key_env = _cfg_get(cfg, "LLM_API_KEY_ENV", "LLM_API_KEY")
		api_key = os.environ[str(api_key_env)]
	request_extra_raw = _cfg_get(cfg, "LLM_REQUEST_EXTRA_JSON")
	return build_chat_provider(
		{
			"protocol": _cfg_get(cfg, "LLM_PROVIDER", "openai_compat"),
			"base_url": _cfg_get(cfg, "LLM_BASE_URL"),
			"api_prefix": _cfg_get(cfg, "LLM_API_PREFIX", "/v1"),
			"api_key": api_key,
			"timeout_seconds": int(_cfg_get(cfg, "LLM_TIMEOUT_SECONDS", "60")),
			"max_retries": int(_cfg_get(cfg, "LLM_MAX_RETRIES", "2")),
			"retry_backoff_seconds": float(_cfg_get(cfg, "LLM_RETRY_BACKOFF_SECONDS", "1.0")),
		}
	), json.loads(request_extra_raw) if request_extra_raw else {}


def _build_social_platform_workflow(context: WorkflowBuildContext, options: dict[str, Any]) -> Any:
	unknown = set(options).difference({"model", "temperature", "max_tokens", "max_memory_items", "identity_component_id"})
	if unknown:
		raise ValueError(f"social_platform workflow options have unknown fields: {sorted(unknown)}")
	schedule = _load_json(_world_data_file(context, "Study/activation_schedule.json"))
	if schedule.get("schema_version") != "social_activation_schedule.v1":
		raise ValueError("social_platform workflow requires social_activation_schedule.v1")
	bindings_payload = _load_json(_world_data_file(context, "Study/actor_bindings.json"))
	if bindings_payload.get("schema_version") != "social_actor_bindings.v1":
		raise ValueError("social_platform workflow requires social_actor_bindings.v1")
	study_config_path = context.loaded_packages.world_package.root / "Study" / "study_config.v1.json"
	study_config = _load_json(study_config_path)
	conditions = list(study_config.get("conditions", []) or [])
	post_ids = {str(condition.get("post_id", "") or "").strip() for condition in conditions if isinstance(condition, dict)}
	if len(post_ids) != 1 or not next(iter(post_ids)):
		raise ValueError("social_platform workflow requires paired conditions with one stable experimental post_id")
	client, request_extra = _chat_provider_from_runtime_config(context.runtime_config)
	bindings = {
		str(actor_id): ActorPlatformBinding(
			terminal_id=str(binding["terminal_id"]),
			account_id=str(binding["account_id"]),
			runtime_id=str(binding.get("runtime_id", "social_platform")),
		)
		for actor_id, binding in dict(bindings_payload.get("bindings", {}) or {}).items()
	}
	return SocialPlatformWorkflow(
		activation_schedule=JsonActivationSchedule(dict(schedule["active_by_tick"])),
		actor_bindings=bindings,
		client=client,
		model=str(options.get("model", "") or _cfg_get(context.runtime_config, "SOCIAL_WORKFLOW_MODEL", _cfg_get(context.runtime_config, "LLM_PLANNER_MODEL"))),
		experimental_post_id=next(iter(post_ids)),
		temperature=float(options.get("temperature", _cfg_get(context.runtime_config, "SOCIAL_WORKFLOW_TEMPERATURE", "0.2"))),
		max_tokens=int(options.get("max_tokens", _cfg_get(context.runtime_config, "SOCIAL_WORKFLOW_MAX_TOKENS", "1200"))),
		request_extra=request_extra,
		trace_recorder=context.trace_recorder,
		max_memory_items=int(options.get("max_memory_items", 20)),
		workflow_id="social_platform",
		identity_component_id=str(options.get("identity_component_id", "sea_level_social_experiment:SocialIdentityComponent")),
	)


BUILTIN_WORKFLOW_BUILDERS: dict[str, WorkflowBuilder] = {
	"simple": _build_simple_workflow,
	"llm": _build_llm_workflow,
	"social_platform": _build_social_platform_workflow,
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
	"JsonActivationSchedule",
	"WorkflowBuildContext",
	"build_builtin_workflow_registry",
]
