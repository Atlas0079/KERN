from __future__ import annotations

from typing import Any

from KERN.effects import EffectSpec
from KERN.entity_ref_resolver import resolve_entity_id
from KERN.execution_errors import ERROR_KIND_BUSINESS, ERROR_KIND_CONTRACT, executor_error
from KERN.executor._effect_binder import BindError, _base_bind, _require_int, _require_str, _resolve_param_token
from KERN.package_definitions import package_effect


SCREEN_COMPONENT_ID = "social_propagation:ScreenComponent"
PUBLIC_CARD_FIELDS = (
	"feed_item_kind",
	"post_id",
	"original_author_id",
	"created_tick",
	"reposted_by_account_id",
	"reposted_tick",
	"text",
	"display_hashtags",
	"repost_count",
	"like_count",
	"comment_count",
	"viewer_has_liked",
	"viewer_has_reposted",
	"source_kind",
	"source_account_id",
	"section",
	"position",
)


def _terminal_id(params: dict[str, Any], effect_type: str, context: dict[str, Any]) -> str:
	terminal_ref = _require_str(params, effect_type, "terminal")
	terminal_id = resolve_entity_id(terminal_ref, context, allow_literal=False)
	if not terminal_id:
		raise BindError(effect_type, ["terminal"])
	return terminal_id


