from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..execution_errors import KernFailure
from .contracts import ActionFeedback, DecisionFrame
from .full_ws_view_builder import build_full_ws_view
from .memory_policy import build_memory_patch
from .observer import build_agent_perception
from .view_profile import active_workflow_view_profile


@dataclass(frozen=True)
class _PreparedDecisionFrame(DecisionFrame):
	_legacy_workflow_view: dict[str, Any] = field(default_factory=dict, repr=False)


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
	services = getattr(ws, "services", {}) or {}
	interaction_engine = services.get("interaction_engine")
	if interaction_engine is None or not hasattr(interaction_engine, "recipe_db"):
		return {}
	recipe_db = getattr(interaction_engine, "recipe_db", {}) or {}
	return dict(recipe_db) if isinstance(recipe_db, dict) else {}


def _execute_memory_patch(ws: Any, actor_id: str, patch: dict[str, Any]) -> None:
	execute = (getattr(ws, "services", {}) or {}).get("execute")
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
					"notes": [dict(item) for item in list(patch.get("notes", []) or []) if isinstance(item, dict)],
					"consume_interaction_ids": [
						str(item)
						for item in list(patch.get("consume_interaction_ids", []) or [])
						if str(item or "").strip()
					],
					"mid_term_summaries": [dict(item) for item in list(patch.get("mid_term_summaries", []) or []) if isinstance(item, dict)],
					"clear_mid_term_prep": bool(patch.get("clear_mid_term_prep", False)),
				}
			]
		},
		{"self_id": actor_id, "target_id": actor_id},
	)


def _normalized_memory_notes(ws: Any, actor_id: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	normalized: list[dict[str, Any]] = []
	for note in [dict(item) for item in list((meta or {}).get("memory_notes", []) or []) if isinstance(item, dict)]:
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
class DecisionContextBuilder:
	"""Build one post-settlement, agent-visible workflow frame."""

	def build(
		self,
		ws: Any,
		actor_id: str,
		reason: str,
		mode_context: dict[str, Any],
		*,
		previous_action: ActionFeedback | None,
		actions_committed: int,
		replans: int,
	) -> DecisionFrame:
		workflow_view = _build_workflow_view(ws, actor_id, reason, mode_context)
		full_view = dict(workflow_view.get("full_ws_view", {}) or {})
		recent_interactions = [
			dict(item)
			for item in list(full_view.get("interaction_inbox", []) or [])
			if isinstance(item, dict)
		]
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
			workflow_view = _build_workflow_view(ws, actor_id, reason, mode_context)
			full_view = dict(workflow_view.get("full_ws_view", {}) or {})
		full_view["recent_interactions"] = recent_interactions
		workflow_view["full_ws_view"] = full_view
		return _PreparedDecisionFrame(
			actor_id=str(actor_id),
			reason=str(reason or ""),
			mode_context=dict(mode_context or {}),
			perception=build_agent_perception(full_view, str(actor_id)),
			action_catalog=_workflow_action_catalog(ws),
			previous_action=previous_action,
			actions_committed=int(actions_committed),
			replans=int(replans),
			_legacy_workflow_view=workflow_view,
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
				"mid_term_summaries": [],
				"clear_mid_term_prep": False,
			},
		)


__all__ = ["DecisionContextBuilder"]
