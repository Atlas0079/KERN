from __future__ import annotations

import traceback
from typing import Any, NoReturn

ERROR_KIND_BUSINESS = "business"
ERROR_KIND_CONTRACT = "contract"
ERROR_KIND_ENGINE = "engine"


class KernFailure(RuntimeError):
	"""A fatal kernel failure that must terminate the current simulation."""

	def __init__(
		self,
		code: str,
		message: str,
		*,
		origin: str = "kernel",
		phase: str = "",
		context: dict[str, Any] | None = None,
	) -> None:
		self.code = str(code or "KERN_FAILURE")
		self.origin = str(origin or "kernel")
		self.phase = str(phase or "")
		self.context = dict(context or {})
		super().__init__(str(message or self.code))

	@property
	def message(self) -> str:
		return str(self.args[0] if self.args else "")

	def add_context(self, **values: Any) -> "KernFailure":
		for key, value in values.items():
			if value is not None and value != "":
				self.context.setdefault(str(key), value)
		return self

	def to_dict(self) -> dict[str, Any]:
		return {
			"code": self.code,
			"message": self.message,
			"origin": self.origin,
			"phase": self.phase,
			"context": dict(self.context),
			"exception_type": type(self).__name__,
		}

	def traceback_text(self) -> str:
		return "".join(traceback.format_exception(self)).strip()


def executor_error(
	message: str,
	*,
	kind: str = ERROR_KIND_ENGINE,
	code: str = "",
	effect: str = "",
	origin: str = "",
	phase: str = "",
	context: dict[str, Any] | None = None,
) -> NoReturn:
	"""Raise the canonical fatal failure used by Effect handlers."""
	failure_origin = str(origin or "").strip() or "executor"
	clean_kind = str(kind or ERROR_KIND_ENGINE).strip().lower()
	if clean_kind not in {ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, ERROR_KIND_ENGINE}:
		clean_kind = ERROR_KIND_ENGINE
	raise KernFailure(
		str(code or "EXECUTOR_FAILURE").strip() or "EXECUTOR_FAILURE",
		str(message or "executor failure"),
		origin=failure_origin,
		phase=str(phase or "effect_execution"),
		context={**dict(context or {}), **({"effect": str(effect or "")} if effect else {})},
	)


__all__ = ["ERROR_KIND_BUSINESS", "ERROR_KIND_CONTRACT", "ERROR_KIND_ENGINE", "KernFailure", "executor_error"]
