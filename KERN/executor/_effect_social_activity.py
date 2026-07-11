from __future__ import annotations

import hashlib
from typing import Any

from ..agent_workflow.batch_runtime import normalize_decision_mode, run_social_activity_batch
from ..agent_workflow.provider_routing import resolve_workflow_provider
from ..execution_errors import ERROR_KIND_CONTRACT, executor_error
from ..models.components import AgentControlComponent, ContainerComponent, ScreenComponent, SocialBehaviorComponent, StatusComponent
from ._effect_binder import _base_bind, _resolve_param_token


SOCIAL_ACTION_COOLDOWN_STATUS = "social_action_cooldown"


def _optional_int(params: dict[str, Any], key: str, ctx: dict[str, Any], default: int) -> int:
	raw = _resolve_param_token(params.get(key, default), ctx)
	try:
		return int(raw)
	except Exception:
		return int(default)


def _optional_float(params: dict[str, Any], key: str, ctx: dict[str, Any], default: float) -> float:
	raw = _resolve_param_token(params.get(key, default), ctx)
	try:
		return float(raw)
	except Exception:
		return float(default)


def _optional_str(params: dict[str, Any], key: str, ctx: dict[str, Any], default: str = "") -> str:
	return str(_resolve_param_token(params.get(key, default), ctx) or "").strip()


def _bind_social_activity_gate_tick(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	out = {
		"effect": effect_type,
		"provider_id": _optional_str(params, "provider_id", ctx, ""),
		"max_agents_per_tick": max(0, _optional_int(params, "max_agents_per_tick", ctx, 999999)),
		"max_actions_per_agent": max(0, _optional_int(params, "max_actions_per_agent", ctx, 1)),
		"default_screen_context_window_ticks": max(0, _optional_int(params, "default_screen_context_window_ticks", ctx, 2)),
		"base_rate_multiplier": max(0.0, _optional_float(params, "base_rate_multiplier", ctx, 1.0)),
		"decision_mode": normalize_decision_mode(_optional_str(params, "decision_mode", ctx, "serial")),
		"max_decision_workers": max(1, _optional_int(params, "max_decision_workers", ctx, 1)),
	}
	return out, ctx


def _tick(ws: Any) -> int:
	return int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)


def _stable_roll(run_id: str, tick: int, agent_id: str) -> float:
	seed = f"{run_id}|{int(tick)}|{agent_id}|SocialActivityGateTick"
	digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
	return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _clamp01(value: Any) -> float:
	try:
		v = float(value)
	except Exception:
		v = 0.0
	return max(0.0, min(1.0, v))


def _inventory_screen(ws: Any, agent: Any) -> tuple[Any | None, ScreenComponent | None]:
	container = agent.get_component("ContainerComponent") if hasattr(agent, "get_component") else None
	if not isinstance(container, ContainerComponent):
		return None, None
	for item_id in container.get_all_item_ids():
		item = ws.get_entity_by_id(str(item_id)) if hasattr(ws, "get_entity_by_id") else None
		if item is None or not hasattr(item, "get_component"):
			continue
		screen = item.get_component("ScreenComponent")
		if isinstance(screen, ScreenComponent):
			return item, screen
	return None, None


def _active_hour_multiplier(ws: Any, behavior: SocialBehaviorComponent) -> float:
	active_hours = [int(x) for x in list(getattr(behavior, "active_hours", []) or [])]
	if not active_hours:
		return 1.0
	game_time = getattr(ws, "game_time", None)
	hour = getattr(game_time, "hour", None)
	if hour is None:
		try:
			hour = int(_tick(ws)) % 24
		except Exception:
			hour = 0
	return 1.0 if int(hour) in set(active_hours) else 0.35


def _probability(ws: Any, behavior: SocialBehaviorComponent, base_rate_multiplier: float) -> float:
	base = _clamp01(getattr(behavior, "base_activity_rate", 0.0)) * max(0.0, float(base_rate_multiplier or 0.0))
	value = base * _active_hour_multiplier(ws, behavior)
	return _clamp01(value)


def _workflow_for_agent(ws: Any, ctrl: AgentControlComponent, requested_provider_id: str) -> Any | None:
	return resolve_workflow_provider(getattr(ws, "services", {}) or {}, ctrl, requested_provider_id)


def _has_status(entity: Any, status_id: str) -> bool:
	comp = entity.get_component("StatusComponent") if hasattr(entity, "get_component") else None
	return bool(isinstance(comp, StatusComponent) and comp.has_status(status_id))


