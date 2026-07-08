from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from KERN.executor.executor import WorldExecutor
from KERN.external_runtime import ExternalRuntimeBridge
from KERN.external_runtimes import SQLiteSocialPlatformRuntime
from KERN.models.components import (
	AgentControlComponent,
	AgentSetting,
	ContainerComponent,
	ContainerSlot,
	DecisionArbiterComponent,
	MemoryComponent,
	ScreenComponent,
	SocialBehaviorComponent,
	StatusComponent,
	TagComponent,
)
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime


class OneCommandSocialProvider:
	def __init__(self, verb: str = "BrowseSocialFeed") -> None:
		self.calls: list[dict[str, Any]] = []
		self.verb = str(verb or "BrowseSocialFeed")

	def build_memory_patch_data(self, _ws_view: Any, _recipe_db: dict[str, Any], _actor_id: str) -> dict[str, Any] | None:
		return None

	def decide(
		self,
		ws_view: Any,
		_recipe_db: dict[str, Any],
		actor_id: str,
		reason: str,
		mode_context: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		self.calls.append(
			{
				"actor_id": actor_id,
				"reason": reason,
				"mode_context": dict(mode_context or {}),
				"ws_view": dict(ws_view or {}) if isinstance(ws_view, dict) else {},
			}
		)
		return {
			"type": "apply_commands",
			"commands": [
				{"verb": self.verb, "target_id": f"phone_{actor_id}", "parameters": {"limit": 1, "slot": 0}},
				{"verb": "CreateSocialPost", "target_id": f"phone_{actor_id}", "parameters": {"text": "should not execute"}},
			],
		}


def _add_agent_with_phone(ws: WorldState, agent_id: str, account_id: str, *, rate: float = 1.0) -> None:
	agent = Entity(entity_id=agent_id, template_id="Agent", entity_name=agent_id)
	agent.add_component("TagComponent", TagComponent(tags=["agent"]))
	agent.add_component("AgentSetting", AgentSetting(agent_name=agent_id))
	agent.add_component("AgentControlComponent", AgentControlComponent(provider_id="social_llm"))
	agent.add_component("DecisionArbiterComponent", DecisionArbiterComponent.from_template_data({}))
	agent.add_component("MemoryComponent", MemoryComponent())
	agent.add_component("SocialBehaviorComponent", SocialBehaviorComponent(base_activity_rate=rate))
	agent.add_component("StatusComponent", StatusComponent())
	agent.add_component("ContainerComponent", ContainerComponent(slots={"inventory": ContainerSlot(config={"capacity_count": 4}, items=[])}))
	ws.register_entity(agent)
	ws.get_location_by_id("room").add_entity_id(agent_id)

	phone_id = f"phone_{agent_id}"
	phone = Entity(entity_id=phone_id, template_id="Phone", entity_name=phone_id)
	phone.add_component("TagComponent", TagComponent(tags=["phone", "device"]))
	phone.add_component("ScreenComponent", ScreenComponent(runtime_id="social", account_id=account_id, app="social_platform"))
	ws.register_entity(phone)
	agent.get_component("ContainerComponent").slots["inventory"].items.append(phone_id)


def _world_with_two_social_agents(db_path: Path, *, provider_verb: str = "BrowseSocialFeed") -> tuple[WorldState, OneCommandSocialProvider]:
	ws = WorldState()
	ws.register_location(Location(location_id="room", location_name="Room", description=""))
	_add_agent_with_phone(ws, "agent_a", "acc_a", rate=1.0)
	_add_agent_with_phone(ws, "agent_b", "acc_b", rate=1.0)

	rt = SQLiteSocialPlatformRuntime(db_path, runtime_id="social")
	for aid, display in [("acc_a", "A"), ("acc_b", "B"), ("acc_seed", "Seed")]:
		rt.upsert_account(aid, display, interests={"rumor": 1.0})
	rt.invoke("create_post", {"account_id": "acc_seed", "post_id": "post_rumor", "text": "Seed rumor", "tags": ["rumor"], "tick": 0}, {})

	provider = OneCommandSocialProvider(provider_verb)
	from KERN.interaction.engine import InteractionEngine

	ws.services = {
		"interaction_engine": InteractionEngine(
			recipe_db={
				"browse": {
					"verb": "BrowseSocialFeed",
					"condition": {"type": "has_component", "target": "target", "component": "ScreenComponent"},
					"bundle": {"effects": [{"effect": "ObserveSocialFeed", "target": "target", "limit": "param:limit"}]},
				},
				"create": {
					"verb": "CreateSocialPost",
					"condition": {"type": "has_component", "target": "target", "component": "ScreenComponent"},
					"bundle": {"effects": [{"effect": "CreateSocialPost", "target": "target", "text": "param:text"}]},
				},
				"open": {
					"verb": "OpenSocialPost",
					"condition": {"type": "has_component", "target": "target", "component": "ScreenComponent"},
					"bundle": {
						"effects": [
							{"effect": "ObserveSocialPost", "target": "target", "slot": "param:slot"},
							{"effect": "AddStatus", "target": "self", "status_id": "social_action_cooldown", "duration_ticks": 2},
						]
					},
				},
			}
		),
		"action_providers": {"social_llm": provider},
		"default_action_provider": None,
		"external_runtime_bridge": ExternalRuntimeBridge({"social": rt}),
		"execute": lambda bundle, context: WorldExecutor().execute_bundle(ws, bundle, context),
	}
	return ws, provider


class SocialActivityGateTests(unittest.TestCase):
	def test_browse_feed_does_not_consume_social_time_or_trigger_cooldown(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, provider = _world_with_two_social_agents(Path(td) / "social.sqlite3")
			ws.game_time.total_ticks = 1
			events = WorldExecutor().execute(
				ws,
				{
					"effect": "SocialActivityGateTick",
					"provider_id": "social_llm",
					"max_agents_per_tick": 10,
					"max_actions_per_agent": 1,
				},
				{},
			)

			granted = [ev for ev in events if ev.get("type") == "SocialActivityOpportunityGranted"]
			self.assertEqual([ev["entity_id"] for ev in granted], ["agent_a", "agent_b"])
			self.assertEqual(len(provider.calls), 2)
			self.assertEqual([row["verb"] for row in ws.interaction_log], ["BrowseSocialFeed", "BrowseSocialFeed"])
			self.assertTrue(all(call["mode_context"].get("social_activity_opportunity") for call in provider.calls))
			self.assertFalse(ws.get_entity_by_id("agent_a").get_component("StatusComponent").has_status("social_action_cooldown"))

			ws.game_time.total_ticks = 2
			next_events = WorldExecutor().execute(
				ws,
				{"effect": "SocialActivityGateTick", "provider_id": "social_llm", "max_agents_per_tick": 10},
				{},
			)
			self.assertEqual(len([ev for ev in next_events if ev.get("type") == "SocialActivityOpportunityGranted"]), 2)
			self.assertEqual(len(provider.calls), 4)

	def test_open_post_consumes_social_time_and_triggers_cooldown(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			ws, provider = _world_with_two_social_agents(Path(td) / "social.sqlite3", provider_verb="OpenSocialPost")
			# Preload each phone screen so OpenSocialPost can resolve slot 0.
			for agent_id in ("agent_a", "agent_b"):
				WorldExecutor().execute(
					ws,
					{"effect": "ObserveSocialFeed", "target": f"phone_{agent_id}", "limit": 1},
					{"self_id": agent_id},
				)

			ws.game_time.total_ticks = 1
			events = WorldExecutor().execute(
				ws,
				{"effect": "SocialActivityGateTick", "provider_id": "social_llm", "max_agents_per_tick": 10},
				{},
			)

			granted = [ev for ev in events if ev.get("type") == "SocialActivityOpportunityGranted"]
			self.assertEqual([ev["entity_id"] for ev in granted], ["agent_a", "agent_b"])
			self.assertTrue(ws.get_entity_by_id("agent_a").get_component("StatusComponent").has_status("social_action_cooldown"))
			self.assertEqual([row["verb"] for row in ws.interaction_log], ["OpenSocialPost", "OpenSocialPost"])

			ws.game_time.total_ticks = 2
			cooldown_events = WorldExecutor().execute(
				ws,
				{"effect": "SocialActivityGateTick", "provider_id": "social_llm", "max_agents_per_tick": 10},
				{},
			)
			self.assertFalse([ev for ev in cooldown_events if ev.get("type") == "SocialActivityOpportunityGranted"])
			self.assertEqual(len(provider.calls), 2)

	def test_rumor_spread_config_uses_social_activity_gate_not_default_agent_control(self) -> None:
		project_root = Path(__file__).resolve().parents[1]
		with tempfile.TemporaryDirectory() as td:
			runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.rumor_spread.smoke.json",
				validate=True,
				configure_logging=False,
				overrides={
					"CHECKPOINT_EVERY_TICK": "0",
					"EXTERNAL_RUNTIMES_JSON": (
						'{"social":{"type":"sqlite_social_platform","db_path":"'
						+ str(Path(td) / "social.sqlite3").replace("\\", "\\\\")
						+ '","reset_db":true,"seed_json":"Data/RumorSpread/social_seed.json"}}'
					),
				},
			)

			rule_ids = [str(rule.get("id", "")) for rule in runtime.reaction_rules]
			self.assertIn("rumor_world_tick_social_activity_gate", rule_ids)
			self.assertNotIn("advance_tick_agent_control", rule_ids)
			self.assertIn("SocialActivityGateTick", {effect.get("effect") for rule in runtime.reaction_rules for effect in rule.get("bundle", {}).get("effects", [])})


if __name__ == "__main__":
	unittest.main()
