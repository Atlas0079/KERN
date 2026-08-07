from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, Callable

from .component_catalog import ComponentSpec, DataclassCodec
from .effects import EffectSpec
from .external_runtime_catalog import ExternalRuntimeSpec


_EFFECT_ATTR = "__kern_package_effect_spec__"
_COMPONENT_ATTR = "__kern_package_component_spec__"
_EXTERNAL_RUNTIME_ATTR = "__kern_package_external_runtime_spec__"


def package_effect(spec: EffectSpec) -> Callable[[Any], Any]:
	"""Mark one module-level definition as a Package Effect declaration."""
	if not isinstance(spec, EffectSpec):
		raise TypeError("package_effect requires an EffectSpec")

	def decorate(definition: Any) -> Any:
		setattr(definition, _EFFECT_ATTR, spec)
		return definition

	return decorate


def package_component(component_id: str, *, codec: Any = None, version: str = "1") -> Callable[[type], type]:
	"""Mark a pure dataclass as a Package Component declaration."""
	def decorate(component_type: type) -> type:
		if not isinstance(component_type, type) or not is_dataclass(component_type):
			raise TypeError("package_component requires a dataclass type")
		component_codec = codec or DataclassCodec(component_type)
		setattr(
			component_type,
			_COMPONENT_ATTR,
			ComponentSpec(component_id=str(component_id), component_type=component_type, codec=component_codec, version=str(version)),
		)
		return component_type

	return decorate


def package_external_runtime(spec: ExternalRuntimeSpec) -> Callable[[Any], Any]:
	"""Mark one module-level definition as a Package external runtime declaration."""
	if not isinstance(spec, ExternalRuntimeSpec):
		raise TypeError("package_external_runtime requires an ExternalRuntimeSpec")

	def decorate(definition: Any) -> Any:
		setattr(definition, _EXTERNAL_RUNTIME_ATTR, spec)
		return definition

	return decorate


def marked_effect_spec(value: Any) -> EffectSpec | None:
	spec = getattr(value, _EFFECT_ATTR, None)
	return spec if isinstance(spec, EffectSpec) else None


def marked_component_spec(value: Any) -> ComponentSpec | None:
	spec = getattr(value, _COMPONENT_ATTR, None)
	return spec if isinstance(spec, ComponentSpec) else None


def marked_external_runtime_spec(value: Any) -> ExternalRuntimeSpec | None:
	spec = getattr(value, _EXTERNAL_RUNTIME_ATTR, None)
	return spec if isinstance(spec, ExternalRuntimeSpec) else None