def execute_social_activity_gate_tick(_executor: Any, ws: Any, data: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
	services = getattr(ws, "services", {}) or {}
	if not callable(services.get("execute")):
		return executor_error(
			"SocialActivityGateTick: ws.services.execute missing",
			kind=ERROR_KIND_CONTRACT,
			code="SOCIAL_ACTIVITY_EXECUTE_MISSING",
			effect="SocialActivityGateTick",
		)
	tick = _tick(ws)
	run_id = str(getattr(ws, "_checkpoint_run_id", "") or services.get("run_id", "") or "")
	requested_provider_id = str(data.get("provider_id", "") or "").strip()
	max_agents = int(data.get("max_agents_per_tick", 999999) or 999999)
	max_actions = int(data.get("max_actions_per_agent", 1) or 1)
	screen_window = int(data.get("default_screen_context_window_ticks", 2) or 2)
	base_rate_multiplier = float(data.get("base_rate_multiplier", 1.0) or 1.0)
	decision_mode = normalize_decision_mode(data.get("decision_mode", "serial"))
	max_decision_workers = max(1, int(data.get("max_decision_workers", 1) or 1))

	events: list[dict[str, Any]] = []
	skipped = {"cooldown": 0, "missing_phone": 0, "provider": 0, "probability": 0, "disabled": 0}
	candidates = 0
	selected = 0
	selected_ids: list[str] = []
	batch_items: list[dict[str, Any]] = []
	granted_meta: list[dict[str, Any]] = []

	for agent_id in sorted(str(x) for x in getattr(ws, "entities", {}).keys()):
		if selected >= max_agents:
			break
		agent = ws.get_entity_by_id(agent_id)
		if agent is None or not hasattr(agent, "get_component"):
			continue
		behavior = agent.get_component("SocialBehaviorComponent")
		if not isinstance(behavior, SocialBehaviorComponent):
			continue
		candidates += 1
		ctrl = agent.get_component("AgentControlComponent")
		if not isinstance(ctrl, AgentControlComponent) or not bool(getattr(ctrl, "enabled", True)):
			skipped["disabled"] += 1
			continue
		phone, screen = _inventory_screen(ws, agent)
		if phone is None or screen is None or not str(getattr(screen, "runtime_id", "") or "").strip() or not str(getattr(screen, "account_id", "") or "").strip():
			skipped["missing_phone"] += 1
			continue
		workflow = _workflow_for_agent(ws, ctrl, requested_provider_id)
		if workflow is None or not hasattr(workflow, "decide"):
			skipped["provider"] += 1
			continue
		if _has_status(agent, SOCIAL_ACTION_COOLDOWN_STATUS):
			skipped["cooldown"] += 1
			continue
		probability = _probability(ws, behavior, base_rate_multiplier)
		roll = _stable_roll(run_id, tick, agent_id)
		if roll > probability:
			skipped["probability"] += 1
			continue
		opportunity_type = "routine_browse"
		if _clamp01(getattr(behavior, "expression_opportunity_rate", 0.0)) >= _clamp01(getattr(behavior, "routine_browse_rate", 0.0)):
			opportunity_type = "expression_opportunity"
		mode_context = {
			"social_activity_opportunity": True,
			"activity_reason": opportunity_type,
			"opportunity_type": opportunity_type,
			"max_social_actions": int(max_actions),
			"grounder": True,
			"grounder_screen_context_window_ticks": int(screen_window),
			"salient_context": [],
			"rumor_experiment": {"enabled": True, "active_rumor_ids": []},
		}
		batch_items.append(
			{
				"actor_id": agent_id,
				"workflow": workflow,
				"reason": opportunity_type,
				"mode_context": mode_context,
				"max_actions": int(max_actions),
			}
		)
		granted_meta.append(
			{
				"entity_id": agent_id,
				"phone_id": str(getattr(phone, "entity_id", "") or ""),
				"account_id": str(getattr(screen, "account_id", "") or ""),
				"opportunity_type": opportunity_type,
				"probability": probability,
				"roll": roll,
				"tick": tick,
			}
		)
		selected += 1
		selected_ids.append(agent_id)
	outcomes = run_social_activity_batch(
		ws,
		batch_items,
		decision_mode=decision_mode,
		max_decision_workers=max_decision_workers,
	)
	for meta, outcome in zip(granted_meta, outcomes):
		events.append(
			{
				"type": "SocialActivityOpportunityGranted",
				**dict(meta),
				"outcome": dict(outcome or {}),
			}
		)
	events.append(
		{
			"type": "SocialActivityGateEvaluated",
			"tick": tick,
			"candidate_count": candidates,
			"selected_count": selected,
			"selected_agent_ids": selected_ids,
			"skipped": skipped,
			"decision_mode": decision_mode,
			"max_decision_workers": max_decision_workers,
		}
	)
	return events
