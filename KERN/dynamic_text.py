from __future__ import annotations

import re
from typing import Any

from .entity_ref_resolver import resolve_entity_id
from .query.core import resolve_path_value, resolve_value


PLACEHOLDER_RE = re.compile(r"\{([^{}\r\n]+)\}")

PAYLOAD_TEXT_KEYS = frozenset(
	{
		"message",
		"text",
		"description",
		"detail",
		"reason",
		"summary",
		"name",
		"label",
	}
)


class DynamicTextError(ValueError):
	pass


def _stringify_rendered_value(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, bool):
		return "true" if value else "false"
	return str(value)


def resolve_dynamic_text_value(ws: Any, context: dict[str, Any] | None, expression: str) -> Any:
	"""
	Resolve one dynamic text placeholder expression.

	This intentionally reuses the existing ref/value vocabulary and does not add
	script-like expressions.
	"""
	expr = str(expression or "").strip()
	if not expr:
		return None
	ctx = context if isinstance(context, dict) else {}
	if expr.startswith("param:"):
		params = ctx.get("parameters", {}) or {}
		if not isinstance(params, dict):
			return None
		path = expr[len("param:") :].strip()
		if not path:
			return None
		return resolve_path_value(params, path.split("."))
	if expr in {"self", "target", "event_entity"}:
		return resolve_entity_id(expr, ctx, allow_literal=False) or None
	if expr.startswith("event.") or expr.startswith("param.") or expr.startswith("self.") or expr.startswith("target.") or expr.startswith("event_entity."):
		value = resolve_value(ws, expr, ctx)
		return None if value == expr else value
	return None


def render_dynamic_text(ws: Any, context: dict[str, Any] | None, template: Any) -> str:
	text = str(template or "")
	if "{" not in text or "}" not in text:
		return text
	ctx = context if isinstance(context, dict) else {}

	def _replace(match: re.Match[str]) -> str:
		raw_expr = str(match.group(1) or "")
		value = resolve_dynamic_text_value(ws, ctx, raw_expr)
		if value is None:
			raise DynamicTextError(f"unresolved dynamic text placeholder: {{{raw_expr}}}")
		return _stringify_rendered_value(value)

	return PLACEHOLDER_RE.sub(_replace, text)


def render_dynamic_payload_text_fields(
	ws: Any,
	context: dict[str, Any] | None,
	payload: Any,
	text_keys: set[str] | frozenset[str] = PAYLOAD_TEXT_KEYS,
) -> dict[str, Any]:
	if not isinstance(payload, dict):
		return {}
	keys = {str(x) for x in set(text_keys or set()) if str(x)}

	def _render_node(node: Any, key: str = "") -> Any:
		if isinstance(node, dict):
			return {str(k): _render_node(v, str(k)) for k, v in node.items()}
		if isinstance(node, list):
			return [_render_node(v, key) for v in node]
		if isinstance(node, str) and key in keys:
			return render_dynamic_text(ws, context, node)
		return node

	return _render_node(payload)
