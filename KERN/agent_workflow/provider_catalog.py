from __future__ import annotations

import os
from typing import Any

from ..llm.provider_factory import build_chat_provider
from .llm_action_provider import LLMWorkflow
from .trace import LLMTraceRecorder


def build_workflow_catalog(config: dict[str, Any], *, trace_recorder: LLMTraceRecorder | None = None) -> tuple[Any, dict[str, Any]]:
	providers: dict[str, Any] = {}
	for provider_id, definition in dict(config["llm_providers"]).items():
		provider_key = str(provider_id).strip()
		if not provider_key:
			raise ValueError("llm provider id must not be blank")
		if provider_key != str(provider_id):
			raise ValueError(f"llm provider id must not contain surrounding whitespace: {provider_id!r}")
		item = dict(definition)
		if bool(item.get("api_key")) == bool(item.get("api_key_env")):
			raise ValueError(f"provider {provider_id} requires exactly one of api_key/api_key_env")
		if item.get("api_key_env"):
			item["api_key"] = os.environ[str(item["api_key_env"])]
		providers[provider_key] = build_chat_provider(item)
	workflows: dict[str, Any] = {}
	for workflow_id, definition in dict(config["workflows"]).items():
		workflow_key = str(workflow_id).strip()
		if not workflow_key:
			raise ValueError("workflow id must not be blank")
		if workflow_key != str(workflow_id):
			raise ValueError(f"workflow id must not contain surrounding whitespace: {workflow_id!r}")
		roles = {key: dict(value) for key, value in dict(definition["roles"]).items()}
		if definition.get("kind") != "llm" or not all(role in roles for role in ("planner", "grounder", "dialogue")):
			raise ValueError(f"invalid llm workflow: {workflow_id}")
		for binding in roles.values():
			provider_id = str(binding["provider_id"]).strip()
			model = str(binding["model"]).strip()
			if provider_id not in providers or not model:
				raise ValueError(f"invalid workflow role binding: {workflow_id}")
			binding["provider_id"] = provider_id
			binding["model"] = model
			if "request_extra" in binding:
				binding["request_extra"] = dict(binding["request_extra"])
		options = dict(definition.get("options", {}) or {})
		workflows[workflow_key] = LLMWorkflow(
			providers=providers,
			roles=roles,
			debug=bool(options.get("debug", False)),
			focus_agent_id=str(options.get("focus_agent_id", "") or ""),
			focus_log_prompts=bool(options.get("focus_log_prompts", False)),
			focus_log_perception=bool(options.get("focus_log_perception", True)),
			llm_debug_view=str(options.get("llm_debug_view", "") or ""),
			trace_recorder=trace_recorder,
		)
	default_id = str(config["default_workflow_id"])
	return workflows.pop(default_id), workflows
