from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..effect_bundle import effect_bundle_from_raw
from ..execution_errors import KernFailure
from ..executor._effect_child_bundle import EVENT_CONTEXT_KEY
from ..effect_record import EVENT_ENVELOPE_KEY, build_runtime_event


@dataclass
class SettlementResult:
	events: list[dict[str, Any]] = field(default_factory=list)

	def __iter__(self):
		return iter(self.events)


@dataclass
class _QueuedEvent:
	event: dict[str, Any]
	context: dict[str, Any]
	reaction_depth: int


class WorldSettlement:
	"""Commit bundles, publish records, and run reactions in deterministic FIFO order."""

	def __init__(
		self,
		*,
		ws: Any,
		executor: Any,
		trigger_system: Any | None,
		max_reaction_depth: int,
	) -> None:
		self.ws = ws
		self.executor = executor
		self.trigger_system = trigger_system
		self.max_reaction_depth = max(0, int(max_reaction_depth))
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
			raise KernFailure(
				"INVALID_EFFECT_BUNDLE",
				str(exc),
				origin="settlement",
				phase="bundle_binding",
				context={"bundle": bundle_data},
			) from exc
		child_events: list[dict[str, Any]] = []
		self._bundle_event_frames.append(child_events)
		try:
			result_events = self.executor.execute_bundle(self.ws, bundle, context)
		finally:
			self._bundle_event_frames.pop()
		combined_events = [dict(event) for event in child_events + list(result_events or []) if isinstance(event, dict)]
		if self._bundle_event_frames:
			self._bundle_event_frames[-1].extend(combined_events)
		return combined_events

	def publish_event(self, event: dict[str, Any], context: dict[str, Any]) -> SettlementResult:
		return self._process_events([event], dict(context or {}), reaction_depth=0)

	def publish_events(self, events: list[dict[str, Any]], context: dict[str, Any] | None = None) -> SettlementResult:
		return self._process_events(list(events or []), dict(context or {}), reaction_depth=0)

	def _process_events(self, events: list[dict[str, Any]], context: dict[str, Any], reaction_depth: int) -> SettlementResult:
		result = SettlementResult()
		queue: deque[_QueuedEvent] = deque()
		for event in list(events or []):
			if isinstance(event, dict):
				self._publish_to_queue(queue, result, event, context, reaction_depth)

		while queue:
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
					raise KernFailure(
						"REACTION_DEPTH_EXCEEDED",
						"reaction depth exceeded",
						origin="reaction",
						phase="settlement",
						context={
							"reaction_rule_id": str(rctx.get("reaction_rule_id", "") or ""),
							"trigger_event_type": str(item.event.get("type", "") or ""),
							"reaction_depth": int(next_depth),
							"max_reaction_depth": int(self.max_reaction_depth),
						},
					)
				try:
					reaction_events = self._execute_bundle_events(request.get("bundle", {}) or {}, rctx)
				except KernFailure as exc:
					exc.add_context(
						reaction_rule_id=str(rctx.get("reaction_rule_id", "") or ""),
						trigger_event_type=str(item.event.get("type", "") or ""),
						reaction_depth=int(next_depth),
					)
					raise
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
		is_envelope = bool(clean.pop(EVENT_ENVELOPE_KEY, False))
		embedded_context = clean.get("context", {})
		if isinstance(child_context, dict):
			clean_context = dict(child_context)
		elif isinstance(embedded_context, dict) and embedded_context:
			clean_context = dict(embedded_context)
		else:
			clean_context = dict(context or {})
		if not is_envelope:
			event_type = str(clean.pop("type", "") or "")
			clean = build_runtime_event(event_type, clean, clean_context)
			clean.pop(EVENT_ENVELOPE_KEY, None)
		self._record_event(clean, clean_context, result)
		queue.append(_QueuedEvent(clean, clean_context, int(reaction_depth)))

	def _record_event(self, event: dict[str, Any], context: dict[str, Any], result: SettlementResult) -> None:
		clean = dict(event)
		result.events.append(clean)
		if hasattr(self.ws, "record_event"):
			self.ws.record_event(clean, context)
