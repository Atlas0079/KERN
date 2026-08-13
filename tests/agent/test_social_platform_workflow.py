from __future__ import annotations

import json
import threading
import unittest

from KERN.agent_workflow.contracts import ActionFeedback, EndTurn, SubmitAction, TurnFrame, TurnStart
from KERN.effects import build_core_effect_catalog
from KERN.execution_errors import KernFailure
from KERN.executor.executor import WorldExecutor
from KERN.models.components import MemoryComponent, PerceptionComponent
from KERN.models.entity import Entity
from KERN.models.world_state import WorldState
from Packages.SeaLevelSocialExperiment.components.identity import SocialIdentityComponent
from Packages.SocialPropagation.components.screen import ScreenComponent
from KERN.agent_workflow.social_platform import ActorPlatformBinding, SocialPlatformWorkflow


class _Schedule:
	def __init__(self, active: set[tuple[str, int]]) -> None:
		self.active = set(active)

	def is_active(self, actor_id: str, tick: int) -> bool:
		return (actor_id, tick) in self.active


class _Client:
	def __init__(self, response: str | list[str]) -> None:
		self.responses = list(response) if isinstance(response, list) else [response]
		self.calls: list[dict] = []

	def chat_text(self, **kwargs):
		self.calls.append(dict(kwargs))
		if not self.responses:
			raise AssertionError("unexpected social decision client call")
		return self.responses.pop(0)


class _BlockingClient:
	def __init__(self, response: str, ready: threading.Barrier) -> None:
		self.response = response
		self.ready = ready
		self.calls: list[int] = []

	def chat_text(self, **_kwargs):
		self.calls.append(threading.get_ident())
		self.ready.wait(timeout=5)
		return self.response


def _turn_start() -> TurnStart:
	return TurnStart(
		turn_id="tick:4:turn:0",
		tick=4,
		turn_index=0,
		actor_id="agent_001",
		wake_reason="NoActiveTask",
		mode="normal",
	)


def _frame(previous_action: ActionFeedback | None = None) -> TurnFrame:
	return TurnFrame(
		actor_id="agent_001",
		reason="NoActiveTask",
		mode_context={"location_secret": "must-not-reach-llm"},
		previous_action=previous_action,
	)


def _committed(intent: dict) -> ActionFeedback:
	return ActionFeedback(action_id="action-1", intent=dict(intent), status="committed")


def _page(*, include_experimental: bool = True) -> dict:
	items = [
		{
			"post_id": "background_001",
			"text": "一条背景帖子",
			"display_hashtags": ["公共议题"],
			"original_author_id": "background_author",
			"feed_item_kind": "original",
			"created_tick": 0,
			"section": "recommended",
			"position": 0,
			"like_count": 2,
			"comment_count": 1,
			"repost_count": 0,
			"viewer_has_liked": False,
			"viewer_has_reposted": False,
			"score": 999.0,
			"ranking_topics": ["private_topic"],
			"condition_id": "private_condition",
		}
	]
	if include_experimental:
		items.append(
			{
				"post_id": "experiment_001",
				"text": "海平面上升实验帖",
				"display_hashtags": ["海平面上升"],
				"original_author_id": "earth_voice",
				"feed_item_kind": "original",
				"created_tick": 0,
				"section": "recommended",
				"position": 1,
				"like_count": 3,
				"comment_count": 2,
				"repost_count": 1,
				"viewer_has_liked": False,
				"viewer_has_reposted": False,
			}
		)
	return {
		"feed_session_id": 17,
		"account_id": "account_001",
		"tick": 4,
		"feed_items": items,
	}


