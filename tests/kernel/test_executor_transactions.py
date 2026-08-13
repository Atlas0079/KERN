from __future__ import annotations

import unittest

from KERN.effect_bundle import effect_bundle_from_raw
from KERN.executor.executor import WorldExecutor
from KERN.effects import EffectSpec, build_core_effect_catalog
from KERN.execution_errors import KernFailure
from KERN.external_runtime import ExternalRuntimeBridge
from KERN.models.components import ContainerComponent, ContainerSlot, PerceptionComponent, StatusComponent, TagComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState


class ExecutorTransactionTests(unittest.TestCase):
	@staticmethod
	def _bind_recordable(_ws, effect_data, context):
		return dict(effect_data), dict(context or {})

	@staticmethod
	def _execute_recordable(_executor, _ws, data, _context):
		return [{"type": "RecordableDone", "value": str(data.get("value", "") or "")}]

	@staticmethod
	def _record_recordable(_ws, data, _context, _events):
		return f"我看到了 {data.get('value')}"

	def test_add_tag_requires_existing_tag_component(self) -> None:
		ws = WorldState()
		ws.register_entity(Entity(entity_id="target", template_id="Thing", entity_name="Target"))
		executor = WorldExecutor()

		with self.assertRaisesRegex(KernFailure, "AddTag: TagComponent missing"):
			executor.execute(ws, {"effect": "AddTag", "target": "target", "tag": "marked"}, {"target_id": "target"})

	def test_effect_bundle_preserves_record_contract(self) -> None:
		bundle = effect_bundle_from_raw(
			{
				"effects": [{"effect": "EmitEvent", "event_type": "Probe", "payload": {}}],
				"record": {"mode": "auto", "target": "self"},
			}
		)

		self.assertEqual(bundle.to_dict()["record"], {"mode": "auto", "target": "self"})

	def test_invoke_bundle_is_part_of_executor_transaction_without_runtime_service(self) -> None:
		ws = WorldState()
		target = Entity(entity_id="target", template_id="Thing", entity_name="Target")
		target.add_component("TagComponent", TagComponent())
		ws.register_entity(target)
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{
						"effect": "InvokeBundle",
						"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "nested"}]},
					}
				]
			},
			{"target_id": "target"},
		)

		self.assertEqual([event["type"] for event in events], ["TagAdded", "AddTag", "InvokeBundle"])
		self.assertIn("nested", ws.get_entity_by_id("target").get_all_tags())

	def test_random_bundle_returns_child_events_without_runtime_service(self) -> None:
		ws = WorldState()
		target = Entity(entity_id="target", template_id="Thing", entity_name="Target")
		target.add_component("TagComponent", TagComponent())
		ws.register_entity(target)
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{
						"effect": "RandomBundle",
						"table_id": "certain",
						"entries": [
							{
								"id": "only",
								"weight": 1,
								"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "selected"}]},
							}
						],
					}
				]
			},
			{"target_id": "target"},
		)

		self.assertEqual([event["type"] for event in events], ["RandomBundleResolved", "TagAdded", "AddTag", "RandomBundle"])
		self.assertIn("selected", ws.get_entity_by_id("target").get_all_tags())

	def test_apply_to_query_returns_all_child_events_without_runtime_service(self) -> None:
		ws = WorldState()
		for entity_id, name in (("first", "First"), ("second", "Second")):
			entity = Entity(entity_id=entity_id, template_id="Thing", entity_name=name)
			entity.add_component("TagComponent", TagComponent())
			ws.register_entity(entity)
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{
						"effect": "ApplyToQuery",
						"query": {"from": "entities"},
						"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "matched"}]},
					}
				]
			},
			{},
		)

		self.assertEqual(
			[event["type"] for event in events],
			["TagAdded", "AddTag", "TagAdded", "AddTag", "QueryApplied", "ApplyToQuery"],
		)
		self.assertIn("matched", ws.get_entity_by_id("first").get_all_tags())
		self.assertIn("matched", ws.get_entity_by_id("second").get_all_tags())

	def test_bundle_auto_record_writes_agent_record_in_same_transaction(self) -> None:
		ws = WorldState()
		actor = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		actor.add_component("PerceptionComponent", PerceptionComponent())
		ws.register_entity(actor)
		catalog = build_core_effect_catalog()
		catalog.register(
			EffectSpec(
				effect_id="test:Recordable",
				binder=self._bind_recordable,
				handler=self._execute_recordable,
				recorder=self._record_recordable,
			)
		)
		executor = WorldExecutor(effect_catalog=catalog)

		executor.execute_bundle(
			ws,
			{"effects": [{"effect": "test:Recordable", "value": "页面"}], "record": {"mode": "auto", "target": "self"}},
			{"self_id": "agent"},
		)

		inbox = actor.get_component("PerceptionComponent").record_inbox
		self.assertEqual(len(inbox), 1)
		self.assertEqual(inbox[0]["content"], "我看到了 页面")
		self.assertEqual(inbox[0]["record_type"], "effect_record")

	def test_bundle_auto_record_rolls_back_with_failed_bundle(self) -> None:
		ws = WorldState()
		actor = Entity(entity_id="agent", template_id="Agent", entity_name="Agent")
		actor.add_component("PerceptionComponent", PerceptionComponent())
		ws.register_entity(actor)
		catalog = build_core_effect_catalog()
		catalog.register(
			EffectSpec(
				effect_id="test:Recordable",
				binder=self._bind_recordable,
				handler=self._execute_recordable,
				recorder=self._record_recordable,
			)
		)
		executor = WorldExecutor(effect_catalog=catalog)

		with self.assertRaises(KernFailure):
			executor.execute_bundle(
				ws,
				{
					"effects": [
						{"effect": "test:Recordable", "value": "页面"},
						{"effect": "UnknownEffect"},
					],
					"record": {"mode": "auto", "target": "self"},
				},
				{"self_id": "agent"},
			)

		self.assertEqual(actor.get_component("PerceptionComponent").record_inbox, [])


if __name__ == "__main__":
	unittest.main()
