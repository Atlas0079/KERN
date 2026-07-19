from __future__ import annotations

import importlib
import re

from .spec import EffectSpec, SIDE_EFFECT_POLICIES


class EffectResolutionError(RuntimeError):
	def __init__(self, effect_id: str, kind: str, module: str, callable_name: str, reason: str) -> None:
		self.effect_id = str(effect_id)
		self.kind = str(kind)
		self.module = str(module)
		self.callable_name = str(callable_name)
		self.reason = str(reason)
		symbol = f"{self.module}.{self.callable_name}" if self.module else self.callable_name
		super().__init__(f"{self.effect_id}: {self.kind} resolution failed for {symbol}: {self.reason}")


class EffectCatalog:
	def __init__(self) -> None:
		self._specs: dict[str, EffectSpec] = {}
		self._frozen = False
		self._binder_cache: dict[str, object | None] = {}
		self._handler_cache: dict[str, object | None] = {}

	def register(self, spec: EffectSpec) -> None:
		if self._frozen:
			raise RuntimeError("effect catalog is frozen")
		effect_id = str(spec.effect_id or "").strip()
		if not effect_id:
			raise ValueError("effect id must not be blank")
		if effect_id != str(spec.effect_id):
			raise ValueError(f"effect id must not contain surrounding whitespace: {spec.effect_id!r}")
		if effect_id in self._specs:
			raise ValueError(f"effect id already registered: {effect_id}")
		if str(spec.side_effect or "") not in SIDE_EFFECT_POLICIES:
			raise ValueError(f"effect side_effect is invalid for {effect_id}: {spec.side_effect!r}")
		self._specs[effect_id] = spec

	def contains(self, effect_id: str) -> bool:
		return str(effect_id or "") in self._specs

	def freeze(self) -> None:
		self._frozen = True

	def require(self, effect_id: str) -> EffectSpec:
		clean_id = str(effect_id or "")
		try:
			return self._specs[clean_id]
		except KeyError as exc:
			raise KeyError(f"effect id is not registered: {clean_id}") from exc

	def effect_ids(self) -> frozenset[str]:
		return frozenset(self._specs)

	def resolve_binder(self, effect_id: str):
		return self._resolve_callable(effect_id, "binder")

	def resolve_handler(self, effect_id: str):
		return self._resolve_callable(effect_id, "handler")

	def clone_mutable(self) -> "EffectCatalog":
		clone = EffectCatalog()
		for spec in self._specs.values():
			clone.register(spec)
		return clone

	def _resolve_callable(self, effect_id: str, kind: str):
		clean_id = str(effect_id or "")
		cache = self._binder_cache if kind == "binder" else self._handler_cache
		if clean_id in cache:
			return cache[clean_id]
		spec = self._specs.get(clean_id)
		if spec is None:
			return None
		direct = spec.binder if kind == "binder" else spec.handler
		if callable(direct):
			cache[clean_id] = direct
			return direct
		module_path = str(spec.module or "").strip()
		function_name = str(spec.binder_name if kind == "binder" else spec.handler_name).strip()
		if not function_name:
			function_name = default_binder_name(clean_id) if kind == "binder" else default_handler_name(clean_id)
		if not module_path:
			raise EffectResolutionError(clean_id, kind, module_path, function_name, "module path is empty")
		try:
			module = importlib.import_module(module_path)
		except Exception as exc:
			raise EffectResolutionError(clean_id, kind, module_path, function_name, str(exc)) from exc
		candidate = getattr(module, function_name, None)
		if not callable(candidate):
			raise EffectResolutionError(clean_id, kind, module_path, function_name, "callable was not found")
		cache[clean_id] = candidate
		return candidate


def _camel_to_snake(name: str) -> str:
	text = str(name or "").strip()
	if not text:
		return ""
	s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
	return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def default_binder_name(effect_id: str) -> str:
	return f"_bind_{_camel_to_snake(str(effect_id).rsplit(':', 1)[-1])}"


def default_handler_name(effect_id: str) -> str:
	return f"execute_{_camel_to_snake(str(effect_id).rsplit(':', 1)[-1])}"
