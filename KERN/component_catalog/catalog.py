from __future__ import annotations

from typing import Any

from ..models.components import CustomComponent
from .spec import ComponentSpec


class ComponentCatalog:
	def __init__(self) -> None:
		self._specs: dict[str, ComponentSpec] = {}
		self._frozen = False

	def register(self, spec: ComponentSpec) -> None:
		if self._frozen:
			raise RuntimeError("component catalog is frozen")
		component_id = str(spec.component_id or "").strip()
		if not component_id:
			raise ValueError("component id must not be blank")
		if component_id != str(spec.component_id):
			raise ValueError(f"component id must not contain surrounding whitespace: {spec.component_id!r}")
		if component_id in self._specs:
			raise ValueError(f"component id already registered: {component_id}")
		if not isinstance(spec.component_type, type):
			raise TypeError(f"component type must be a class: {component_id}")
		for method_name in ("build", "serialize", "apply_snapshot"):
			if not callable(getattr(spec.codec, method_name, None)):
				raise TypeError(f"component codec missing {method_name}(): {component_id}")
		self._specs[component_id] = spec

	def contains(self, component_id: str) -> bool:
		return str(component_id or "") in self._specs

	def build(self, component_id: str, raw: Any) -> Any:
		spec = self._specs.get(str(component_id or ""))
		if spec is None:
			data = dict(raw) if isinstance(raw, dict) else {"value": raw}
			return CustomComponent(data=data)
		return spec.codec.build(raw)

	def serialize(self, component_id: str, component: Any) -> dict[str, Any]:
		spec = self._specs.get(str(component_id or ""))
		if spec is None:
			if not isinstance(component, CustomComponent):
				raise TypeError(f"unregistered component is not CustomComponent: {component_id}")
			return dict(component.data or {})
		if not isinstance(component, spec.component_type):
			raise TypeError(f"component type mismatch for {component_id}: {type(component).__name__}")
		return spec.codec.serialize(component)

	def apply_snapshot(
		self,
		component_id: str,
		component: Any,
		patch: dict[str, Any],
		*,
		restore_container_items: bool = True,
	) -> Any:
		spec = self._specs.get(str(component_id or ""))
		if spec is None:
			if not isinstance(component, CustomComponent):
				raise TypeError(f"unregistered component is not CustomComponent: {component_id}")
			component.data.update(dict(patch or {}))
			return component
		if not isinstance(component, spec.component_type):
			raise TypeError(f"component type mismatch for {component_id}: {type(component).__name__}")
		return spec.codec.apply_snapshot(
			component,
			dict(patch or {}),
			restore_container_items=restore_container_items,
		)

	def freeze(self) -> None:
		self._frozen = True

	def clone_mutable(self) -> "ComponentCatalog":
		clone = ComponentCatalog()
		for spec in self._specs.values():
			clone.register(spec)
		return clone

	def component_ids(self) -> frozenset[str]:
		return frozenset(self._specs)
