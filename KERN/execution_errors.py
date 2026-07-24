from __future__ import annotations

import traceback
from typing import Any, NoReturn

ERROR_KIND_BUSINESS = "business"
ERROR_KIND_CONTRACT = "contract"
ERROR_KIND_ENGINE = "engine"
ERROR_KIND_INFRASTRUCTURE = "infrastructure"
ERROR_CATEGORIES = {
	ERROR_KIND_BUSINESS,
	ERROR_KIND_CONTRACT,
	ERROR_KIND_ENGINE,
	ERROR_KIND_INFRASTRUCTURE,
}
FAILURE_DISPOSITION_TERMINAL = "terminal"


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
		category: str = ERROR_KIND_ENGINE,
		disposition: str = FAILURE_DISPOSITION_TERMINAL,
		retryable: bool = False,
		cause: BaseException | None = None,
	) -> None:
		self.code = str(code or "KERN_FAILURE")
		self.origin = str(origin or "kernel")
		self.phase = str(phase or "")
		self.context = dict(context or {})
		clean_category = str(category or ERROR_KIND_ENGINE).strip().lower()
		self.category = clean_category if clean_category in ERROR_CATEGORIES else ERROR_KIND_ENGINE
		self.disposition = str(disposition or FAILURE_DISPOSITION_TERMINAL).strip().lower() or FAILURE_DISPOSITION_TERMINAL
		self.retryable = bool(retryable)
		self.cause = cause
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
		cause = self.cause or self.__cause__ or self.__context__
		payload = {
			"code": self.code,
			"category": self.category,
			"disposition": self.disposition,
			"retryable": self.retryable,
			"message": self.message,
			"origin": self.origin,
			"phase": self.phase,
			"context": dict(self.context),
			"exception_type": type(self).__name__,
		}
		if cause is not None:
			payload["cause"] = {
				"exception_type": type(cause).__name__,
				"message": str(cause),
			}
		return payload

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
	if clean_kind not in ERROR_CATEGORIES:
		clean_kind = ERROR_KIND_ENGINE
	raise KernFailure(
		str(code or "EXECUTOR_FAILURE").strip() or "EXECUTOR_FAILURE",
		str(message or "executor failure"),
		origin=failure_origin,
		phase=str(phase or "effect_execution"),
		context={**dict(context or {}), **({"effect": str(effect or "")} if effect else {})},
		category=clean_kind,
		disposition=FAILURE_DISPOSITION_TERMINAL,
		retryable=False,
	)


__all__ = [
	"ERROR_KIND_BUSINESS",
	"ERROR_KIND_CONTRACT",
	"ERROR_KIND_ENGINE",
	"ERROR_KIND_INFRASTRUCTURE",
	"ERROR_CATEGORIES",
	"FAILURE_DISPOSITION_TERMINAL",
	"KernFailure",
	"executor_error",
]
