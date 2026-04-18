from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WORKFLOW_DECISION_TYPES = frozenset({"apply_commands", "noop", "error"})
WORKFLOW_ERROR_KINDS = frozenset({"temporary", "business", "contract"})


@dataclass
class WorkflowDecisionError:
	kind: str
	code: str
	message: str

	def to_dict(self) -> dict[str, str]:
		return {
			"kind": str(self.kind or ""),
			"code": str(self.code or ""),
			"message": str(self.message or ""),
		}


def build_noop_decision(meta: dict[str, Any] | None = None) -> dict[str, Any]:
	return {
		"type": "noop",
		"meta": dict(meta or {}),
	}


def build_error_decision(kind: str, code: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
	return {
		"type": "error",
		"error": WorkflowDecisionError(kind=str(kind or ""), code=str(code or ""), message=str(message or "")).to_dict(),
		"meta": dict(meta or {}),
	}


def build_apply_commands_decision(commands: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
	out_cmds: list[dict[str, Any]] = []
	for item in list(commands or []):
		if isinstance(item, dict):
			out_cmds.append(dict(item))
	return {"type": "apply_commands", "commands": out_cmds, "meta": dict(meta or {})}


def validate_workflow_decision(raw: Any) -> tuple[dict[str, Any] | None, str]:
	if not isinstance(raw, dict):
		return None, "decision must be object"
	d = dict(raw)
	dtype = str(d.get("type", "") or "").strip()
	if dtype not in WORKFLOW_DECISION_TYPES:
		return None, "decision.type must be apply_commands/noop/error"
	if dtype == "noop":
		return {"type": "noop", "meta": dict(d.get("meta", {}) or {})}, ""
	if dtype == "error":
		err = d.get("error", {}) or {}
		if not isinstance(err, dict):
			return None, "decision.error must be object when type=error"
		kind = str(err.get("kind", "") or "").strip()
		code = str(err.get("code", "") or "").strip()
		message = str(err.get("message", "") or "").strip()
		if kind not in WORKFLOW_ERROR_KINDS:
			return None, "decision.error.kind must be temporary/business/contract"
		if not code:
			return None, "decision.error.code is required"
		return {
			"type": "error",
			"error": {"kind": kind, "code": code, "message": message},
			"meta": dict(d.get("meta", {}) or {}),
		}, ""
	if dtype == "apply_commands":
		commands = d.get("commands", []) or []
		if not isinstance(commands, list):
			return None, "decision.commands must be list when type=apply_commands"
		out_cmds: list[dict[str, Any]] = []
		for idx, item in enumerate(commands):
			if not isinstance(item, dict):
				return None, f"decision.commands[{idx}] must be object"
			verb = str(item.get("verb", "") or "").strip()
			if not verb:
				return None, f"decision.commands[{idx}].verb is required"
			params = item.get("parameters", {}) or {}
			if not isinstance(params, dict):
				return None, f"decision.commands[{idx}].parameters must be object"
			out = dict(item)
			out["verb"] = verb
			out["parameters"] = dict(params)
			out_cmds.append(out)
		return {"type": "apply_commands", "commands": out_cmds, "meta": dict(d.get("meta", {}) or {})}, ""
	return None, "unsupported decision type"
