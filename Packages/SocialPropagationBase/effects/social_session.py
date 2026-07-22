from __future__ import annotations

from typing import Any
import hashlib

from KERN.agent_workflow.provider_routing import resolve_workflow_provider
from KERN.agent_workflow.runtime import commit_workflow_decision, decide_from_prepared_workflow, prepare_workflow_decision_input
from KERN.execution_errors import is_execution_error_event
from KERN.effects import EffectSpec
from KERN.executor._effect_binder import BindError, _base_bind, _resolve_param_token
from KERN.models.components import AgentControlComponent, ContainerComponent, ScreenComponent
from KERN.package_definitions import package_effect


_SELECTION_KINDS = {"social_behavior_rate", "big_five_extraversion"}


def _optional_int(params: dict[str, Any], key: str, context: dict[str, Any], default: int) -> int:
	try:
		return int(_resolve_param_token(params.get(key, default), context))
	except Exception:
		return default


def _bind_social_session_round(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	policy = _resolve_param_token(params.get("policy", {}), ctx)
	if not isinstance(policy, dict):
		raise BindError(effect_type, ["policy"])
	selection = policy.get("selection", {})
	session = policy.get("session", {})
	permissions = policy.get("permissions", {})
	if not isinstance(selection, dict) or not isinstance(session, dict) or not isinstance(permissions, dict):
		raise BindError(effect_type, ["policy"])
	selection_kind = str(selection.get("kind", "") or "").strip()
	if selection_kind not in _SELECTION_KINDS:
		raise BindError(effect_type, ["policy.selection.kind"])
	budgets = {
		"initial_feed_limit": _optional_int(session, "initial_feed_limit", ctx, 0),
		"max_feed_pages": _optional_int(session, "max_feed_pages", ctx, 0),
		"max_open_posts": _optional_int(session, "max_open_posts", ctx, 0),
		"max_terminal_actions": _optional_int(session, "max_terminal_actions", ctx, 0),
	}
	if any(value < 0 for value in budgets.values()) or budgets["initial_feed_limit"] < 1 or budgets["max_terminal_actions"] != 1:
		raise BindError(effect_type, ["policy.session"])
	if any(not isinstance(permissions.get(key), bool) for key in ("allow_create_post", "like_requires_open_post", "comment_requires_open_post", "repost_requires_open_post")):
		raise BindError(effect_type, ["policy.permissions"])
	out = {
		"effect": effect_type,
		"provider_id": str(_resolve_param_token(params.get("provider_id", ""), ctx) or "").strip(),
		"max_agents_per_round": max(0, _optional_int(params, "max_agents_per_round", ctx, 999999)),
		"decision_mode": str(_resolve_param_token(params.get("decision_mode", "serial"), ctx) or "serial").strip(),
		"max_decision_workers": max(1, _optional_int(params, "max_decision_workers", ctx, 1)),
		"policy": {"selection": dict(selection), "session": budgets, "permissions": dict(permissions)},
	}
	return out, ctx


def _bind_exit_social_session(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, _params, ctx = _base_bind(effect_data, context)
	return {"effect": effect_type}, ctx


def execute_social_session_round(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	services = getattr(ws, "services", {}) or {}
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	run_id = str(getattr(ws, "_checkpoint_run_id", "") or services.get("run_id", "") or "")
	policy = dict(data["policy"])
	selected: list[tuple[str, Any, Any]] = []
	for agent_id in sorted(str(item) for item in getattr(ws, "entities", {})):
		if len(selected) >= int(data["max_agents_per_round"]):
			break
		agent = ws.get_entity_by_id(agent_id)
		if agent is None or not hasattr(agent, "get_component"):
			continue
		control = agent.get_component("AgentControlComponent")
		eligibility = agent.get_component("social_propagation:SocialSessionEligibilityComponent")
		if not isinstance(control, AgentControlComponent) or not bool(control.enabled) or eligibility is None:
			continue
		phone = _phone_for_agent(ws, agent)
		if phone is None:
			continue
		rate = _selection_rate(policy, eligibility)
		roll = _stable_roll(run_id, tick, agent_id, str(policy["selection"]["kind"]))
		if roll <= rate:
			selected.append((agent_id, control, phone))
	events: list[dict[str, Any]] = []
	for agent_id, control, phone in selected:
		workflow = resolve_workflow_provider(services, control, str(data["provider_id"]))
		if workflow is None or not hasattr(workflow, "decide"):
			events.append({"type": "SocialSessionEnded", "agent_id": agent_id, "tick": tick, "exit_reason": "provider_missing"})
			continue
		feed_events = _executor.execute(ws, {"effect": "ObserveSocialFeed", "target": str(phone.entity_id), "limit": int(policy["session"]["initial_feed_limit"])}, {"self_id": agent_id, "target_id": str(phone.entity_id)})
		if any(str(event.get("type", "")) == "ExecutionError" for event in feed_events if isinstance(event, dict)):
			events.append({"type": "SocialSessionEnded", "agent_id": agent_id, "tick": tick, "exit_reason": "initial_feed_failed"})
			continue
		session_events = _run_session(_executor, ws, agent_id, workflow, policy, int(policy["session"]["max_feed_pages"]), int(policy["session"]["max_open_posts"]))
		events.extend(session_events)
		_record_session_trace(ws, agent_id, phone, run_id, tick, session_events)
	events.append({
		"type": "SocialSessionRoundEvaluated",
		"tick": tick,
		"selected_count": len(selected),
		"policy_selection_kind": str(data["policy"]["selection"]["kind"]),
	})
	return events


def _record_session_trace(ws: Any, agent_id: str, phone: Any, run_id: str, tick: int, events: list[dict[str, Any]]) -> None:
	ended = next((event for event in events if str(event.get("type", "")) == "SocialSessionEnded"), None)
	if not isinstance(ended, dict):
		return
	screen = phone.get_component("ScreenComponent") if phone is not None else None
	bridge = (getattr(ws, "services", {}) or {}).get("external_runtime_bridge")
	if not isinstance(screen, ScreenComponent) or bridge is None or not callable(getattr(bridge, "invoke", None)):
		return
	session_id = hashlib.sha256(f"{run_id}|{tick}|{agent_id}".encode("utf-8")).hexdigest()[:24]
	bridge.invoke(str(screen.runtime_id), "record_session_trace", {"session_id": session_id, "account_id": str(screen.account_id), "tick": tick, "exit_reason": str(ended.get("exit_reason", "")), "steps": int(ended.get("steps", 0) or 0), "agent_id": agent_id}, {"run_id": run_id, "tick": tick})


def _phone_for_agent(ws: Any, agent: Any) -> Any | None:
	container = agent.get_component("ContainerComponent")
	if not isinstance(container, ContainerComponent):
		return None
	for item_id in container.get_all_item_ids():
		item = ws.get_entity_by_id(str(item_id))
		if item is not None and isinstance(item.get_component("ScreenComponent"), ScreenComponent):
			return item
	return None


def _selection_rate(policy: dict[str, Any], eligibility: Any) -> float:
	selection = dict(policy["selection"])
	if str(selection["kind"]) == "social_behavior_rate":
		value = float(getattr(eligibility, "session_rate", 0.0) or 0.0) * float(selection.get("base_rate_multiplier", 1.0) or 0.0)
	else:
		value = float(selection.get("alpha", 0.0) or 0.0) + float(selection.get("beta_e", 0.0) or 0.0) * float(getattr(eligibility, "extraversion", 0.0) or 0.0)
	return max(0.0, min(1.0, value))


def _stable_roll(run_id: str, tick: int, agent_id: str, adapter: str) -> float:
	digest = hashlib.sha256(f"{run_id}|{tick}|{agent_id}|{adapter}".encode("utf-8")).hexdigest()[:12]
	return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _run_session(executor: Any, ws: Any, agent_id: str, workflow: Any, policy: dict[str, Any], pages_left: int, opens_left: int) -> list[dict[str, Any]]:
	steps = 0
	while True:
		prepared = prepare_workflow_decision_input(ws, agent_id, workflow, "social_session", {"grounder": True, "social_session": True})
		if str(prepared.get("status")) != "ready":
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "prepare_failed", "steps": steps}]
		decision = decide_from_prepared_workflow(prepared)
		raw = decision.get("decision_raw", {}) if str(decision.get("status")) == "ok" else {}
		commands = list(raw.get("commands", []) or []) if isinstance(raw, dict) else []
		if not commands:
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "agent_exit", "steps": steps}]
		verb = str(dict(commands[0]).get("verb", "") or "")
		if verb == "ExitBrowsing":
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "agent_exit", "steps": steps}]
		if verb == "ContinueBrowsing" and pages_left <= 0:
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "session_budget_exhausted", "steps": steps}]
		if verb == "OpenSocialPost" and opens_left <= 0:
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "session_budget_exhausted", "steps": steps}]
		if verb == "CreateSocialPost" and not bool(policy["permissions"]["allow_create_post"]):
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "command_not_permitted", "steps": steps}]
		phone = _phone_for_agent(ws, ws.get_entity_by_id(agent_id))
		screen = phone.get_component("ScreenComponent") if phone is not None else None
		requires_open = (verb == "CommentSocialPost" and bool(policy["permissions"]["comment_requires_open_post"])) or (verb == "RepostSocialPost" and bool(policy["permissions"]["repost_requires_open_post"])) or (verb == "LikeSocialPost" and bool(policy["permissions"]["like_requires_open_post"]))
		if requires_open and not isinstance(getattr(screen, "current_post", None), dict):
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "read_required", "steps": steps}]
		outcome = commit_workflow_decision(ws, agent_id, "social_session", raw, max_commands=1, decide_error=str(decision.get("error", "") or ""))
		if str(outcome.get("type")) != "apply_operations":
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "command_failed", "steps": steps}]
		consumed = False
		for operation in list(outcome.get("operations", []) or []):
			bundle = operation.get("bundle", {}) if isinstance(operation, dict) else {}
			context = operation.get("context", {}) if isinstance(operation, dict) else {}
			operation_events = executor.execute_bundle(ws, bundle, context)
			if any(is_execution_error_event(event) for event in operation_events if isinstance(event, dict)):
				return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "command_failed", "steps": steps}]
			consumed = True
		steps += 1
		if not consumed:
			return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "command_failed", "steps": steps}]
		if verb == "ContinueBrowsing":
			pages_left -= 1
			continue
		if verb == "OpenSocialPost":
			opens_left -= 1
			continue
		return [{"type": "SocialSessionEnded", "agent_id": agent_id, "exit_reason": "terminal_action", "steps": steps, "terminal_verb": verb}]


def execute_exit_social_session(_executor: Any, ws: Any, _data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return [{
		"type": "SocialSessionExited",
		"agent_id": str(context.get("self_id", "") or ""),
		"tick": int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0),
	}]


@package_effect(EffectSpec(effect_id="social_propagation:SocialSessionRound", binder=_bind_social_session_round, handler=execute_social_session_round))
def social_session_round_definition() -> None:
	pass


@package_effect(EffectSpec(effect_id="social_propagation:ExitSocialSession", binder=_bind_exit_social_session, handler=execute_exit_social_session))
def exit_social_session_definition() -> None:
	pass
