from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .runtime import (
	_apply_operations,
	commit_workflow_decision,
	decide_from_prepared_workflow,
	prepare_workflow_decision_input,
	run_social_activity_cycle,
)


SERIAL_MODE = "serial"
PARALLEL_DECIDE_SERIAL_COMMIT_MODE = "parallel_decide_serial_commit"


def normalize_decision_mode(value: Any) -> str:
	mode = str(value or SERIAL_MODE).strip().lower()
	if mode in {SERIAL_MODE, PARALLEL_DECIDE_SERIAL_COMMIT_MODE}:
		return mode
	return SERIAL_MODE


def _apply_social_outcome(ws: Any, actor_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
	otype = str((outcome or {}).get("type", "") or "")
	if otype == "apply_operations":
		stop_loop, consumed = _apply_operations(ws, actor_id, list((outcome or {}).get("operations", []) or []))
		return {
			"type": "applied" if consumed else "noop",
			"consumed": bool(consumed),
			"stop_loop": bool(stop_loop),
		}
	return dict(outcome or {"type": "noop"})


def _run_parallel_decide_serial_commit(ws: Any, items: list[dict[str, Any]], max_decision_workers: int) -> list[dict[str, Any]]:
	prepared_by_index: dict[int, dict[str, Any]] = {}
	outcomes: list[dict[str, Any] | None] = [None for _ in items]
	for idx, item in enumerate(items):
		actor_id = str(item.get("actor_id", "") or "")
		prepared = prepare_workflow_decision_input(
			ws,
			actor_id,
			item.get("workflow"),
			str(item.get("reason", "") or ""),
			dict(item.get("mode_context", {}) or {}),
		)
		if str(prepared.get("status", "") or "") != "ready":
			outcomes[idx] = dict(prepared.get("outcome", {"type": "noop"}) or {"type": "noop"})
			continue
		prepared_by_index[idx] = prepared

	decisions_by_index: dict[int, dict[str, Any]] = {}
	worker_count = max(1, int(max_decision_workers or 1))
	if prepared_by_index:
		with ThreadPoolExecutor(max_workers=worker_count) as pool:
			future_to_index = {pool.submit(decide_from_prepared_workflow, prepared): idx for idx, prepared in prepared_by_index.items()}
			for future in as_completed(future_to_index):
				idx = int(future_to_index[future])
				try:
					decisions_by_index[idx] = dict(future.result() or {})
				except Exception as exc:
					actor_id = str(items[idx].get("actor_id", "") or "")
					decisions_by_index[idx] = {"status": "exception", "actor_id": actor_id, "error": str(exc)}

	for idx, item in enumerate(items):
		if outcomes[idx] is not None:
			continue
		actor_id = str(item.get("actor_id", "") or "")
		decision = decisions_by_index.get(idx, {})
		outcome = commit_workflow_decision(
			ws,
			actor_id,
			str(item.get("reason", "") or ""),
			decision.get("decision_raw"),
			max_commands=max(0, int(item.get("max_actions", 1) or 1)),
			decide_error=str(decision.get("error", "") or "") if str(decision.get("status", "") or "") != "ok" else "",
		)
		outcomes[idx] = _apply_social_outcome(ws, actor_id, outcome)
	return [dict(outcome or {"type": "noop"}) for outcome in outcomes]


def run_social_activity_batch(
	ws: Any,
	items: list[dict[str, Any]],
	*,
	decision_mode: str = SERIAL_MODE,
	max_decision_workers: int = 1,
) -> list[dict[str, Any]]:
	mode = normalize_decision_mode(decision_mode)
	normalized_items = [dict(item) for item in list(items or []) if isinstance(item, dict)]
	if mode == PARALLEL_DECIDE_SERIAL_COMMIT_MODE:
		return _run_parallel_decide_serial_commit(ws, normalized_items, max_decision_workers)
	outcomes: list[dict[str, Any]] = []
	for item in normalized_items:
		outcomes.append(
			run_social_activity_cycle(
				ws,
				str(item.get("actor_id", "") or ""),
				item.get("workflow"),
				reason=str(item.get("reason", "") or ""),
				mode_context=dict(item.get("mode_context", {}) or {}),
				max_actions=max(0, int(item.get("max_actions", 1) or 1)),
			)
		)
	return outcomes

