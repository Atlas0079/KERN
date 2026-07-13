from __future__ import annotations

from types import MappingProxyType

from .effects import build_core_effect_catalog
from .effects.catalog import default_binder_name, default_handler_name
from .effects.core import CORE_EFFECT_MODULES


EFFECT_SPECS = MappingProxyType(
	{effect_id: MappingProxyType({"module": module}) for effect_id, module in CORE_EFFECT_MODULES}
)
EFFECT_TYPES = frozenset(EFFECT_SPECS)


def resolve_effect_binder_callable(effect_name: str):
	return build_core_effect_catalog().resolve_binder(str(effect_name))


def resolve_effect_handler_callable(effect_name: str):
	return build_core_effect_catalog().resolve_handler(str(effect_name))


def get_effect_module_path(effect_name: str) -> str:
	spec = EFFECT_SPECS.get(str(effect_name), {}) or {}
	return str(spec.get("module", "") or "").strip()


def get_effect_callable_names(effect_name: str) -> tuple[str, str]:
	name = str(effect_name)
	return default_binder_name(name), default_handler_name(name)


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
