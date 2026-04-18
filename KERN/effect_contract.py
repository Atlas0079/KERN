from __future__ import annotations

from functools import lru_cache
import importlib
import re

EFFECT_SPECS: dict[str, dict[str, str]] = {
	"AgentControlTick": {"module": "KERN.executor._effect_agent"},
	"WorkerTick": {"module": "KERN.executor._effect_agent"},
	"StatusTick": {"module": "KERN.executor._effect_task"},
	"ModifyProperty": {"module": "KERN.executor._effect_property"},
	"AddTag": {"module": "KERN.executor._effect_property"},
	"RemoveTag": {"module": "KERN.executor._effect_property"},
	"ApplyMetaAction": {"module": "KERN.executor._effect_agent"},
	"AttachDetails": {"module": "KERN.executor._effect_agent"},
	"CreateEntity": {"module": "KERN.executor._effect_entity"},
	"DestroyEntity": {"module": "KERN.executor._effect_entity"},
	"MoveEntity": {"module": "KERN.executor._effect_entity"},
	"AddStatus": {"module": "KERN.executor._effect_task"},
	"RemoveStatus": {"module": "KERN.executor._effect_task"},
	"ConsumeInputs": {"module": "KERN.executor._effect_task"},
	"CreateTask": {"module": "KERN.executor._effect_task"},
	"AcceptTask": {"module": "KERN.executor._effect_task"},
	"ProgressTask": {"module": "KERN.executor._effect_task"},
	"UpdateTaskStatus": {"module": "KERN.executor._effect_task"},
	"FinishTask": {"module": "KERN.executor._effect_task"},
	"InterruptTask": {"module": "KERN.executor._effect_task"},
	"ResumeTask": {"module": "KERN.executor._effect_task"},
	"CancelTask": {"module": "KERN.executor._effect_task"},
	"KillEntity": {"module": "KERN.executor._effect_entity"},
	"StartConversation": {"module": "KERN.executor._effect_conversation"},
	"AddMemoryNote": {"module": "KERN.executor._effect_memory"},
	"ApplyMemoryPatch": {"module": "KERN.executor._effect_memory"},
	"EmitEvent": {"module": "KERN.executor._effect_event"},
	"ExchangeResources": {"module": "KERN.executor._effect_resource"},
	"AbortSimulation": {"module": "KERN.executor._effect_resource"},
}

EFFECT_TYPES = frozenset(EFFECT_SPECS.keys())


def _camel_to_snake(name: str) -> str:
	text = str(name or "").strip()
	if not text:
		return ""
	s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
	return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _default_binder_name(effect_name: str) -> str:
	return f"_bind_{_camel_to_snake(effect_name)}"


def _default_handler_name(effect_name: str) -> str:
	return f"execute_{_camel_to_snake(effect_name)}"


def _resolve_effect_callable(effect_name: str, kind: str):
	spec = EFFECT_SPECS.get(str(effect_name), {}) or {}
	module_path = str(spec.get("module", "") or "").strip()
	if not module_path:
		return None
	if kind == "binder":
		func_name = str(spec.get("binder", "") or "").strip() or _default_binder_name(str(effect_name))
	else:
		func_name = str(spec.get("handler", "") or "").strip() or _default_handler_name(str(effect_name))
	if not func_name:
		return None
	try:
		module = importlib.import_module(module_path)
	except Exception:
		return None
	candidate = getattr(module, func_name, None)
	if not callable(candidate):
		return None
	return candidate


@lru_cache(maxsize=None)
def resolve_effect_binder_callable(effect_name: str):
	return _resolve_effect_callable(str(effect_name), "binder")


@lru_cache(maxsize=None)
def resolve_effect_handler_callable(effect_name: str):
	return _resolve_effect_callable(str(effect_name), "handler")


def get_effect_module_path(effect_name: str) -> str:
	spec = EFFECT_SPECS.get(str(effect_name), {}) or {}
	return str(spec.get("module", "") or "").strip()


def get_effect_callable_names(effect_name: str) -> tuple[str, str]:
	spec = EFFECT_SPECS.get(str(effect_name), {}) or {}
	binder_name = str(spec.get("binder", "") or "").strip() or _default_binder_name(str(effect_name))
	handler_name = str(spec.get("handler", "") or "").strip() or _default_handler_name(str(effect_name))
	return binder_name, handler_name


def diff_effect_types(actual: set[str] | frozenset[str], expected: set[str] | frozenset[str], actual_name: str) -> list[str]:
	actual_set = {str(x) for x in set(actual or set()) if str(x)}
	expected_set = {str(x) for x in set(expected or set()) if str(x)}
	missing = sorted(expected_set - actual_set)
	extra = sorted(actual_set - expected_set)
	out: list[str] = []
	if missing:
		out.append(f"{actual_name} missing effect types: {missing}")
	if extra:
		out.append(f"{actual_name} has unknown effect types: {extra}")
	return out
