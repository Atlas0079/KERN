from __future__ import annotations

from typing import Any

INTERRUPT_MODE_FORBIDDEN = "forbidden"
INTERRUPT_MODE_PAUSE_KEEP = "pause_keep_progress"
INTERRUPT_MODE_PAUSE_RESET = "pause_reset_progress"
INTERRUPT_MODE_CANCEL = "cancel"
INTERRUPT_MODE_FAIL = "fail"

TASK_INTERRUPT_MODES = frozenset(
	{
		INTERRUPT_MODE_FORBIDDEN,
		INTERRUPT_MODE_PAUSE_KEEP,
		INTERRUPT_MODE_PAUSE_RESET,
		INTERRUPT_MODE_CANCEL,
		INTERRUPT_MODE_FAIL,
	}
)

DEFAULT_TASK_POLICY = {
	"interrupt_mode": INTERRUPT_MODE_PAUSE_KEEP,
	"allow_voluntary_interrupt": True,
	"allow_voluntary_cancel": True,
}


def normalize_task_policy(raw_policy: Any) -> dict[str, Any]:
	if raw_policy is None:
		return dict(DEFAULT_TASK_POLICY)
	if not isinstance(raw_policy, dict):
		raise ValueError("task_policy must be object")
	policy = dict(raw_policy)
	mode = str(policy.get("interrupt_mode", INTERRUPT_MODE_PAUSE_KEEP) or "").strip().lower()
	if mode not in TASK_INTERRUPT_MODES:
		raise ValueError(f"task_policy.interrupt_mode invalid: {mode}")
	return {
		"interrupt_mode": mode,
		"allow_voluntary_interrupt": bool(policy.get("allow_voluntary_interrupt", True)),
		"allow_voluntary_cancel": bool(policy.get("allow_voluntary_cancel", True)),
	}


def get_task_policy_from_task(task: Any) -> dict[str, Any]:
	params = getattr(task, "parameters", {}) or {}
	if not isinstance(params, dict):
		params = {}
	raw_policy = params.get("task_policy", {}) or {}
	return normalize_task_policy(raw_policy)


def extract_task_policy_from_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
	recipe_data = dict(recipe or {}) if isinstance(recipe, dict) else {}
	if "task_policy" in recipe_data:
		raise ValueError("recipe.task_policy is removed; use recipe.process.task_policy")
	process = recipe_data.get("process", {}) or {}
	if not isinstance(process, dict):
		process = {}
	policy = process.get("task_policy", None)
	if policy is not None and not isinstance(policy, dict):
		raise ValueError("recipe.process.task_policy must be object")
	return normalize_task_policy(policy)


def is_interrupt_mode_resumable(interrupt_mode: str) -> bool:
	mode = str(interrupt_mode or INTERRUPT_MODE_PAUSE_KEEP).strip().lower()
	return mode not in {INTERRUPT_MODE_CANCEL, INTERRUPT_MODE_FAIL}
