from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..execution_errors import KernFailure
from .full_ws_view_builder import build_full_ws_view
from .memory_policy import build_memory_patch
from .observer import build_agent_perception
from .view_profile import active_workflow_view_profile


@dataclass(frozen=True)
class LLMDecisionContext:
	perception: dict[str, Any]
	action_catalog: dict[str, Any]


def _build_workflow_view(ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any]) -> dict[str, Any]:
	profile = active_workflow_view_profile(ws=ws, mode_context=mode_context, full_ws_view={})
	full_view = build_full_ws_view(ws, actor_id, reason, mode_context)
	full_view["workflow_view_profile"] = dict(profile)
	return {
		"full_ws_view": full_view,
		"interrupt_reason": str(reason or ""),
		"mode_context": dict(mode_context or {}),
		"workflow_view_profile": dict(profile),
	}


def _workflow_action_catalog(ws: Any) -> dict[str, Any]:
	interaction_engine = ws.services["interaction_engine"]
	return dict(interaction_engine.recipe_db)


def _execute_memory_patch(ws: Any, actor_id: str, patch: dict[str, Any]) -> None:
	execute = ws.services["execute"]
	if not callable(execute):
		raise KernFailure(
			"WORKFLOW_MEMORY_PATCH_APPLY_FAILED",
			"workflow memory patch executor is unavailable",
			origin="workflow",
			phase="memory_patch",
			context={"actor_id": str(actor_id or "")},
		)
	execute(
		{
			"effects": [
				{
					"effect": "ApplyMemoryPatch",
					"target": actor_id,
					"notes": [dict(item) for item in patch.get("notes", [])],
					"consume_interaction_ids": [str(item) for item in patch.get("consume_interaction_ids", [])],
					"consume_record_ids": [str(item) for item in patch.get("consume_record_ids", [])],
					"remove_short_term_record_ids": [str(item) for item in patch.get("remove_short_term_record_ids", [])],
					"mid_term_summaries": [dict(item) for item in patch.get("mid_term_summaries", [])],
					"clear_mid_term_prep": bool(patch.get("clear_mid_term_prep", False)),
				}
			]
		},
		{"self_id": actor_id, "target_id": actor_id},
	)


def apply_record_memory_patch(
	ws: Any,
	actor_id: str,
	reason: str,
	mode_context: dict[str, Any],
) -> bool:
	"""Consume visible record inbox entries into the actor's MemoryComponent."""

	workflow_view = _build_workflow_view(ws, actor_id, reason, mode_context)
	full_view = dict(workflow_view.get("full_ws_view", {}) or {})
	try:
		memory_patch = build_memory_patch(full_ws_view=full_view, actor_id=str(actor_id))
	except Exception as exc:
		raise KernFailure(
			"WORKFLOW_MEMORY_PATCH_BUILD_FAILED",
			str(exc),
			origin="workflow",
			phase="memory_patch",
			context={"actor_id": str(actor_id or "")},
		) from exc
	if isinstance(memory_patch, dict) and memory_patch:
		_execute_memory_patch(ws, actor_id, memory_patch)
		return True
	return False


apply_interaction_memory_patch = apply_record_memory_patch


def _normalized_memory_notes(ws: Any, actor_id: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
	tick = int(ws.game_time.total_ticks)
	normalized: list[dict[str, Any]] = []
	for note in [dict(item) for item in meta.get("memory_notes", [])]:
		content = str(note.get("content", note.get("text", "")) or "").strip()
		if not content:
			continue
		out = dict(note)
		out["content"] = content
		out.setdefault("tick", tick)
		out.setdefault("type", "note")
		out.setdefault("topic", "grounding")
		out.setdefault("importance", 0.8)
		out.setdefault("actor_id", actor_id)
		out.setdefault("tags", ["grounding", "ungroundable"])
		normalized.append(out)
	return normalized


@dataclass
class LLMDecisionContextBuilder:
	"""Build the default LLM workflow's private, agent-visible decision input."""

	def build(
		self,
		ws: Any,
		actor_id: str,
		reason: str,
		mode_context: dict[str, Any],
	) -> LLMDecisionContext:
		workflow_view = _build_workflow_view(ws, actor_id, reason, mode_context)
		full_view = dict(workflow_view.get("full_ws_view", {}) or {})
		recent_records = [
			dict(item)
			for item in list(full_view.get("record_inbox", []) or [])
			if isinstance(item, dict)
		]
		if apply_record_memory_patch(ws, actor_id, reason, mode_context):
			workflow_view = _build_workflow_view(ws, actor_id, reason, mode_context)
			full_view = dict(workflow_view.get("full_ws_view", {}) or {})
		full_view["recent_records"] = recent_records
		full_view["recent_interactions"] = []
		workflow_view["full_ws_view"] = full_view
		return LLMDecisionContext(
			perception=build_agent_perception(full_view, str(actor_id)),
			action_catalog=_workflow_action_catalog(ws),
		)

	@staticmethod
	def apply_step_meta(ws: Any, actor_id: str, meta: dict[str, Any]) -> None:
		notes = _normalized_memory_notes(ws, actor_id, dict(meta or {}))
		if not notes:
			return
		_execute_memory_patch(
			ws,
			actor_id,
			{
				"notes": notes,
				"consume_interaction_ids": [],
				"consume_record_ids": [],
				"remove_short_term_record_ids": [],
				"mid_term_summaries": [],
				"clear_mid_term_prep": False,
			},
		)


__all__ = ["LLMDecisionContext", "LLMDecisionContextBuilder", "apply_record_memory_patch"]
