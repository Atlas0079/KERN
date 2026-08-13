from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from uuid import uuid4

from KERN.agent_workflow.context_builder import apply_record_memory_patch
from KERN.agent_workflow.contracts import AgentTurnSession, EndTurn, SubmitAction, TurnFrame, TurnStart
from KERN.execution_errors import ERROR_KIND_CONTRACT, ERROR_KIND_INFRASTRUCTURE, KernFailure


_BIG_FIVE_FIELDS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
_PUBLIC_CARD_FIELDS = (
	"post_id",
	"text",
	"display_hashtags",
	"original_author_id",
	"feed_item_kind",
	"reposted_by_account_id",
	"created_tick",
	"reposted_tick",
	"section",
	"position",
	"like_count",
	"comment_count",
	"repost_count",
	"viewer_has_liked",
	"viewer_has_reposted",
)
_PAGE_DECISION_EMPTY_RESPONSE_MAX_ATTEMPTS = 3


def _parse_page_decision_output(response_text: str) -> dict[str, Any]:
	def _try_load_object(candidate: str) -> dict[str, Any] | None:
		text = str(candidate or "").strip()
		if not text:
			return None
		try:
			loaded = json.loads(text)
		except json.JSONDecodeError:
			return None
		if not isinstance(loaded, dict):
			raise ValueError("social workflow response JSON must be an object")
		return loaded

	def _code_fence_bodies(text: str) -> list[str]:
		out: list[str] = []
		for match in re.finditer(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n([\s\S]*?)\r?\n?[ \t]*```", text):
			body = str(match.group(1) or "").strip()
			if body:
				out.append(body)
		return out

	def _balanced_span_from(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
		if start < 0 or start >= len(text) or text[start] != open_ch:
			return None
		depth = 1
		in_str = False
		escape = False
		j = start + 1
		while j < len(text):
			ch = text[j]
			if in_str:
				if escape:
					escape = False
				elif ch == "\\":
					escape = True
				elif ch == '"':
					in_str = False
				j += 1
				continue
			if ch == '"':
				in_str = True
			elif ch == open_ch:
				depth += 1
			elif ch == close_ch:
				depth -= 1
				if depth == 0:
					return text[start : j + 1]
			j += 1
		return None

	def _balanced_object_spans(text: str) -> list[str]:
		out: list[str] = []
		n = len(text)
		i = 0
		while i < n:
			if text[i] != "{":
				i += 1
				continue
			span = _balanced_span_from(text, i, "{", "}")
			if span is not None:
				out.append(span)
			i += 1
		return out

	def _field_value_start(text: str, field_name: str) -> int:
		match = re.search(rf'"{re.escape(field_name)}"\s*:\s*', text)
		return int(match.end()) if match else -1

	def _decode_loose_json_string(value: str) -> str:
		out: list[str] = []
		escape = False
		for ch in str(value):
			if ch == '"' and not escape:
				out.append(r"\"")
			else:
				out.append(ch)
			if escape:
				escape = False
			elif ch == "\\":
				escape = True
		try:
			return str(json.loads('"' + "".join(out) + '"'))
		except json.JSONDecodeError:
			return str(value)

	def _loose_string_field(text: str, field_name: str) -> str | None:
		start = _field_value_start(text, field_name)
		if start < 0 or start >= len(text) or text[start] != '"':
			return None
		i = start + 1
		escape = False
		while i < len(text):
			ch = text[i]
			if escape:
				escape = False
				i += 1
				continue
			if ch == "\\":
				escape = True
				i += 1
				continue
			if ch == '"':
				j = i + 1
				while j < len(text) and text[j] in " \t\r\n":
					j += 1
				if j >= len(text) or text[j] in ",}]":
					return _decode_loose_json_string(text[start + 1 : i])
			i += 1
		return None

	def _loose_contract_object(text: str) -> dict[str, Any] | None:
		actions_start = _field_value_start(text, "actions")
		if actions_start < 0 or actions_start >= len(text) or text[actions_start] != "[":
			return None
		actions_span = _balanced_span_from(text, actions_start, "[", "]")
		if actions_span is None:
			return None
		try:
			actions = json.loads(actions_span)
		except json.JSONDecodeError:
			return None
		summary = _loose_string_field(text, "decision_summary")
		if summary is None:
			return None
		return {"actions": actions, "decision_summary": summary}

	raw = str(response_text or "").strip()
	fenced = _code_fence_bodies(raw)
	candidates: list[str] = [raw, *fenced]
	seen: set[str] = set()
	for candidate in candidates:
		text = str(candidate or "").strip()
		if not text or text in seen:
			continue
		seen.add(text)
		loaded = _try_load_object(text)
		if loaded is not None:
			return loaded
		loose = _loose_contract_object(text)
		if loose is not None:
			return loose
	for candidate in _balanced_object_spans(raw):
		text = str(candidate or "").strip()
		if not text or text in seen:
			continue
		seen.add(text)
		loaded = _try_load_object(text)
		if loaded is not None:
			return loaded
	excerpt = raw if len(raw) <= 1200 else raw[:1200] + "...<truncated>"
	raise ValueError(f"social workflow response does not contain a valid JSON object: {excerpt}")


class SocialActivationSchedule(Protocol):
	def is_active(self, actor_id: str, tick: int) -> bool:
		...


class SocialDecisionClient(Protocol):
	def chat_text(
		self,
		*,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> str:
		...


@dataclass(frozen=True)
class ActorPlatformBinding:
	terminal_id: str
	account_id: str
	runtime_id: str = "social_platform"

	def __post_init__(self) -> None:
		for label, value in (
			("terminal_id", self.terminal_id),
			("account_id", self.account_id),
			("runtime_id", self.runtime_id),
		):
			if not str(value or "").strip() or str(value) != str(value).strip():
				raise ValueError(f"social actor binding {label} must be a non-blank trimmed string")


@dataclass
class _PreparedSocialPageDecision:
	workflow: "SocialPlatformWorkflow"
	start: TurnStart
	binding: ActorPlatformBinding
	card_by_id: dict[str, dict[str, Any]]
	messages: list[dict[str, Any]]
	trace: dict[str, Any]

	def run(self) -> str:
		return self.workflow._request_page_decision_with_trace(self.trace, self.start, self.messages)

	def complete(self, response_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
		return self.workflow.complete_page_decision(
			response_text,
			trace=self.trace,
			card_by_id=self.card_by_id,
			start=self.start,
			binding=self.binding,
		)


@dataclass
class _PreparedSocialSessionStep:
	session: "_ActiveSocialTurnSession"
	decision: _PreparedSocialPageDecision

	def run(self) -> str:
		return self.decision.run()

	def complete(self, response_text: str):
		actions, meta = self.decision.complete(response_text)
		self.session.decision_meta = dict(meta)
		if actions:
			self.session.phase = "awaiting_action"
			return SubmitAction(intent=actions[0], meta=dict(self.session.decision_meta))
		self.session.phase = "done"
		return EndTurn(meta=dict(self.session.decision_meta))


@dataclass
class SocialPlatformWorkflow:
	"""One-page social-platform decision workflow using the existing duck-typed contract."""

	activation_schedule: SocialActivationSchedule
	actor_bindings: Mapping[str, ActorPlatformBinding]
	client: SocialDecisionClient
	model: str
	experimental_post_id: str
	temperature: float = 0.2
	max_tokens: int = 1200
	consolidation_max_tokens: int = 900
	consolidation_trigger_entries: int = 40
	consolidation_keep_recent_entries: int = 10
	request_extra: dict[str, Any] = field(default_factory=dict)
	trace_recorder: Any | None = None
	max_memory_items: int = 20
	workflow_id: str = "social_platform"
	identity_component_id: str = "sea_level_social_experiment:SocialIdentityComponent"

	def __post_init__(self) -> None:
		self.model = self._trimmed(self.model, "model")
		self.experimental_post_id = self._trimmed(self.experimental_post_id, "experimental_post_id")
		self.workflow_id = self._trimmed(self.workflow_id, "workflow_id")
		self.identity_component_id = self._trimmed(self.identity_component_id, "identity_component_id")
		if self.activation_schedule is None or not callable(getattr(self.activation_schedule, "is_active", None)):
			raise ValueError("social workflow activation_schedule must implement is_active(actor_id, tick)")
		if self.client is None or not callable(getattr(self.client, "chat_text", None)):
			raise ValueError("social workflow client must implement chat_text()")
		if not 0.0 <= float(self.temperature) <= 2.0:
			raise ValueError("social workflow temperature must be between 0 and 2")
		if int(self.max_tokens) <= 0:
			raise ValueError("social workflow max_tokens must be positive")
		if int(self.consolidation_max_tokens) <= 0:
			raise ValueError("social workflow consolidation_max_tokens must be positive")
		if int(self.consolidation_trigger_entries) <= 0:
			raise ValueError("social workflow consolidation_trigger_entries must be positive")
		if int(self.consolidation_keep_recent_entries) < 0:
			raise ValueError("social workflow consolidation_keep_recent_entries must be non-negative")
		if int(self.consolidation_keep_recent_entries) >= int(self.consolidation_trigger_entries):
			raise ValueError("social workflow consolidation_keep_recent_entries must be smaller than consolidation_trigger_entries")
		if int(self.max_memory_items) < 0:
			raise ValueError("social workflow max_memory_items must be non-negative")
		bindings = dict(self.actor_bindings)
		if not bindings:
			raise ValueError("social workflow actor_bindings must not be empty")
		for actor_id, binding in bindings.items():
			self._trimmed(actor_id, "actor_id")
			if not isinstance(binding, ActorPlatformBinding):
				raise ValueError(f"social workflow binding must be ActorPlatformBinding: {actor_id}")
		self.actor_bindings = bindings
		self.request_extra = dict(self.request_extra)

	def consolidate_memory_if_needed(self, ws: Any, start: TurnStart) -> bool:
		actor = ws.get_entity_by_id(start.actor_id) if hasattr(ws, "get_entity_by_id") else None
		memory_component = actor.get_component("MemoryComponent") if actor is not None and hasattr(actor, "get_component") else None
		if memory_component is None:
			return False
		short_items = [dict(item) for item in list(getattr(memory_component, "short_term_queue", []) or []) if isinstance(item, dict)]
		trigger_entries = int(self.consolidation_trigger_entries)
		keep_recent_entries = int(self.consolidation_keep_recent_entries)
		if len(short_items) < trigger_entries:
			return False
		ordered = sorted(enumerate(short_items), key=lambda pair: (int(pair[1].get("tick", 0) or 0), int(pair[0])))
		kept = ordered[-keep_recent_entries:] if keep_recent_entries else []
		kept_ids = {
			str(item.get("record_id", "") or "").strip()
			for _idx, item in kept
			if str(item.get("record_id", "") or "").strip()
		}
		candidates = [
			dict(item)
			for _idx, item in ordered[: max(0, len(ordered) - keep_recent_entries)]
		]
		if not candidates:
			return False
		messages = self._consolidation_messages(start, candidates)
		trace_id = uuid4().hex
		trace = {
			"trace_id": trace_id,
			"tick": int(start.tick),
			"actor_id": start.actor_id,
			"context_type": "social_memory_consolidation",
			"workflow_id": self.workflow_id,
			"model": self.model,
			"request": {
				"messages": messages,
				"temperature": float(self.temperature),
				"max_tokens": int(self.consolidation_max_tokens),
				"response_format": {"type": "json_object"},
				"extra": dict(self.request_extra),
			},
			"response_text": "",
			"parsed_output": None,
			"action_results": [],
		}
		try:
			response_text = self.client.chat_text(
				messages=messages,
				model=self.model,
				temperature=float(self.temperature),
				max_tokens=int(self.consolidation_max_tokens),
				response_format={"type": "json_object"},
				extra=dict(self.request_extra),
			)
		except Exception as exc:
			trace["error"] = {"code": "SOCIAL_MEMORY_CONSOLIDATION_REQUEST_FAILED", "message": str(exc)}
			self._record_trace(trace)
			raise KernFailure(
				"SOCIAL_MEMORY_CONSOLIDATION_REQUEST_FAILED",
				str(exc),
				origin="workflow",
				phase="social_memory_consolidation",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_INFRASTRUCTURE,
				cause=exc,
			) from exc
		trace["response_text"] = str(response_text)
		try:
			parsed = json.loads(str(response_text))
			patch = self._validate_consolidation_output(parsed, candidates, kept_ids)
		except (json.JSONDecodeError, TypeError, ValueError) as exc:
			trace["parsed_output"] = parsed if "parsed" in locals() else None
			trace["error"] = {"code": "SOCIAL_MEMORY_CONSOLIDATION_OUTPUT_INVALID", "message": str(exc)}
			self._record_trace(trace)
			raise KernFailure(
				"SOCIAL_MEMORY_CONSOLIDATION_OUTPUT_INVALID",
				str(exc),
				origin="workflow",
				phase="social_memory_consolidation",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
				cause=exc,
			) from exc
		trace["parsed_output"] = parsed
		self._record_trace(trace)
		execute = getattr(ws, "services", {}).get("execute") if isinstance(getattr(ws, "services", {}), dict) else None
		if not callable(execute):
			raise KernFailure(
				"SOCIAL_MEMORY_CONSOLIDATION_APPLY_FAILED",
				"workflow memory patch executor is unavailable",
				origin="workflow",
				phase="social_memory_consolidation",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		execute(
			{
				"effects": [
					{
						"effect": "ApplyMemoryPatch",
						"target": start.actor_id,
						"notes": [],
						"mid_term_summaries": [dict(item) for item in patch["mid_term_summaries"]],
						"remove_short_term_record_ids": [str(item) for item in patch["remove_short_term_record_ids"]],
					}
				]
			},
			{"self_id": start.actor_id, "target_id": start.actor_id},
		)
		return True

	def _consolidation_messages(self, start: TurnStart, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
		payload = {
			"schema_version": "social_memory_consolidation_input.v1",
			"tick": int(start.tick),
			"actor_id": start.actor_id,
			"trigger_entries": int(self.consolidation_trigger_entries),
			"keep_recent_entries": int(self.consolidation_keep_recent_entries),
			"short_term_candidates": [dict(item) for item in candidates],
		}
		system = (
			"你正在整理一个社交平台用户的短期记忆。系统已按时间保留最新短期记忆，"
			"输入候选将从短期记忆移除并总结进入中期记忆。只根据输入候选记忆生成中期摘要，"
			"不要加入候选之外的信息。返回 JSON 对象："
			"{\"mid_term_summaries\":[{\"summary\":\"...\",\"tick_start\":0,\"tick_end\":0}],"
			"\"decision_summary\":\"...\"}。"
		)
		return [
			{"role": "system", "content": system},
			{"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
		]

	@staticmethod
	def _validate_consolidation_output(raw: Any, candidates: list[dict[str, Any]], kept_ids: set[str]) -> dict[str, Any]:
		if not isinstance(raw, dict) or set(raw) != {"mid_term_summaries", "decision_summary"}:
			raise ValueError("social memory consolidation output has invalid fields")
		candidate_ids = {
			str(item.get("record_id", "") or "").strip()
			for item in candidates
			if str(item.get("record_id", "") or "").strip()
		}
		summaries_raw = raw["mid_term_summaries"]
		if not isinstance(summaries_raw, list):
			raise ValueError("mid_term_summaries must be an array")
		summaries: list[dict[str, Any]] = []
		for item in summaries_raw:
			if not isinstance(item, dict):
				raise ValueError("mid_term summary must be an object")
			summary = str(item.get("summary", "") or "").strip()
			if not summary:
				raise ValueError("mid_term summary text is required")
			summaries.append(
				{
					"summary": summary,
					"tick_start": int(item.get("tick_start", 0) or 0),
					"tick_end": int(item.get("tick_end", 0) or 0),
					"tags": [str(x) for x in list(item.get("tags", []) or [])] if isinstance(item.get("tags", []), list) else [],
				}
			)
		if not isinstance(raw["decision_summary"], str) or not raw["decision_summary"].strip():
			raise ValueError("decision_summary must be a non-blank string")
		return {
			"mid_term_summaries": summaries,
			"remove_short_term_record_ids": sorted(candidate_ids - set(kept_ids)),
		}

	def begin_turn(self, _ws: Any, start: TurnStart) -> AgentTurnSession:
		binding = self.actor_bindings.get(start.actor_id)
		if binding is None:
			raise KernFailure(
				"SOCIAL_ACTOR_BINDING_MISSING",
				"social workflow has no platform binding for actor",
				origin="workflow",
				phase="turn_start",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		if not bool(self.activation_schedule.is_active(start.actor_id, start.tick)):
			return _InactiveSocialTurnSession(workflow_id=self.workflow_id)
		return _ActiveSocialTurnSession(workflow=self, start=start, binding=binding)

	def decide_page(self, ws: Any, start: TurnStart, binding: ActorPlatformBinding) -> tuple[list[dict[str, Any]], dict[str, Any]]:
		perception, card_by_id = self._decision_perception(ws, start, binding)
		prepared = self.prepare_page_decision(perception, card_by_id, start, binding)
		return prepared.complete(prepared.run())

	def prepare_page_decision(
		self,
		perception: dict[str, Any],
		card_by_id: dict[str, dict[str, Any]],
		start: TurnStart,
		binding: ActorPlatformBinding,
	) -> "_PreparedSocialPageDecision":
		messages = self._messages(perception)
		trace_id = uuid4().hex
		trace = {
			"trace_id": trace_id,
			"tick": int(start.tick),
			"actor_id": start.actor_id,
			"context_type": "social_platform_page_decision",
			"workflow_id": self.workflow_id,
			"model": self.model,
			"request": {
				"messages": messages,
				"temperature": float(self.temperature),
				"max_tokens": int(self.max_tokens),
				"response_format": None,
				"extra": dict(self.request_extra),
			},
			"response_text": "",
			"parsed_output": None,
			"action_results": [],
		}
		return _PreparedSocialPageDecision(
			workflow=self,
			start=start,
			binding=binding,
			card_by_id={str(key): dict(value) for key, value in dict(card_by_id).items()},
			messages=messages,
			trace=trace,
		)

	def run_page_decision_request(self, messages: list[dict[str, Any]]) -> str:
		return self.client.chat_text(
			messages=messages,
			model=self.model,
			temperature=float(self.temperature),
			max_tokens=int(self.max_tokens),
			response_format=None,
			extra=dict(self.request_extra),
		)

	def complete_page_decision(
		self,
		response_text: str,
		*,
		trace: dict[str, Any],
		card_by_id: dict[str, dict[str, Any]],
		start: TurnStart,
		binding: ActorPlatformBinding,
		) -> tuple[list[dict[str, Any]], dict[str, Any]]:
		trace["response_text"] = str(response_text)
		try:
			parsed = _parse_page_decision_output(str(response_text))
		except ValueError as exc:
			trace["error"] = {"code": "WORKFLOW_OUTPUT_PARSE_FAILED", "message": str(exc)}
			self._record_trace(trace)
			raise KernFailure(
				"WORKFLOW_OUTPUT_PARSE_FAILED",
				"social workflow response is not valid JSON",
				origin="workflow",
				phase="social_decision",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
				cause=exc,
			) from exc

		try:
			actions, decision_summary = self._validate_output(parsed, card_by_id)
		except (TypeError, ValueError) as exc:
			trace["parsed_output"] = parsed
			trace["error"] = {"code": "WORKFLOW_OUTPUT_CONTRACT_INVALID", "message": str(exc)}
			self._record_trace(trace)
			raise KernFailure(
				"WORKFLOW_OUTPUT_CONTRACT_INVALID",
				str(exc),
				origin="workflow",
				phase="social_decision",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
				cause=exc,
			) from exc

		trace["parsed_output"] = parsed
		recorded_trace_id = self._record_trace(trace)
		meta = {
			"provider": self.workflow_id,
			"reason": "social_page_decision" if actions else "no_action",
			"decision_summary": decision_summary,
			"llm_trace_id": recorded_trace_id,
		}
		return [self._action_intent(binding.terminal_id, action) for action in actions], meta

	def _request_page_decision_with_trace(self, trace: dict[str, Any], start: TurnStart, messages: list[dict[str, Any]]) -> str:
		empty_attempts: list[dict[str, Any]] = []
		for attempt in range(_PAGE_DECISION_EMPTY_RESPONSE_MAX_ATTEMPTS):
			try:
				response_text = self.run_page_decision_request(messages)
			except KernFailure:
				raise
			except Exception as exc:
				if empty_attempts:
					trace["empty_response_attempts"] = [dict(item) for item in empty_attempts]
				trace["error"] = {"code": "SOCIAL_WORKFLOW_LLM_REQUEST_FAILED", "message": str(exc)}
				self._record_trace(trace)
				raise KernFailure(
					"SOCIAL_WORKFLOW_LLM_REQUEST_FAILED",
					str(exc),
					origin="workflow",
					phase="social_decision",
					context={"actor_id": start.actor_id, "tick": start.tick},
					category=ERROR_KIND_INFRASTRUCTURE,
					cause=exc,
				) from exc
			if str(response_text or "").strip():
				if empty_attempts:
					trace["empty_response_attempts"] = [dict(item) for item in empty_attempts]
				return str(response_text)
			empty_attempts.append({"attempt": int(attempt + 1)})
		trace["response_text"] = ""
		trace["empty_response_attempts"] = [dict(item) for item in empty_attempts]
		trace["error"] = {
			"code": "SOCIAL_WORKFLOW_EMPTY_RESPONSE",
			"message": "social workflow LLM response was empty after retries",
			"attempts": int(_PAGE_DECISION_EMPTY_RESPONSE_MAX_ATTEMPTS),
		}
		self._record_trace(trace)
		raise KernFailure(
			"SOCIAL_WORKFLOW_EMPTY_RESPONSE",
			"social workflow LLM response was empty after retries",
			origin="workflow",
			phase="social_decision",
			context={"actor_id": start.actor_id, "tick": start.tick, "attempts": int(_PAGE_DECISION_EMPTY_RESPONSE_MAX_ATTEMPTS)},
			category=ERROR_KIND_INFRASTRUCTURE,
		)

	def _decision_perception(
		self,
		ws: Any,
		start: TurnStart,
		binding: ActorPlatformBinding,
	) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
		actor = ws.get_entity_by_id(start.actor_id) if hasattr(ws, "get_entity_by_id") else None
		if actor is None:
			raise KernFailure(
				"SOCIAL_ACTOR_MISSING",
				"social workflow actor is unavailable in WorldState",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		identity = actor.get_component(self.identity_component_id) if hasattr(actor, "get_component") else None
		if identity is None:
			raise KernFailure(
				"SOCIAL_IDENTITY_MISSING",
				"social workflow actor has no configured identity component",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "component_id": self.identity_component_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		profile_payload = self._profile_payload(
			{
				"profile_id": getattr(identity, "profile_id", None),
				"natural_language_background": getattr(identity, "natural_language_background", None),
				"big_five": getattr(identity, "big_five", None),
			}
		)
		terminal = ws.get_entity_by_id(binding.terminal_id) if hasattr(ws, "get_entity_by_id") else None
		screen = terminal.get_component("social_propagation:ScreenComponent") if terminal is not None and hasattr(terminal, "get_component") else None
		if screen is None:
			raise KernFailure(
				"SOCIAL_SCREEN_MISSING",
				"social workflow terminal has no ScreenComponent",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "terminal_id": binding.terminal_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		if (
			str(getattr(screen, "runtime_id", "") or "") != binding.runtime_id
			or str(getattr(screen, "account_id", "") or "") != binding.account_id
			or str(getattr(screen, "view", "") or "") != "feed"
			or int(getattr(screen, "updated_tick", -1)) != int(start.tick)
		):
			raise KernFailure(
				"SOCIAL_SCREEN_MISMATCH",
				"social screen does not match the active actor binding and tick",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "terminal_id": binding.terminal_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		feed_session_id = getattr(screen, "feed_session_id", None)
		if not isinstance(feed_session_id, int) or isinstance(feed_session_id, bool) or feed_session_id <= 0:
			raise KernFailure(
				"SOCIAL_FEED_SESSION_INVALID",
				"feed_session_id must be a positive integer",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		raw_items = getattr(screen, "feed_items", None)
		if not isinstance(raw_items, list):
			raise KernFailure(
				"SOCIAL_FEED_SESSION_INVALID",
				"feed session feed_items must be an array",
				origin="workflow",
				phase="social_perception",
				context={"actor_id": start.actor_id, "tick": start.tick},
				category=ERROR_KIND_CONTRACT,
			)
		items: list[dict[str, Any]] = []
		card_by_id: dict[str, dict[str, Any]] = {}
		for raw in raw_items:
			if not isinstance(raw, dict):
				raise KernFailure(
					"SOCIAL_FEED_SESSION_INVALID",
					"feed item must be an object",
					origin="workflow",
					phase="social_perception",
					context={"actor_id": start.actor_id, "tick": start.tick},
					category=ERROR_KIND_CONTRACT,
				)
			post_id = raw.get("post_id")
			if not isinstance(post_id, str) or not post_id.strip() or post_id != post_id.strip() or post_id in card_by_id:
				raise KernFailure(
					"SOCIAL_FEED_SESSION_INVALID",
					"feed item post_id must be a unique non-blank trimmed string",
					origin="workflow",
					phase="social_perception",
					context={"actor_id": start.actor_id, "tick": start.tick},
					category=ERROR_KIND_CONTRACT,
				)
			card = {key: raw[key] for key in _PUBLIC_CARD_FIELDS if key in raw}
			items.append(card)
			card_by_id[post_id] = card

		memory_component = actor.get_component("MemoryComponent") if hasattr(actor, "get_component") else None
		memory_items = [
			dict(item)
			for item in list(getattr(memory_component, "mid_term_queue", []) or [])
			+ list(getattr(memory_component, "short_term_queue", []) or [])
			if isinstance(item, dict)
		]
		memory = memory_items[-int(self.max_memory_items) :] if int(self.max_memory_items) else []
		return (
			{
				"schema_version": "social_decision_perception.v1",
				"tick": int(start.tick),
				"actor_id": start.actor_id,
				"profile": profile_payload,
				"screen": {
					"terminal_id": binding.terminal_id,
					"runtime_id": binding.runtime_id,
					"account_id": binding.account_id,
					"view": "feed",
					"updated_tick": int(start.tick),
					"feed_session_id": feed_session_id,
					"feed_items": items,
				},
				"recent_social_memory": [dict(item) for item in memory],
			},
			card_by_id,
		)

	@staticmethod
	def _profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
		profile_id = profile.get("profile_id")
		background = profile.get("natural_language_background")
		big_five = profile.get("big_five")
		if not isinstance(profile_id, str) or not profile_id.strip():
			raise ValueError("social profile_id must be a non-blank string")
		if not isinstance(background, str) or not background.strip():
			raise ValueError("social natural_language_background must be a non-blank string")
		if not isinstance(big_five, dict) or set(big_five) != set(_BIG_FIVE_FIELDS):
			raise ValueError("social big_five must contain exactly the five configured dimensions")
		for field_name in _BIG_FIVE_FIELDS:
			value = big_five[field_name]
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
				raise ValueError(f"social big_five.{field_name} must be a number between 0 and 1")
		return {
			"profile_id": profile_id,
			"natural_language_background": background,
			"big_five": {field_name: float(big_five[field_name]) for field_name in _BIG_FIVE_FIELDS},
		}

	def _messages(self, perception: dict[str, Any]) -> list[dict[str, Any]]:
		profile = dict(perception.get("profile", {}) or {}) if isinstance(perception.get("profile", {}), dict) else {}
		big_five = dict(profile.get("big_five", {}) or {}) if isinstance(profile.get("big_five", {}), dict) else {}
		big_five_text = ", ".join(
			f"{field_name}={float(big_five[field_name]):.2f}"
			for field_name in _BIG_FIVE_FIELDS
			if field_name in big_five
		)
		profile_id = str(profile.get("profile_id", "") or "").strip()
		background = str(profile.get("natural_language_background", "") or "").strip()
		system = (
			"我就是以下这个社交平台用户；这不是第三方角色扮演材料，而是我的自我画像和稳定人格。"
			"我的每个判断都要直接来自我的经历、性格、近期社交记忆和当前手机页面。\n\n"
			f"我的 profile_id：{profile_id}\n"
			f"我的自我画像：\n{background}\n"
			f"我的人格五维（0-1，越高越明显）：{big_five_text}\n\n"
			"现在是我的休息时间，我只是随手刷自己的社交平台推荐页"
			"我会像平时一样快速扫过页面：大多数内容看过就划走，只有被自然触动时才公开互动。"
			"我不会把人格维度机械地解释成固定行为，也不会假设页面之外的信息。"
			"评论和转发文字必须符合我的第一人称表达。只返回一个 JSON 对象，不输出解释性正文。\n"
			"可用行为含义："
			"do_nothing 表示我看过后继续划走，不公开表达态度；这是默认且常见的选择，输出为空 actions。"
			"like 表示我愿意留下一个轻量的公开反馈，通常是认同、共鸣、觉得有用或想稍后再看。"
			"comment 表示我有一句具体的话想当场说出来，例如补充、质疑、提问、表达个人经验或情绪。"
			"repost 表示我想把这条内容转给自己的社交圈看，或借它公开表达一个我愿意承担的立场；"
			"输出契约：{\"actions\":[...],\"decision_summary\":\"一至三句决定摘要\"}。"
			"每次只表达当前这一刻的自然浏览反应，actions 必须为空数组或只包含一个动作。"
			"如果我选择 do_nothing，就返回 {\"actions\":[],\"decision_summary\":\"我为什么划走\"}。"
			"我不需要系统性处理页面上的帖子；已经有一次轻微互动后，如果当前页面状态和近期记忆"
			"没有自然激发新的互动冲动，就返回空 actions。"
			"like 动作只能是 {\"post_id\":\"页面中的ID\",\"action\":\"like\"}，不得包含 text。"
			"comment 动作必须是 {\"post_id\":\"页面中的ID\",\"action\":\"comment\",\"text\":\"非空评论\"}。"
			"repost 动作必须是 {\"post_id\":\"页面中的ID\",\"action\":\"repost\",\"text\":\"可为空\"}。"
			"actions 可以为空。"
			"所有动作的 post_id 必须逐字取自 allowed_action_post_ids；不得输出列表之外的 post_id。"
		)
		allowed_ids = [
			str(item.get("post_id"))
			for item in list(((perception.get("screen") or {}).get("feed_items") or []))
			if isinstance(item, dict) and isinstance(item.get("post_id"), str)
		]
		request_perception = dict(perception)
		request_perception.pop("profile", None)
		request_perception["schema_version"] = "social_decision_page_context.v1"
		request_perception["allowed_action_post_ids"] = allowed_ids
		return [
			{"role": "system", "content": system},
			{"role": "user", "content": json.dumps(request_perception, ensure_ascii=False, separators=(",", ":"))},
		]

	@staticmethod
	def _validate_output(raw: Any, card_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
		if not isinstance(raw, dict) or set(raw) != {"actions", "decision_summary"}:
			raise ValueError("social output must contain exactly actions and decision_summary")
		actions = raw["actions"]
		summary = raw["decision_summary"]
		if not isinstance(actions, list):
			raise ValueError("social output actions must be an array")
		if len(actions) > 1:
			raise ValueError("social output actions must contain at most one next action")
		if not isinstance(summary, str) or not summary.strip():
			raise ValueError("social output decision_summary must be a non-blank string")
		seen: set[tuple[str, str]] = set()
		validated: list[dict[str, Any]] = []
		for item in actions:
			if not isinstance(item, dict):
				raise ValueError("social action must be an object")
			post_id = item.get("post_id")
			action = item.get("action")
			if not isinstance(post_id, str) or post_id not in card_by_id:
				raise ValueError(f"social action post_id is not visible: {post_id!r}")
			if action not in {"like", "comment", "repost"}:
				raise ValueError(f"unsupported social action: {action!r}")
			expected_keys = {"post_id", "action", "text"} if action == "comment" else {"post_id", "action"}
			if action == "repost" and "text" in item:
				expected_keys.add("text")
			if set(item) != expected_keys:
				raise ValueError(f"invalid fields for social action {action}")
			key = (post_id, action)
			if key in seen:
				raise ValueError(f"duplicate social action: {post_id}/{action}")
			seen.add(key)
			card = card_by_id[post_id]
			if action == "like" and card.get("viewer_has_liked") is True:
				raise ValueError(f"post is already liked by viewer: {post_id}")
			if action == "repost" and card.get("viewer_has_reposted") is True:
				raise ValueError(f"post is already reposted by viewer: {post_id}")
			out = {"post_id": post_id, "action": action}
			if action == "comment":
				text = item.get("text")
				if not isinstance(text, str) or not text.strip():
					raise ValueError("social comment text must be a non-blank string")
				out["text"] = text
			elif action == "repost":
				text = item.get("text", "")
				if not isinstance(text, str):
					raise ValueError("social repost text must be a string")
				out["text"] = text
			validated.append(out)
		return validated, summary

	@staticmethod
	def _action_intent(terminal_id: str, action: dict[str, Any]) -> dict[str, Any]:
		action_name = action["action"]
		verb = {
			"like": "LikeSocialPost",
			"comment": "CommentOnSocialPost",
			"repost": "RepostSocialPost",
		}[action_name]
		parameters = {"post_id": action["post_id"]}
		if action_name in {"comment", "repost"}:
			parameters["text"] = action.get("text", "")
		return {"verb": verb, "target_id": terminal_id, "parameters": parameters}

	def _record_trace(self, trace: dict[str, Any]) -> str:
		if self.trace_recorder is None:
			return ""
		return str(self.trace_recorder.record(trace) or "")

	@staticmethod
	def _trimmed(value: Any, label: str) -> str:
		if not isinstance(value, str) or not value.strip() or value != value.strip():
			raise ValueError(f"social workflow {label} must be a non-blank trimmed string")
		return value


@dataclass
class _InactiveSocialTurnSession:
	workflow_id: str

	def next_step(self, _ws: Any, _frame: TurnFrame) -> EndTurn:
		return EndTurn(meta={"provider": self.workflow_id, "reason": "not_scheduled"})


@dataclass
class _ActiveSocialTurnSession:
	workflow: SocialPlatformWorkflow
	start: TurnStart
	binding: ActorPlatformBinding
	phase: str = "browse"
	decision_meta: dict[str, Any] = field(default_factory=dict)

	def next_step(self, ws: Any, frame: TurnFrame):
		prepared = self.prepare_parallel_next_step(ws, frame)
		if isinstance(prepared, (SubmitAction, EndTurn)):
			return prepared
		return prepared.complete(prepared.run())

	def prepare_parallel_next_step(self, ws: Any, frame: TurnFrame):
		feedback = frame.previous_action
		if feedback is not None and feedback.status == "rejected":
			return EndTurn(
				meta={
					**dict(self.decision_meta),
					"provider": self.workflow.workflow_id,
					"reason": "social_action_rejected",
					"rejection_code": feedback.rejection_code,
				}
			)
		if self.phase == "browse":
			self.phase = "awaiting_browse"
			return SubmitAction(
				intent={"verb": "BrowseSocialFeed", "target_id": self.binding.terminal_id, "parameters": {}},
				meta={"provider": self.workflow.workflow_id, "reason": "scheduled_social_feed_open"},
			)
		if self.phase == "awaiting_browse":
			if feedback is None or feedback.status != "committed" or feedback.intent.get("verb") != "BrowseSocialFeed":
				raise KernFailure(
					"SOCIAL_BROWSE_FEEDBACK_INVALID",
					"social workflow expected committed BrowseSocialFeed feedback",
					origin="workflow",
					phase="social_decision",
					context={"actor_id": self.start.actor_id, "tick": self.start.tick},
					category=ERROR_KIND_CONTRACT,
				)
			return self._prepare_decision(ws, frame)
		if self.phase == "awaiting_action":
			if feedback is None or feedback.status != "committed":
				raise KernFailure(
					"SOCIAL_ACTION_FEEDBACK_INVALID",
					"social workflow expected committed social action feedback",
					origin="workflow",
					phase="social_decision",
					context={"actor_id": self.start.actor_id, "tick": self.start.tick},
					category=ERROR_KIND_CONTRACT,
				)
			return self._prepare_decision(ws, frame)
		if self.phase == "parallel_decision":
			return self._prepare_decision(ws, frame)
		self.phase = "done"
		return EndTurn(meta=dict(self.decision_meta))

	def _prepare_decision(self, ws: Any, frame: TurnFrame):
		apply_record_memory_patch(ws, self.start.actor_id, frame.reason, frame.mode_context)
		self.workflow.consolidate_memory_if_needed(ws, self.start)
		perception, card_by_id = self.workflow._decision_perception(ws, self.start, self.binding)
		self.phase = "parallel_decision"
		return _PreparedSocialSessionStep(
			session=self,
			decision=self.workflow.prepare_page_decision(perception, card_by_id, self.start, self.binding),
		)


__all__ = [
	"ActorPlatformBinding",
	"SocialActivationSchedule",
	"SocialPlatformWorkflow",
]
