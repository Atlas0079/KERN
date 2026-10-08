from __future__ import annotations

from typing import Any

from KERN.agent_workflow.context_builder import _execute_memory_patch
from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.memory_policy import build_memory_patch
from KERN.execution_errors import KernFailure


_EXPERIENCE_TYPES = {
    "social_propagation:RefreshFeed": ("social_feed_view", 0.65),
    "social_propagation:RepostVisiblePost": ("social_action", 0.8),
    "social_propagation:LikeVisiblePost": ("social_action", 0.8),
    "social_propagation:CommentOnVisiblePost": ("social_action", 0.8),
}


def apply_record_memory_patch(
    ws: Any, actor_id: str, reason: str, mode_context: dict[str, Any],
) -> bool:
    """Categorize perceived experiences using this experiment's memory policy."""
    view = build_full_ws_view(ws, actor_id, reason, mode_context)
    try:
        patch = build_memory_patch(view, actor_id)
        if not patch:
            return False
        for note in patch["notes"]:
            source_effect = note["source"]["source_effect"]
            if source_effect in _EXPERIENCE_TYPES:
                record_type, importance = _EXPERIENCE_TYPES[source_effect]
                note.update(record_type=record_type, topic=record_type, importance=importance)
    except Exception as exc:
        raise KernFailure(
            "WORKFLOW_MEMORY_PATCH_BUILD_FAILED", str(exc),
            origin="workflow", phase="memory_patch", context={"actor_id": actor_id},
        ) from exc
    _execute_memory_patch(ws, actor_id, patch)
    return True