class SocialPlatformWorkflowTests(unittest.TestCase):
	def _workflow(self, *, active: bool, response: str, page: dict | None = None) -> tuple[SocialPlatformWorkflow, _Client, WorldState]:
		client = _Client(response)
		page_data = _page() if page is None else page
		ws = WorldState()
		agent = Entity(entity_id="agent_001", template_id="SocialExperimentAgent", entity_name="Agent")
		agent.add_component(
			"sea_level_social_experiment:SocialIdentityComponent",
			SocialIdentityComponent(
				profile_id="profile:agent_001",
				natural_language_background="我是一名关注公共议题的研究人员。",
				big_five={
					"openness": 0.8,
					"conscientiousness": 0.7,
					"extraversion": 0.4,
					"agreeableness": 0.6,
					"neuroticism": 0.3,
				},
			),
		)
		agent.add_component(
			"MemoryComponent",
			MemoryComponent(short_term_queue=[{"post_id": "older", "summary": "我此前看过一条气候新闻。"}]),
		)
		agent.add_component("PerceptionComponent", PerceptionComponent())
		phone = Entity(entity_id="phone_001", template_id="SocialExperimentPhone", entity_name="Phone")
		phone.add_component(
			"social_propagation:ScreenComponent",
			ScreenComponent(
				runtime_id="social_platform",
				account_id="account_001",
				view="feed",
				feed_items=[dict(item) for item in page_data["feed_items"]],
				feed_session_id=int(page_data["feed_session_id"]),
				updated_tick=int(page_data["tick"]),
			),
		)
		ws.register_entity(agent)
		ws.register_entity(phone)
		workflow = SocialPlatformWorkflow(
			activation_schedule=_Schedule({("agent_001", 4)} if active else set()),
			actor_bindings={"agent_001": ActorPlatformBinding(terminal_id="phone_001", account_id="account_001")},
			client=client,
			model="test-model",
			experimental_post_id="experiment_001",
		)
		return workflow, client, ws

	def test_inactive_session_ends_without_page_read_or_llm_call(self) -> None:
		workflow, client, ws = self._workflow(active=False, response="{}")

		step = workflow.begin_turn(ws, _turn_start()).next_step(ws, _frame())

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(step.meta["reason"], "not_scheduled")
		self.assertEqual(client.calls, [])

	def test_active_session_browses_before_reading_page(self) -> None:
		workflow, client, ws = self._workflow(active=True, response="{}")
		session = workflow.begin_turn(ws, _turn_start())

		step = session.next_step(ws, _frame())

		self.assertIsInstance(step, SubmitAction)
		self.assertEqual(
			step.intent,
			{"verb": "BrowseSocialFeed", "target_id": "phone_001", "parameters": {}},
		)
		self.assertEqual(client.calls, [])

	def test_page_without_experimental_post_still_calls_llm(self) -> None:
		response = json.dumps(
			{"actions": [], "decision_summary": "我看过这些内容，但暂时不打算互动。"},
			ensure_ascii=False,
		)
		workflow, client, ws = self._workflow(active=True, response=response, page=_page(include_experimental=False))
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		step = session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(step.meta["reason"], "no_action")
		self.assertEqual(len(client.calls), 1)

	def test_committed_social_action_rebuilds_perception_before_next_decision(self) -> None:
		responses = [
			json.dumps(
				{"actions": [{"post_id": "experiment_001", "action": "like"}], "decision_summary": "先点赞。"},
				ensure_ascii=False,
			),
			json.dumps(
				{"actions": [], "decision_summary": "已经点赞过这条帖子，暂时不继续互动。"},
				ensure_ascii=False,
			),
		]
		workflow, client, ws = self._workflow(active=True, response=responses)
		executor = WorldExecutor(effect_catalog=build_core_effect_catalog())
		ws.services = {"execute": lambda bundle, context: executor.execute_bundle(ws, bundle, context)}
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		like = session.next_step(ws, _frame(_committed(browse.intent)))
		perception = ws.get_entity_by_id("agent_001").get_component("PerceptionComponent")
		perception.enqueue_record(
			{
				"record_id": "record_like_001",
				"tick": 4,
				"actor_id": "agent_001",
				"record_type": "social_action",
				"content": "我给海平面上升实验帖点了赞。",
				"source_effect": "social_propagation:LikeVisiblePost",
			}
		)
		screen = ws.get_entity_by_id("phone_001").get_component("social_propagation:ScreenComponent")
		screen.feed_items[1]["viewer_has_liked"] = True
		screen.feed_items[1]["like_count"] = 4
		end = session.next_step(ws, _frame(_committed(like.intent)))

		self.assertEqual(like.intent, {"verb": "LikeSocialPost", "target_id": "phone_001", "parameters": {"post_id": "experiment_001"}})
		self.assertIsInstance(end, EndTurn)
		self.assertEqual(len(client.calls), 2)
		request_text = json.dumps(client.calls[0], ensure_ascii=False)
		self.assertNotIn("must-not-reach-llm", request_text)
		self.assertNotIn("hidden-world-entity", request_text)
		self.assertNotIn("private_topic", request_text)
		self.assertNotIn("private_condition", request_text)
		self.assertNotIn('"score"', request_text)
		second_request = json.loads(client.calls[1]["messages"][1]["content"])
		self.assertTrue(second_request["screen"]["feed_items"][1]["viewer_has_liked"])
		self.assertTrue(any(item.get("record_type") == "social_action" for item in second_request["recent_social_memory"]))

	def test_rejected_social_action_ends_session_without_second_decision(self) -> None:
		response = json.dumps(
			{"actions": [{"post_id": "experiment_001", "action": "like"}], "decision_summary": "点赞。"},
			ensure_ascii=False,
		)
		workflow, client, ws = self._workflow(active=True, response=response)
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())
		like = session.next_step(ws, _frame(_committed(browse.intent)))
		rejected = ActionFeedback(
			action_id="action-2",
			intent=dict(like.intent),
			status="rejected",
			rejection_code="ALREADY_LIKED",
			message="already liked",
		)

		step = session.next_step(ws, _frame(rejected))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(step.meta["reason"], "social_action_rejected")
		self.assertEqual(len(client.calls), 1)

	def test_empty_action_decision_is_distinct_from_inactive_turn(self) -> None:
		response = json.dumps(
			{"actions": [], "decision_summary": "我看过这些内容，但暂时不打算互动。"},
			ensure_ascii=False,
		)
		workflow, client, ws = self._workflow(active=True, response=response)
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		step = session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(step.meta["reason"], "no_action")
		self.assertEqual(len(client.calls), 1)

	def test_parallel_prepared_social_decision_keeps_memory_patch_in_caller_thread(self) -> None:
		response = json.dumps(
			{"actions": [], "decision_summary": "我看过这些内容，但暂时不打算互动。"},
			ensure_ascii=False,
		)
		workflow, client, ws = self._workflow(active=True, response=response)
		ws.game_time.total_ticks = 4
		agent = ws.get_entity_by_id("agent_001")
		perception = agent.get_component("PerceptionComponent")
		perception.enqueue_record(
			{
				"record_id": "record_001",
				"tick": 3,
				"actor_id": "agent_001",
				"record_type": "social_feed_view",
				"content": "我刚刚看到一条海平面帖子。",
			}
		)
		executor = WorldExecutor(effect_catalog=build_core_effect_catalog())
		ws.services = {"execute": lambda bundle, context: executor.execute_bundle(ws, bundle, context)}
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())
		caller_thread = threading.get_ident()

		prepared = session.prepare_parallel_next_step(ws, _frame(_committed(browse.intent)))

		self.assertEqual(threading.get_ident(), caller_thread)
		self.assertEqual(perception.record_inbox, [])
		self.assertEqual(len(client.calls), 0)
		step = prepared.complete(prepared.run())
		self.assertIsInstance(step, EndTurn)
		self.assertEqual(step.meta["reason"], "no_action")
		self.assertEqual(len(client.calls), 1)

	def test_prepared_social_page_decisions_can_wait_concurrently(self) -> None:
		from concurrent.futures import ThreadPoolExecutor

		response = json.dumps(
			{"actions": [], "decision_summary": "我看过这些内容，但暂时不打算互动。"},
			ensure_ascii=False,
		)
		barrier = threading.Barrier(2)
		client = _BlockingClient(response, barrier)
		workflow, _old_client, ws = self._workflow(active=True, response=response)
		workflow.client = client
		start = _turn_start()
		binding = ActorPlatformBinding(terminal_id="phone_001", account_id="account_001")
		perception, card_by_id = workflow._decision_perception(ws, start, binding)
		prepared_a = workflow.prepare_page_decision(perception, card_by_id, start, binding)
		prepared_b = workflow.prepare_page_decision(perception, card_by_id, start, binding)

		with ThreadPoolExecutor(max_workers=2) as pool:
			result_a = pool.submit(prepared_a.run)
			result_b = pool.submit(prepared_b.run)
			self.assertEqual(prepared_a.complete(result_a.result())[1]["reason"], "no_action")
			self.assertEqual(prepared_b.complete(result_b.result())[1]["reason"], "no_action")

		self.assertEqual(len(client.calls), 2)
		self.assertEqual(len(set(client.calls)), 2)

	def test_social_decision_consumes_record_inbox_into_recent_memory(self) -> None:
		response = json.dumps(
			{"actions": [], "decision_summary": "我看过这些内容，但暂时不打算互动。"},
			ensure_ascii=False,
		)
		workflow, client, ws = self._workflow(active=True, response=response)
		ws.game_time.total_ticks = 4
		agent = ws.get_entity_by_id("agent_001")
		perception = agent.get_component("PerceptionComponent")
		perception.enqueue_record(
			{
				"record_id": "record_001",
				"tick": 3,
				"time_str": "tick 3",
				"actor_id": "agent_001",
				"record_type": "social_action",
				"content": "我刚刚点赞过一条海平面帖子。",
			}
		)
		executor = WorldExecutor(effect_catalog=build_core_effect_catalog())
		ws.services = {"execute": lambda bundle, context: executor.execute_bundle(ws, bundle, context)}
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		step = session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(len(client.calls), 1)
		request = json.loads(client.calls[0]["messages"][1]["content"])
		memory = request["recent_social_memory"]
		self.assertTrue(any("点赞" in str(item) for item in memory))
		self.assertEqual(perception.record_inbox, [])

	def test_social_memory_consolidation_triggers_at_40_and_keeps_latest_10(self) -> None:
		responses = [
			json.dumps(
				{
					"mid_term_summaries": [{"summary": "我较早时看过海平面风险内容。", "tick_start": 1, "tick_end": 2}],
					"decision_summary": "整理较早记忆。",
				},
				ensure_ascii=False,
			),
			json.dumps({"actions": [], "decision_summary": "暂不互动。"}, ensure_ascii=False),
		]
		client = _Client("")
		client.chat_text = lambda **kwargs: responses.pop(0)
		workflow, _unused_client, ws = self._workflow(active=True, response="{}")
		workflow.client = client
		workflow.consolidation_trigger_entries = 40
		workflow.consolidation_keep_recent_entries = 10
		ws.game_time.total_ticks = 4
		agent = ws.get_entity_by_id("agent_001")
		mem = agent.get_component("MemoryComponent")
		mem.short_term_queue = [
			{"record_id": f"record_{idx:02d}", "tick": idx, "content": f"第 {idx} 条浏览。"}
			for idx in range(40)
		]
		executor = WorldExecutor(effect_catalog=build_core_effect_catalog())
		ws.services = {"execute": lambda bundle, context: executor.execute_bundle(ws, bundle, context)}
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		step = session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual([item.get("record_id") for item in mem.short_term_queue], [f"record_{idx:02d}" for idx in range(30, 40)])
		self.assertEqual(mem.mid_term_queue[0]["summary"], "我较早时看过海平面风险内容。")
		self.assertEqual(responses, [])

	def test_social_memory_consolidation_does_not_trigger_below_40(self) -> None:
		response = json.dumps({"actions": [], "decision_summary": "暂不互动。"}, ensure_ascii=False)
		workflow, client, ws = self._workflow(active=True, response=response)
		workflow.consolidation_trigger_entries = 40
		workflow.consolidation_keep_recent_entries = 10
		agent = ws.get_entity_by_id("agent_001")
		mem = agent.get_component("MemoryComponent")
		mem.short_term_queue = [
			{"record_id": f"record_{idx:02d}", "tick": idx, "content": f"第 {idx} 条浏览。"}
			for idx in range(39)
		]
		executor = WorldExecutor(effect_catalog=build_core_effect_catalog())
		ws.services = {"execute": lambda bundle, context: executor.execute_bundle(ws, bundle, context)}
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		step = session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertIsInstance(step, EndTurn)
		self.assertEqual(len(client.calls), 1)
		self.assertEqual(len(mem.short_term_queue), 39)
		self.assertEqual(mem.mid_term_queue, [])

	def test_invalid_json_is_a_terminal_workflow_parse_failure(self) -> None:
		workflow, _client, ws = self._workflow(active=True, response="not-json")
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		with self.assertRaises(KernFailure) as raised:
			session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertEqual(raised.exception.code, "WORKFLOW_OUTPUT_PARSE_FAILED")

	def test_invisible_post_is_a_terminal_output_contract_failure(self) -> None:
		response = json.dumps(
			{"actions": [{"post_id": "not_visible", "action": "like"}], "decision_summary": "点赞。"},
			ensure_ascii=False,
		)
		workflow, _client, ws = self._workflow(active=True, response=response)
		session = workflow.begin_turn(ws, _turn_start())
		browse = session.next_step(ws, _frame())

		with self.assertRaises(KernFailure) as raised:
			session.next_step(ws, _frame(_committed(browse.intent)))

		self.assertEqual(raised.exception.code, "WORKFLOW_OUTPUT_CONTRACT_INVALID")


if __name__ == "__main__":
	unittest.main()
