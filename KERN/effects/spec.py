from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


BindCallable = Callable[[Any, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]
HandlerCallable = Callable[[Any, Any, dict[str, Any], dict[str, Any]], list[dict[str, Any]]]
RecorderCallable = Callable[[Any, dict[str, Any], dict[str, Any], list[dict[str, Any]]], str | list[str] | None]


SIDE_EFFECT_POLICIES = frozenset(
	{
		"world",
		"external_transactional",
		"external_compensatable",
		"external_irreversible",
	}
)


@dataclass(frozen=True)
class EffectSpec:
	effect_id: str
	module: str = ""
	binder_name: str = ""
	handler_name: str = ""
	recorder_name: str = ""
	binder: BindCallable | None = None
	handler: HandlerCallable | None = None
	recorder: RecorderCallable | None = None
	visibility: str = "public"
	origin: str = "core"
	side_effect: str = "world"
	allows_child_bundle: bool = False
	emits: tuple[str, ...] = ()
	version: str = "1"
