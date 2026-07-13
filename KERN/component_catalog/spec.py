from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ComponentCodec(Protocol):
	def build(self, raw: Any) -> Any: ...

	def serialize(self, component: Any) -> dict[str, Any]: ...

	def apply_snapshot(self, component: Any, patch: dict[str, Any], *, restore_container_items: bool = True) -> Any: ...


@dataclass(frozen=True)
class ComponentSpec:
	component_id: str
	component_type: type
	codec: ComponentCodec
	origin: str = "core"
	version: str = "1"