def _bind_refresh_feed(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	limit = _require_int(params, effect_type, "limit", ctx)
	if limit < 1 or limit > 8:
		raise BindError(effect_type, ["limit"])
	return {"effect": effect_type, "terminal_id": _terminal_id(params, effect_type, ctx), "limit": limit}, ctx


def _bind_visible_post_action(effect_data: dict[str, Any], context: dict[str, Any], *, text_required: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	post_id = str(_resolve_param_token(params.get("post_id", ""), ctx) or "").strip()
	if not post_id:
		raise BindError(effect_type, ["post_id"])
	out = {"effect": effect_type, "terminal_id": _terminal_id(params, effect_type, ctx), "post_id": post_id}
	if text_required:
		text = str(_resolve_param_token(params.get("text", ""), ctx) or "").strip()
		if not text:
			raise BindError(effect_type, ["text"])
		out["text"] = text
	elif "text" in params:
		out["text"] = str(_resolve_param_token(params.get("text", ""), ctx) or "")
	return out, ctx


def _bind_repost_visible_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	return _bind_visible_post_action(effect_data, context)


def _bind_like_visible_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	return _bind_visible_post_action(effect_data, context)


def _bind_comment_on_visible_post(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	return _bind_visible_post_action(effect_data, context, text_required=True)


def _bind_observe_metrics(_ws: Any, effect_data: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	effect_type, params, ctx = _base_bind(effect_data, context)
	runtime_id = _require_str(params, effect_type, "runtime_id")
	return {"effect": effect_type, "runtime_id": runtime_id}, ctx


def _terminal_context(ws: Any, terminal_id: str, context: dict[str, Any]) -> tuple[Any, Any, Any, int]:
	actor_id = str(context.get("self_id", "") or "").strip()
	actor = ws.get_entity_by_id(actor_id) if actor_id and hasattr(ws, "get_entity_by_id") else None
	terminal = ws.get_entity_by_id(terminal_id) if hasattr(ws, "get_entity_by_id") else None
	if actor is None or terminal is None:
		executor_error("social action requires existing actor and terminal", kind=ERROR_KIND_BUSINESS, code="SOCIAL_TERMINAL_MISSING")
	container = actor.get_component("ContainerComponent") if hasattr(actor, "get_component") else None
	item_ids = set(container.get_all_item_ids()) if container is not None and hasattr(container, "get_all_item_ids") else set()
	if terminal_id not in item_ids:
		executor_error("social terminal must be in the acting Agent's inventory", kind=ERROR_KIND_BUSINESS, code="SOCIAL_TERMINAL_NOT_OWNED")
	screen = terminal.get_component(SCREEN_COMPONENT_ID) if hasattr(terminal, "get_component") else None
	if screen is None:
		executor_error("social terminal has no ScreenComponent", kind=ERROR_KIND_CONTRACT, code="SOCIAL_SCREEN_MISSING")
	services = getattr(ws, "services", {}) or {}
	bridge = services.get("external_runtime_bridge") if isinstance(services, dict) else None
	if bridge is None or not bridge.has_adapter(str(screen.runtime_id)):
		executor_error("social runtime adapter is unavailable", kind=ERROR_KIND_CONTRACT, code="SOCIAL_RUNTIME_MISSING")
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	return screen, bridge, terminal, tick


def _visible_card(screen: Any, post_id: str, tick: int) -> dict[str, Any]:
	if int(getattr(screen, "updated_tick", -1)) != int(tick):
		executor_error("social screen is stale; refresh the feed before interacting", kind=ERROR_KIND_BUSINESS, code="SOCIAL_SCREEN_STALE")
	for card in list(getattr(screen, "feed_items", []) or []):
		if isinstance(card, dict) and str(card.get("post_id", "") or "") == post_id:
			return dict(card)
	executor_error("post is not visible on the current social screen", kind=ERROR_KIND_BUSINESS, code="SOCIAL_POST_NOT_VISIBLE")


def _screen_from_terminal(ws: Any, terminal_id: str) -> Any:
	terminal = ws.get_entity_by_id(str(terminal_id)) if hasattr(ws, "get_entity_by_id") else None
	screen = terminal.get_component(SCREEN_COMPONENT_ID) if terminal is not None and hasattr(terminal, "get_component") else None
	return screen


def _card_label(card: dict[str, Any], post_id: str) -> str:
	title = str(card.get("title", "") or "").strip()
	if title:
		return f"标题是《{title}》"
	text = str(card.get("text", "") or "").strip()
	if text:
		summary = text[:48] + ("..." if len(text) > 48 else "")
		return f"正文开头是“{summary}”"
	return f"ID 为 {post_id}"


def _public_card_summary(card: dict[str, Any]) -> str:
	post_id = str(card.get("post_id", "") or "")
	hashtags = [str(item) for item in list(card.get("display_hashtags", []) or []) if str(item)]
	hashtags_text = f"；hashtag：{', '.join(hashtags)}" if hashtags else ""
	repost_text = ""
	if str(card.get("reposted_by_account_id", "") or ""):
		repost_text = f"；直接转发者 {card.get('reposted_by_account_id')}，转发 tick {card.get('reposted_tick')}"
	source_text = ""
	if str(card.get("source_kind", "") or "") or str(card.get("source_account_id", "") or ""):
		source_text = f"；来源 {card.get('source_kind', '')}/{card.get('source_account_id', '')}"
	return (
		f"位置 {card.get('position')}：{_card_label(card, post_id)}；原作者 {card.get('original_author_id')}"
		f"；类型 {card.get('feed_item_kind')}{repost_text}{source_text}{hashtags_text}"
		f"；点赞 {card.get('like_count', 0)}，评论 {card.get('comment_count', 0)}，转发 {card.get('repost_count', 0)}"
		f"；我已点赞 {bool(card.get('viewer_has_liked', False))}，我已转发 {bool(card.get('viewer_has_reposted', False))}"
	)


def record_refresh_feed(ws: Any, data: dict[str, Any], _context: dict[str, Any], _events: list[dict[str, Any]]) -> str:
	screen = _screen_from_terminal(ws, str(data.get("terminal_id", "") or ""))
	if screen is None:
		return ""
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	cards = [dict(item) for item in list(getattr(screen, "feed_items", []) or []) if isinstance(item, dict)]
	card_lines = "；".join(_public_card_summary(card) for card in cards)
	return f"我在 tick {tick} 打开推荐页，feed_session_id={int(getattr(screen, 'feed_session_id', 0) or 0)}，看到了 {len(cards)} 张卡片：{card_lines}"


def record_like_visible_post(ws: Any, data: dict[str, Any], _context: dict[str, Any], _events: list[dict[str, Any]]) -> str:
	screen = _screen_from_terminal(ws, str(data.get("terminal_id", "") or ""))
	if screen is None:
		return ""
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	post_id = str(data.get("post_id", "") or "")
	card = _visible_card(screen, post_id, tick)
	return f"我给{_card_label(card, post_id)}的帖子点了赞。"


def record_comment_on_visible_post(ws: Any, data: dict[str, Any], _context: dict[str, Any], _events: list[dict[str, Any]]) -> str:
	screen = _screen_from_terminal(ws, str(data.get("terminal_id", "") or ""))
	if screen is None:
		return ""
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	post_id = str(data.get("post_id", "") or "")
	card = _visible_card(screen, post_id, tick)
	comment = str(data.get("text", "") or "").strip()
	return f"我给{_card_label(card, post_id)}的帖子评论：{comment}"


def record_repost_visible_post(ws: Any, data: dict[str, Any], _context: dict[str, Any], _events: list[dict[str, Any]]) -> str:
	screen = _screen_from_terminal(ws, str(data.get("terminal_id", "") or ""))
	if screen is None:
		return ""
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	post_id = str(data.get("post_id", "") or "")
	card = _visible_card(screen, post_id, tick)
	text = str(data.get("text", "") or "").strip()
	if text:
		return f"我转发了{_card_label(card, post_id)}的帖子，并写道：{text}"
	return f"我转发了{_card_label(card, post_id)}的帖子。"


def execute_refresh_feed(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	screen, bridge, _terminal, tick = _terminal_context(ws, str(data["terminal_id"]), context)
	limit = int(data["limit"])
	payload = {"account_id": str(screen.account_id), "tick": tick, "limit": limit}
	feed_events = bridge.invoke(str(screen.runtime_id), "open_feed_session", payload, context)
	if not feed_events or feed_events[0].get("type") != "SocialFeedOpened":
		executor_error("social runtime returned an invalid feed session", kind=ERROR_KIND_CONTRACT, code="SOCIAL_FEED_RESULT_INVALID")
	opened = dict(feed_events[0])
	raw_cards = opened.get("feed_items", [])
	if not isinstance(raw_cards, list):
		executor_error("social feed_items must be an array", kind=ERROR_KIND_CONTRACT, code="SOCIAL_FEED_RESULT_INVALID")
	public_cards: list[dict[str, Any]] = []
	for raw_card in raw_cards:
		if not isinstance(raw_card, dict):
			executor_error("social feed card must be an object", kind=ERROR_KIND_CONTRACT, code="SOCIAL_FEED_RESULT_INVALID")
		public_card = {field: raw_card.get(field) for field in PUBLIC_CARD_FIELDS}
		public_card["feed_session_id"] = int(raw_card.get("feed_session_id"))
		public_card["exposure_id"] = int(raw_card.get("exposure_id"))
		public_cards.append(public_card)
	screen.view = "feed"
	screen.title = "推荐"
	screen.feed_items = public_cards
	screen.current_post = None
	screen.selected_post_id = ""
	screen.feed_session_id = int(opened.get("feed_session_id"))
	screen.cursor = len(public_cards)
	screen.updated_tick = tick
	screen.status_text = f"已加载 {len(public_cards)} 条内容"
	screen.last_event_type = "SocialFeedOpened"
	screen.last_error = ""
	opened["feed_items"] = [dict(item) for item in public_cards]
	return [opened, *[dict(item) for item in feed_events[1:]]]


def _execute_visible_interaction(ws: Any, data: dict[str, Any], context: dict[str, Any], operation: str, event_type: str) -> list[dict[str, Any]]:
	screen, bridge, _terminal, tick = _terminal_context(ws, str(data["terminal_id"]), context)
	post_id = str(data["post_id"])
	card = _visible_card(screen, post_id, tick)
	payload = {
		"account_id": str(screen.account_id),
		"post_id": post_id,
		"source_exposure_id": int(card.get("exposure_id")),
		"tick": tick,
	}
	if "text" in data:
		payload["text"] = str(data.get("text", "") or "")
	events = bridge.invoke(str(screen.runtime_id), operation, payload, context)
	if len(events) != 1 or events[0].get("type") != event_type:
		executor_error(f"social runtime returned an invalid {operation} result", kind=ERROR_KIND_CONTRACT, code="SOCIAL_INTERACTION_RESULT_INVALID")
	screen.selected_post_id = post_id
	if operation == "like":
		card["viewer_has_liked"] = True
		card["like_count"] = int(card.get("like_count", 0)) + 1
	elif operation == "repost":
		card["viewer_has_reposted"] = True
		card["repost_count"] = int(card.get("repost_count", 0)) + 1
	else:
		card["comment_count"] = int(card.get("comment_count", 0)) + 1
	for index, item in enumerate(list(screen.feed_items or [])):
		if isinstance(item, dict) and str(item.get("post_id", "") or "") == post_id:
			screen.feed_items[index] = card
			break
	screen.status_text = {"repost": "已转发", "like": "已点赞", "comment": "已评论"}[operation]
	screen.last_event_type = event_type
	screen.last_error = ""
	return events


def execute_repost_visible_post(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return _execute_visible_interaction(ws, data, context, "repost", "SocialPostReposted")


def execute_like_visible_post(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return _execute_visible_interaction(ws, data, context, "like", "SocialPostLiked")


def execute_comment_on_visible_post(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	return _execute_visible_interaction(ws, data, context, "comment", "SocialCommentCreated")


def execute_observe_metrics(_executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	services = getattr(ws, "services", {}) or {}
	bridge = services.get("external_runtime_bridge") if isinstance(services, dict) else None
	runtime_id = str(data["runtime_id"])
	if bridge is None or not bridge.has_adapter(runtime_id):
		executor_error("social runtime adapter is unavailable", kind=ERROR_KIND_CONTRACT, code="SOCIAL_RUNTIME_MISSING")
	tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
	return bridge.invoke(runtime_id, "metrics", {"tick": tick}, context)


@package_effect(EffectSpec(effect_id="social_propagation:RefreshFeed", module="effects.social", side_effect="external_transactional", emits=("SocialFeedOpened", "SocialPostExposed")))
def refresh_feed_effect() -> None:
	pass


@package_effect(EffectSpec(effect_id="social_propagation:RepostVisiblePost", module="effects.social", side_effect="external_transactional", emits=("SocialPostReposted",)))
def repost_visible_post_effect() -> None:
	pass


@package_effect(EffectSpec(effect_id="social_propagation:LikeVisiblePost", module="effects.social", side_effect="external_transactional", emits=("SocialPostLiked",)))
def like_visible_post_effect() -> None:
	pass


@package_effect(EffectSpec(effect_id="social_propagation:CommentOnVisiblePost", module="effects.social", side_effect="external_transactional", emits=("SocialCommentCreated",)))
def comment_on_visible_post_effect() -> None:
	pass


@package_effect(EffectSpec(effect_id="social_propagation:ObserveMetrics", module="effects.social", emits=("SocialMetricsObserved",)))
def observe_metrics_effect() -> None:
	pass
