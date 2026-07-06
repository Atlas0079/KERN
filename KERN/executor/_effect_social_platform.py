from __future__ import annotations

from typing import Any

from ..execution_errors import ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, executor_error, is_execution_error_event
from ..models.components import ScreenComponent
from ._effect_binder import BindError, _base_bind, _require_param, _resolve_param_token


def _optional_str(params: dict[str, Any], key: str, ctx: dict[str, Any], default: str = "") -> str:
	return str(_resolve_param_token(params.get(key, default), ctx) or "").strip()


def _optional_int(params: dict[str, Any], key: str, ctx: dict[str, Any], default: int = 0) -> int:
	raw = _resolve_param_token(params.get(key, default), ctx)
	try:
		return int(raw)
	except Exception:
		return int(default)


def _bind_targeted(effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	target = _optional_str(params, "target", ctx, "target")
	return effect_type, {"effect": effect_type, "target": target or "target"}, ctx


def _bind_observe_social_feed(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, out, ctx = _bind_targeted(effect_data, context)
	_, params, _ = _base_bind(effect_data, context)
	limit = max(1, min(20, _optional_int(params, "limit", ctx, 5)))
	out["limit"] = limit
	return out, ctx


def _bind_observe_social_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, out, ctx = _bind_targeted(effect_data, context)
	_, params, _ = _base_bind(effect_data, context)
	if "post_id" in params:
		out["post_id"] = _optional_str(params, "post_id", ctx)
	if "slot" in params:
		out["slot"] = _optional_int(params, "slot", ctx, 0)
	if "post_id" not in out and "slot" not in out:
		out["slot"] = 0
	if not out.get("post_id", "") and "slot" in out and int(out["slot"]) < 0:
		raise BindError(effect_type, ["slot"])
	return out, ctx


def _bind_create_social_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, out, ctx = _bind_targeted(effect_data, context)
	_, params, _ = _base_bind(effect_data, context)
	text = _optional_str(params, "text", ctx)
	if not text:
		raise BindError(effect_type, ["text"])
	tags_raw = _resolve_param_token(params.get("tags", []), ctx)
	tags = [str(x).strip() for x in list(tags_raw or []) if str(x).strip()] if isinstance(tags_raw, list) else []
	out.update({"text": text, "tags": tags})
	return out, ctx


def _bind_interact_social_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, out, ctx = _bind_targeted(effect_data, context)
	_, params, _ = _base_bind(effect_data, context)
	action = _optional_str(params, "action", ctx)
	if not action:
		raise BindError(effect_type, ["action"])
	if "post_id" in params:
		out["post_id"] = _optional_str(params, "post_id", ctx)
	if "slot" in params:
		out["slot"] = _optional_int(params, "slot", ctx, 0)
	if "post_id" not in out and "slot" not in out:
		out["slot"] = 0
	out["action"] = action
	if "text" in params:
		out["text"] = _optional_str(params, "text", ctx)
	return out, ctx


def _bind_follow_social_account(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, out, ctx = _bind_targeted(effect_data, context)
	_, params, _ = _base_bind(effect_data, context)
	target_account_id = str(_resolve_param_token(_require_param(params, effect_type, "target_account_id"), ctx) or "").strip()
	if not target_account_id:
		raise BindError(effect_type, ["target_account_id"])
	out["target_account_id"] = target_account_id
	return out, ctx


def _tick(ws: Any) -> int:
	return int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)


def _screen_for_target(executor: Any, ws: Any, context: dict[str, Any], data: dict[str, Any], effect_name: str):
	target_key = str(data.get("target", "target") or "target")
	phone, err = executor.require_entity(ws, context, target_key, effect_name, "target")
	if err is not None:
		return None, None, None, "", "", err
	screen = phone.get_component("ScreenComponent") if hasattr(phone, "get_component") else None
	if not isinstance(screen, ScreenComponent):
		return phone, None, None, "", "", executor_error(
			f"{effect_name}: ScreenComponent missing",
			kind=ERROR_KIND_BUSINESS,
			code="SOCIAL_SCREEN_COMPONENT_MISSING",
			effect=effect_name,
		)
	runtime_id = str(getattr(screen, "runtime_id", "") or "").strip()
	account_id = str(getattr(screen, "account_id", "") or "").strip()
	if not runtime_id:
		return phone, screen, None, "", account_id, executor_error(
			f"{effect_name}: runtime_id missing",
			kind=ERROR_KIND_CONTRACT,
			code="SOCIAL_RUNTIME_ID_MISSING",
			effect=effect_name,
		)
	if not account_id:
		return phone, screen, None, runtime_id, "", executor_error(
			f"{effect_name}: account_id missing",
			kind=ERROR_KIND_CONTRACT,
			code="SOCIAL_ACCOUNT_ID_MISSING",
			effect=effect_name,
		)
	bridge = (getattr(ws, "services", {}) or {}).get("external_runtime_bridge")
	if bridge is None or not callable(getattr(bridge, "invoke", None)):
		return phone, screen, None, runtime_id, account_id, executor_error(
			f"{effect_name}: external_runtime_bridge missing",
			kind=ERROR_KIND_CONTRACT,
			code="SOCIAL_RUNTIME_BRIDGE_MISSING",
			effect=effect_name,
		)
	return phone, screen, bridge, runtime_id, account_id, None


def _post_id_from_screen(screen: ScreenComponent, data: dict[str, Any], effect_name: str) -> str | list[dict[str, Any]]:
	post_id = str(data.get("post_id", "") or "").strip()
	if post_id:
		return post_id
	if "slot" in data:
		slot = int(data.get("slot", 0) or 0)
		items = list(getattr(screen, "feed_items", []) or [])
		if 0 <= slot < len(items) and isinstance(items[slot], dict):
			post_id = str(items[slot].get("post_id", "") or "").strip()
			if post_id:
				return post_id
	post_id = str(getattr(screen, "selected_post_id", "") or "").strip()
	if post_id:
		return post_id
	current = getattr(screen, "current_post", None)
	if isinstance(current, dict):
		post_id = str(current.get("post_id", "") or "").strip()
		if post_id:
			return post_id
	return executor_error(
		f"{effect_name}: post not available on screen",
		kind=ERROR_KIND_BUSINESS,
		code="SOCIAL_POST_NOT_ON_SCREEN",
		effect=effect_name,
	)


def _invoke(bridge: Any, runtime_id: str, operation: str, payload: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return bridge.invoke(runtime_id, operation, dict(payload), dict(context or {}))


def _mark_screen_error(screen: ScreenComponent, events: list[dict[str, Any]]) -> None:
	for ev in list(events or []):
		if is_execution_error_event(ev):
			screen.last_event_type = str(ev.get("type", "") or "")
			screen.last_error = str(ev.get("message", "") or "")
			return


def _first_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
	for ev in list(events or []):
		if isinstance(ev, dict) and str(ev.get("type", "") or "") == event_type:
			return ev
	return None


def _update_feed_screen(screen: ScreenComponent, event: dict[str, Any], tick: int) -> None:
	items = [dict(x) for x in list(event.get("items", []) or []) if isinstance(x, dict)]
	screen.view = "feed"
	screen.title = "Recommended feed"
	screen.feed_items = items
	screen.current_post = None
	screen.cursor = int(event.get("cursor", getattr(screen, "cursor", 0)) or 0)
	screen.selected_post_id = str(items[0].get("post_id", "") or "").strip() if items else ""
	screen.updated_tick = int(tick)
	screen.status_text = f"{len(items)} posts visible"
	screen.last_event_type = str(event.get("type", "") or "")
	screen.last_error = ""


def _update_post_screen(screen: ScreenComponent, event: dict[str, Any], tick: int) -> None:
	post = event.get("post", {}) or {}
	screen.view = "post"
	screen.title = str((post if isinstance(post, dict) else {}).get("summary", "") or "Post")
	screen.current_post = dict(post) if isinstance(post, dict) else None
	screen.selected_post_id = str((post if isinstance(post, dict) else {}).get("post_id", "") or "").strip()
	screen.updated_tick = int(tick)
	screen.status_text = "Post open"
	screen.last_event_type = str(event.get("type", "") or "")
	screen.last_error = ""


def _update_action_status(screen: ScreenComponent, event: dict[str, Any], tick: int) -> None:
	screen.updated_tick = int(tick)
	screen.last_event_type = str(event.get("type", "") or "")
	screen.status_text = str(event.get("action", event.get("type", "")) or "")
	screen.last_error = ""


def execute_observe_social_feed(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	_phone, screen, bridge, runtime_id, account_id, err = _screen_for_target(executor, ws, context, data, "ObserveSocialFeed")
	if err is not None:
		return err
	tick = _tick(ws)
	events = _invoke(bridge, runtime_id, "observe_feed", {"account_id": account_id, "limit": int(data.get("limit", 5) or 5), "tick": tick}, context)
	if any(is_execution_error_event(ev) for ev in events):
		_mark_screen_error(screen, events)
		return events
	event = _first_event(events, "SocialFeedObserved")
	if event is not None:
		_update_feed_screen(screen, event, tick)
	return events


def execute_observe_social_post(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	_phone, screen, bridge, runtime_id, account_id, err = _screen_for_target(executor, ws, context, data, "ObserveSocialPost")
	if err is not None:
		return err
	post_id = _post_id_from_screen(screen, data, "ObserveSocialPost")
	if isinstance(post_id, list):
		return post_id
	tick = _tick(ws)
	events = _invoke(bridge, runtime_id, "observe_post", {"account_id": account_id, "post_id": post_id, "tick": tick}, context)
	if any(is_execution_error_event(ev) for ev in events):
		_mark_screen_error(screen, events)
		return events
	event = _first_event(events, "SocialPostObserved")
	if event is not None:
		_update_post_screen(screen, event, tick)
	return events


def execute_create_social_post(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	_phone, screen, bridge, runtime_id, account_id, err = _screen_for_target(executor, ws, context, data, "CreateSocialPost")
	if err is not None:
		return err
	tick = _tick(ws)
	payload = {"account_id": account_id, "text": str(data.get("text", "") or ""), "tags": list(data.get("tags", []) or []), "tick": tick}
	events = _invoke(bridge, runtime_id, "create_post", payload, context)
	if any(is_execution_error_event(ev) for ev in events):
		_mark_screen_error(screen, events)
		return events
	event = _first_event(events, "SocialPostCreated")
	if event is not None:
		_update_action_status(screen, event, tick)
		screen.selected_post_id = str(event.get("post_id", "") or "")
	return events


def execute_interact_social_post(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	_phone, screen, bridge, runtime_id, account_id, err = _screen_for_target(executor, ws, context, data, "InteractSocialPost")
	if err is not None:
		return err
	post_id = _post_id_from_screen(screen, data, "InteractSocialPost")
	if isinstance(post_id, list):
		return post_id
	tick = _tick(ws)
	payload = {"account_id": account_id, "post_id": post_id, "action": str(data.get("action", "") or ""), "tick": tick}
	if "text" in data:
		payload["text"] = str(data.get("text", "") or "")
	events = _invoke(bridge, runtime_id, "interact_post", payload, context)
	if any(is_execution_error_event(ev) for ev in events):
		_mark_screen_error(screen, events)
		return events
	event = _first_event(events, "SocialPostInteracted")
	if event is not None:
		_update_action_status(screen, event, tick)
		screen.selected_post_id = post_id
	return events


def execute_follow_social_account(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	_phone, screen, bridge, runtime_id, account_id, err = _screen_for_target(executor, ws, context, data, "FollowSocialAccount")
	if err is not None:
		return err
	tick = _tick(ws)
	payload = {"account_id": account_id, "target_account_id": str(data.get("target_account_id", "") or ""), "tick": tick}
	events = _invoke(bridge, runtime_id, "follow_account", payload, context)
	if any(is_execution_error_event(ev) for ev in events):
		_mark_screen_error(screen, events)
		return events
	event = _first_event(events, "SocialAccountFollowed")
	if event is not None:
		_update_action_status(screen, event, tick)
	return events
