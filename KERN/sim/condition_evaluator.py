from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..query import compare_values, evaluate_predicate, explain_predicate, resolve_value


@dataclass
class ConditionEvaluator:
	def evaluate(self, ws: Any, condition: dict[str, Any] | None, context: dict[str, Any] | None) -> bool:
		return evaluate_predicate(ws, condition, context)

	def explain(self, ws: Any, condition: dict[str, Any] | None, context: dict[str, Any] | None, path: str = "root") -> dict[str, Any]:
		return explain_predicate(ws, condition, context, path=path)

	def _resolve_compare_value(self, ws: Any, ref: str, context: dict[str, Any]) -> Any:
		return resolve_value(ws, ref, context)

	@staticmethod
	def _compare(actual: Any, expected: Any, op: str) -> bool:
		return compare_values(actual, expected, op)
