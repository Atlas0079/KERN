from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from KERN.agent_workflow.registry import WorkflowRegistry
from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.llm.provider_factory import build_chat_provider
from KERN.package import LoadedPackages, load_packages_from_config
from KERN.runtime import KernRuntime, _load_runtime_config

from .workflow import ActorPlatformBinding, SocialPlatformWorkflow


class JsonActivationSchedule:
	def __init__(self, active_by_tick: dict[str, Any]) -> None:
		self._active_by_tick = {
			int(tick): frozenset(str(actor_id) for actor_id in list(actor_ids or []))
			for tick, actor_ids in dict(active_by_tick or {}).items()
		}

	def is_active(self, actor_id: str, tick: int) -> bool:
		return str(actor_id) in self._active_by_tick.get(int(tick), frozenset())


def _cfg_get(cfg: dict[str, str], key: str, default: str = "") -> str:
	return str(cfg.get(str(key), default) or default).strip()


def _load_json(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(value, dict):
		raise ValueError(f"workflow data JSON root must be an object: {path}")
	return value


def _world_data_file(loaded_packages: LoadedPackages, relative_path: str) -> Path:
	path = (loaded_packages.world_package.root / "Data" / relative_path).resolve()
	data_root = (loaded_packages.world_package.root / "Data").resolve()
	try:
		path.relative_to(data_root)
	except ValueError as exc:
		raise ValueError(f"workflow data path escaped world package Data directory: {relative_path}") from exc
	if not path.is_file():
		raise FileNotFoundError(f"workflow data file not found: {path}")
	return path


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


def _build_social_platform_workflow(loaded_packages: LoadedPackages, runtime_config: dict[str, str], options: dict[str, Any]) -> SocialPlatformWorkflow:
	unknown = set(options).difference({"model", "temperature", "max_tokens", "max_memory_items", "identity_component_id"})
	if unknown:
		raise ValueError(f"social_platform workflow options have unknown fields: {sorted(unknown)}")
	schedule = _load_json(_world_data_file(loaded_packages, "Study/activation_schedule.json"))
	if schedule.get("schema_version") != "social_activation_schedule.v1":
		raise ValueError("social_platform workflow requires social_activation_schedule.v1")
	bindings_payload = _load_json(_world_data_file(loaded_packages, "Study/actor_bindings.json"))
	if bindings_payload.get("schema_version") != "social_actor_bindings.v1":
		raise ValueError("social_platform workflow requires social_actor_bindings.v1")
	study_config_path = loaded_packages.world_package.root / "Study" / "study_config.v1.json"
	study_config = _load_json(study_config_path)
	conditions = list(study_config.get("conditions", []) or [])
	post_ids = {str(condition.get("post_id", "") or "").strip() for condition in conditions if isinstance(condition, dict)}
	if len(post_ids) != 1 or not next(iter(post_ids)):
		raise ValueError("social_platform workflow requires paired conditions with one stable experimental post_id")
	client, request_extra = _chat_provider_from_runtime_config(runtime_config)
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
		model=str(options.get("model", "") or _cfg_get(runtime_config, "SOCIAL_WORKFLOW_MODEL", _cfg_get(runtime_config, "LLM_PLANNER_MODEL"))),
		experimental_post_id=next(iter(post_ids)),
		temperature=float(options.get("temperature", _cfg_get(runtime_config, "SOCIAL_WORKFLOW_TEMPERATURE", "0.2"))),
		max_tokens=int(options.get("max_tokens", _cfg_get(runtime_config, "SOCIAL_WORKFLOW_MAX_TOKENS", "1200"))),
		request_extra=request_extra,
		max_memory_items=int(options.get("max_memory_items", 20)),
		workflow_id="social_platform",
		identity_component_id=str(options.get("identity_component_id", "sea_level_social_experiment:SocialIdentityComponent")),
	)


def create_runtime(
    project_root: str | Path,
    config_path: str | Path,
    *,
    validate: bool = True,
    configure_logging: bool = True,
    overrides: dict[str, Any] | None = None,
) -> KernRuntime:
    """Build this experiment's policy registry, then inject it into KERN."""
    root = Path(project_root).resolve()
    cfg, resolved = _load_runtime_config(root, str(config_path))
    for key, value in dict(overrides or {}).items():
        clean_key = str(key or "").strip()
        if clean_key and value is not None:
            cfg[clean_key] = str(value)
    default = json.loads(cfg.get("DEFAULT_WORKFLOW_PROVIDER_JSON", '{}'))
    if not isinstance(default, dict) or set(default).difference({"kind", "options"}) or default.get("options"):
        raise ValueError("social experiment requires a simple default workflow without options")
    if _cfg_get(cfg, "DEFAULT_WORKFLOW_KIND", str(default.get("kind", "simple"))) != "simple":
        raise ValueError("social experiment requires default_workflow_provider: {kind: simple}")
    specs = json.loads(cfg.get("WORKFLOW_PROVIDERS_JSON", '[]'))
    if not isinstance(specs, list) or not specs:
        raise ValueError("social experiment requires workflow_providers")
    loaded = load_packages_from_config(root, resolved)
    registry = WorkflowRegistry(SimplePolicyActionProvider())
    workflows: list[SocialPlatformWorkflow] = []
    for spec in specs:
        if not isinstance(spec, dict) or set(spec).difference({"workflow_id", "kind", "options"}):
            raise ValueError("invalid social experiment workflow provider")
        if spec.get("kind") != "social_platform":
            raise ValueError("social experiment supports only social_platform workflow providers")
        workflow_id = spec.get("workflow_id", "")
        if not isinstance(workflow_id, str) or not workflow_id.strip() or workflow_id != workflow_id.strip():
            raise ValueError("social workflow_id must be a non-blank trimmed string")
        options = spec.get("options", {})
        if not isinstance(options, dict):
            raise ValueError("social workflow options must be an object")
        workflow = _build_social_platform_workflow(loaded, cfg, options)
        workflow.workflow_id = workflow_id
        registry.register(workflow_id, workflow)
        workflows.append(workflow)
    runtime = KernRuntime.from_loaded_packages(
        loaded, root, resolved, validate=validate, configure_logging=configure_logging,
        overrides=overrides, workflow_registry=registry,
    )
    # Use the runtime's recorder so action results update the same trace files.
    for workflow in workflows:
        workflow.trace_recorder = runtime.llm_trace_recorder
    return runtime
