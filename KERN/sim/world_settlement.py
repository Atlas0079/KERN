from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..effect_bundle import effect_bundle_from_raw
from ..execution_errors import executor_error, is_execution_error_event
from ..executor._effect_child_bundle import EVENT_CONTEXT_KEY


@dataclass
class SettlementResult:
	events: list[dict[str, Any]] = field(default_factory=list)
	fatal_error: dict[str, Any] | None = None

	def __iter__(self):
		return iter(self.events)


@dataclass
class _QueuedEvent:
	event: dict[str, Any]
	context: dict[str, Any]
	reaction_depth: int


class WorldSettlement:
	"""Commit bundles, publish events, and run reactions in deterministic FIFO order."""

	def __init__(
		self,
		*,
		ws: Any,
		executor: Any,
		trigger_system: Any | None,
		max_reaction_depth: int,
		on_fatal: Callable[[dict[str, Any]], None] | None = None,
	) -> None:
		self.ws = ws
		self.executor = executor
		self.trigger_system = trigger_system
		self.max_reaction_depth = max(0, int(max_reaction_depth))
		self.on_fatal = on_fatal
		self._bundle_event_frames: list[list[dict[str, Any]]] = []

	def execute_bundle(self, bundle_data: Any, context: dict[str, Any]) -> SettlementResult:
		is_nested_execution = bool(self._bundle_event_frames)
		result_events = self._execute_bundle_events(bundle_data, context)
		if is_nested_execution:
			return SettlementResult(events=[dict(event) for event in result_events if isinstance(event, dict)])
		return self._process_events(result_events, dict(context or {}), reaction_depth=0)

	def _execute_bundle_events(self, bundle_data: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			bundle = effect_bundle_from_raw(bundle_data)
		except Exception as exc:
			return executor_error(f"invalid bundle ({exc})")
		child_events: list[dict[str, Any]] = []
		self._bundle_event_frames.append(child_events)
		try:
			result_events = self.executor.execute_bundle(self.ws, bundle, context)
		finally:
			self._bundle_event_frames.pop()
		error = next((event for event in list(result_events or []) if is_execution_error_event(event)), None)
		if error is not None:
			return [dict(event) for event in list(result_events or []) if isinstance(event, dict)]
		combined_events = [dict(event) for event in child_events + list(result_events or []) if isinstance(event, dict)]
		if self._bundle_event_frames:
			self._bundle_event_frames[-1].extend(combined_events)
		return combined_events

	def publish_event(self, event: dict[str, Any], context: dict[str, Any]) -> SettlementResult:
		return self._process_events([event], dict(context or {}), reaction_depth=0)

	def _process_events(self, events: list[dict[str, Any]], context: dict[str, Any], reaction_depth: int) -> SettlementResult:
		result = SettlementResult()
		queue: deque[_QueuedEvent] = deque()
		for event in list(events or []):
			if isinstance(event, dict):
				self._publish_to_queue(queue, result, event, context, reaction_depth)

		while queue and result.fatal_error is None:
			if bool(getattr(getattr(self.ws, "runtime_state", None), "abort_requested", False)):
				break
			item = queue.popleft()
			if self.trigger_system is None:
				continue
			requests = self.trigger_system.build_reaction_effects(self.ws, item.event, item.context)
			for request in list(requests or []):
				next_depth = int(item.reaction_depth) + 1
				rctx = dict(request.get("context", {}) or {})
				if next_depth > self.max_reaction_depth:
					fatal = self._depth_error(item, request, next_depth)
					self._record_event(fatal, item.context, result)
					self._record_reaction_attempt(rctx, False, fatal)
					self._set_fatal(result, fatal)
					break
				self._record_reaction_triggered(rctx)
				reaction_events = self._execute_bundle_events(request.get("bundle", {}) or {}, rctx)
				error = next((dict(ev) for ev in reaction_events if is_execution_error_event(ev)), None)
				if error is not None:
					self._record_event(error, rctx, result)
					fatal = self._reaction_error(item, rctx, next_depth, error)
					self._record_event(fatal, rctx, result)
					self._record_reaction_attempt(rctx, False, error)
					self._set_fatal(result, fatal)
					break
				self._record_reaction_attempt(rctx, True, None)
				for reaction_event in list(reaction_events or []):
					if isinstance(reaction_event, dict):
						self._publish_to_queue(queue, result, reaction_event, rctx, next_depth)
		return result

	def _publish_to_queue(
		self,
		queue: deque[_QueuedEvent],
		result: SettlementResult,
		event: dict[str, Any],
		context: dict[str, Any],
		reaction_depth: int,
	) -> None:
		clean = dict(event)
		child_context = clean.pop(EVENT_CONTEXT_KEY, None)
		clean_context = dict(child_context) if isinstance(child_context, dict) else dict(context or {})
		self._record_event(clean, clean_context, result)
		queue.append(_QueuedEvent(clean, clean_context, int(reaction_depth)))

	def _record_event(self, event: dict[str, Any], context: dict[str, Any], result: SettlementResult) -> None:
		clean = dict(event)
		result.events.append(clean)
		if hasattr(self.ws, "record_event"):
			self.ws.record_event(clean, context)

	def _record_reaction_attempt(self, context: dict[str, Any], success: bool, error: dict[str, Any] | None) -> None:
		rule_id = str(context.get("reaction_rule_id", "") or "")
		if not rule_id or not hasattr(self.ws, "record_interaction_attempt"):
			return
		self.ws.record_interaction_attempt(
			actor_id=str(context.get("self_id", "") or ""),
			verb=f"ReactionApplied:{rule_id}",
			target_id=str(context.get("target_id", "") or ""),
			status="success" if success else "failed",
			reason="" if success else str((error or {}).get("message", "") or ""),
			recipe_id=f"reaction_applied:{rule_id}",
			extra={
				"is_reaction": True,
				"reaction_phase": "applied" if success else "failed",
				"reaction_rule_id": rule_id,
				"trigger_event": str(context.get("reaction_trigger_event_type", "") or ""),
			},
		)

	def _record_reaction_triggered(self, context: dict[str, Any]) -> None:
		rule_id = str(context.get("reaction_rule_id", "") or "")
		if not hasattr(self.ws, "record_interaction_attempt"):
			return
		verb = str(context.get("reaction_verb", "") or "").strip()
		if not verb:
			verb = f"ReactionTriggered:{rule_id}" if rule_id else "ReactionTriggered"
		self.ws.record_interaction_attempt(
			actor_id=str(context.get("self_id", "") or ""),
			verb=verb,
			target_id=str(context.get("target_id", "") or ""),
			status="success",
			reason="",
			recipe_id=f"reaction_triggered:{rule_id}" if rule_id else "reaction_triggered",
			extra={
				"is_reaction": True,
				"reaction_phase": "triggered",
				"reaction_rule_id": rule_id,
				"trigger_event": str(context.get("reaction_trigger_event_type", "") or ""),
			},
		)

	def _reaction_error(self, item: _QueuedEvent, context: dict[str, Any], depth: int, error: dict[str, Any]) -> dict[str, Any]:
		return {
			"type": "ReactionFailed",
			"reaction_rule_id": str(context.get("reaction_rule_id", "") or ""),
			"trigger_event_type": str(item.event.get("type", "") or ""),
			"reaction_depth": int(depth),
			"error": dict(error),
		}

	def _depth_error(self, item: _QueuedEvent, request: dict[str, Any], depth: int) -> dict[str, Any]:
		context = dict(request.get("context", {}) or {})
		return {
			"type": "ReactionDepthExceeded",
			"reaction_rule_id": str(context.get("reaction_rule_id", "") or ""),
			"trigger_event_type": str(item.event.get("type", "") or ""),
			"reaction_depth": int(depth),
			"max_reaction_depth": int(self.max_reaction_depth),
		}

	def _set_fatal(self, result: SettlementResult, fatal: dict[str, Any]) -> None:
		result.fatal_error = dict(fatal)
		if callable(self.on_fatal):
			self.on_fatal(dict(fatal))
