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

TASK_INTERRUPT_MODE_ALIAS = {
	"pausable": INTERRUPT_MODE_PAUSE_KEEP,
	"restartable": INTERRUPT_MODE_PAUSE_RESET,
	"cancellable": INTERRUPT_MODE_CANCEL,
	"fail_on_interrupt": INTERRUPT_MODE_FAIL,
}


def normalize_task_policy(raw_policy: Any) -> dict[str, Any]:
	policy = dict(raw_policy) if isinstance(raw_policy, dict) else {}
	mode = str(policy.get("interrupt_mode", INTERRUPT_MODE_PAUSE_KEEP) or "").strip().lower()
	mode = TASK_INTERRUPT_MODE_ALIAS.get(mode, mode)
	if mode not in TASK_INTERRUPT_MODES:
		mode = INTERRUPT_MODE_PAUSE_KEEP
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
	process = recipe_data.get("process", {}) or {}
	if not isinstance(process, dict):
		process = {}
	policy = process.get("task_policy", None)
	if policy is None:
		policy = recipe_data.get("task_policy", None)
	return normalize_task_policy(policy if isinstance(policy, dict) else {})


def is_interrupt_mode_resumable(interrupt_mode: str) -> bool:
	mode = str(interrupt_mode or INTERRUPT_MODE_PAUSE_KEEP).strip().lower()
	return mode not in {INTERRUPT_MODE_CANCEL, INTERRUPT_MODE_FAIL}

