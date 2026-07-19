from __future__ import annotations

import unittest

from KERN.executor.executor import WorldExecutor
from KERN.effects import EffectSpec, build_core_effect_catalog
from KERN.external_runtime import ExternalRuntimeBridge
from KERN.models.components import ContainerComponent, ContainerSlot, StatusComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState


class ExecutorTransactionTests(unittest.TestCase):
	def test_failed_outer_bundle_notifies_external_rollback_once(self) -> None:
		class Adapter:
			def __init__(self) -> None:
				self.rollback_contexts: list[dict] = []

			def rollback_bundle(self, context: dict) -> list[dict]:
				self.rollback_contexts.append(dict(context))
				return [{"type": "ExternalBundleRolledBack"}]

		adapter = Adapter()
		ws = WorldState()
		ws.services["external_runtime_bridge"] = ExternalRuntimeBridge({"social": adapter})
		catalog = build_core_effect_catalog().clone_mutable()
		catalog.register(
			EffectSpec(
				effect_id="TestExternalWrite",
				binder=lambda _ws, data, context: (dict(data), dict(context)),
				handler=lambda _executor, _ws, _data, _context: [{"type": "ExternalWriteAttempted"}],
				side_effect="external_compensatable",
			)
		)
		executor = WorldExecutor(effect_catalog=catalog)

		events = executor.execute_bundle(
			ws,
			{"effects": [{"effect": "TestExternalWrite"}, {"effect": "MissingEffect"}]},
			{},
		)

		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertEqual(len(adapter.rollback_contexts), 1)
		self.assertTrue(adapter.rollback_contexts[0]["transaction_id"])

	def test_irreversible_external_effect_must_be_last_in_a_bundle(self) -> None:
		catalog = build_core_effect_catalog().clone_mutable()
		catalog.register(
			EffectSpec(
				effect_id="TestIrreversible",
				binder=lambda _ws, data, context: (dict(data), dict(context)),
				handler=lambda _executor, _ws, _data, _context: [{"type": "IrreversibleExecuted"}],
				side_effect="external_irreversible",
			)
		)
		executor = WorldExecutor(effect_catalog=catalog)

		events = executor.execute_bundle(
			WorldState(),
			{"effects": [{"effect": "TestIrreversible"}, {"effect": "AddTag", "target": "self", "tag": "later"}]},
			{},
		)

		self.assertEqual(events[0]["code"], "EXTERNAL_IRREVERSIBLE_NOT_LAST")

	def test_external_bundle_rollback_receives_operations_from_its_transaction(self) -> None:
		class Adapter:
			def __init__(self) -> None:
				self.receipts: list[dict] = []

			def invoke(self, operation: str, payload: dict, _context: dict) -> list[dict]:
				return [{"type": "ExternalOperation", "operation": operation, "payload": dict(payload)}]

			def invoke_with_receipt(self, operation: str, payload: dict, context: dict) -> tuple[list[dict], dict]:
				return self.invoke(operation, payload, context), {"created_post_id": str(payload["id"])}

			def rollback_bundle(self, context: dict) -> list[dict]:
				self.receipts = [dict(item) for item in context["receipts"]]
				return [{"type": "ExternalBundleRolledBack"}]

		adapter = Adapter()
		ws = WorldState()
		ws.services["external_runtime_bridge"] = ExternalRuntimeBridge({"social": adapter})
		catalog = build_core_effect_catalog().clone_mutable()
		catalog.register(
			EffectSpec(
				effect_id="TestExternalOperation",
				binder=lambda _ws, data, context: (dict(data), dict(context)),
				handler=lambda _executor, world, _data, context: world.services["external_runtime_bridge"].invoke("social", "write", {"id": "post_01"}, context),
				side_effect="external_compensatable",
			)
		)

		WorldExecutor(effect_catalog=catalog).execute_bundle(
			ws,
			{"effects": [{"effect": "TestExternalOperation"}, {"effect": "MissingEffect"}]},
			{},
		)

		self.assertEqual(adapter.receipts, [{"runtime_id": "social", "receipt": {"created_post_id": "post_01"}}])

	def test_nested_irreversible_effect_waits_for_the_outer_transaction(self) -> None:
		executed: list[str] = []
		catalog = build_core_effect_catalog().clone_mutable()
		catalog.register(
			EffectSpec(
				effect_id="TestNestedIrreversible",
				binder=lambda _ws, data, context: (dict(data), dict(context)),
				handler=lambda _executor, _ws, _data, _context: executed.append("external") or [{"type": "ExternalExecuted"}],
				side_effect="external_irreversible",
			)
		)

		events = WorldExecutor(effect_catalog=catalog).execute_bundle(
			WorldState(),
			{
				"effects": [
					{"effect": "InvokeBundle", "bundle": {"effects": [{"effect": "TestNestedIrreversible"}]}},
					{"effect": "MissingEffect"},
				]
			},
			{},
		)

		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertEqual(executed, [])
	def test_invoke_bundle_is_part_of_executor_transaction_without_runtime_service(self) -> None:
		ws = WorldState()
		target = Entity(entity_id="target", template_id="Thing", entity_name="Target")
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

		self.assertEqual([event["type"] for event in events], ["TagAdded"])
		self.assertIn("nested", ws.get_entity_by_id("target").get_all_tags())

	def test_parent_failure_rolls_back_successful_invoke_bundle(self) -> None:
		ws = WorldState()
		ws.register_entity(Entity(entity_id="target", template_id="Thing", entity_name="Target"))
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{
						"effect": "InvokeBundle",
						"bundle": {"effects": [{"effect": "AddTag", "target": "target", "tag": "must_rollback"}]},
					},
					{"effect": "MissingEffect"},
				]
			},
			{"target_id": "target"},
		)

		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertTrue(events[0]["bundle_rolled_back"])
		self.assertNotIn("must_rollback", ws.get_entity_by_id("target").get_all_tags())

	def test_random_bundle_returns_child_events_without_runtime_service(self) -> None:
		ws = WorldState()
		ws.register_entity(Entity(entity_id="target", template_id="Thing", entity_name="Target"))
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

		self.assertEqual([event["type"] for event in events], ["RandomBundleResolved", "TagAdded"])
		self.assertIn("selected", ws.get_entity_by_id("target").get_all_tags())

	def test_apply_to_query_returns_all_child_events_without_runtime_service(self) -> None:
		ws = WorldState()
		ws.register_entity(Entity(entity_id="first", template_id="Thing", entity_name="First"))
		ws.register_entity(Entity(entity_id="second", template_id="Thing", entity_name="Second"))
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

		self.assertEqual([event["type"] for event in events], ["TagAdded", "TagAdded", "QueryApplied"])
		self.assertIn("matched", ws.get_entity_by_id("first").get_all_tags())
		self.assertIn("matched", ws.get_entity_by_id("second").get_all_tags())

	def test_bundle_rolls_back_prior_effect_when_later_effect_fails(self) -> None:
		ws = WorldState()
		target = Entity(entity_id="target", template_id="Thing", entity_name="Target")
		target.add_component("StatusComponent", StatusComponent())
		ws.register_entity(target)
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{"effect": "AddStatus", "target": "target", "status_id": "marked"},
					{"effect": "MissingEffect"},
				]
			},
			{"target_id": "target"},
		)

		restored_target = ws.get_entity_by_id("target")
		self.assertIsNotNone(restored_target)
		status = restored_target.get_component("StatusComponent")
		self.assertIsInstance(status, StatusComponent)
		self.assertFalse(status.has_status("marked"))
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertTrue(events[0]["bundle_rolled_back"])
		self.assertEqual(events[0]["failed_effect_index"], 1)

	def test_failed_move_entity_bundle_restores_source_location(self) -> None:
		ws = WorldState()
		loc = Location(location_id="room", location_name="Room", description="")
		ws.register_location(loc)
		item = Entity(entity_id="item", template_id="Item", entity_name="Item")
		box = Entity(entity_id="box", template_id="Box", entity_name="Box")
		box.add_component(
			"ContainerComponent",
			ContainerComponent(slots={"main": ContainerSlot(config={"capacity_count": 0}, items=[])}),
		)
		ws.register_entity(item)
		ws.register_entity(box)
		ws.ensure_entity_in_location("item", "room")
		ws.ensure_entity_in_location("box", "room")
		executor = WorldExecutor()

		events = executor.execute_bundle(
			ws,
			{
				"effects": [
					{
						"effect": "MoveEntity",
						"entity_ref": "param:entity_id",
						"from_ref": "param:source_id",
						"to_ref": "param:destination_id",
					}
				]
			},
			{"parameters": {"entity_id": "item", "source_id": "room", "destination_id": "box"}},
		)

		item_location = ws.get_location_of_entity("item")
		self.assertIsNotNone(item_location)
		self.assertEqual(item_location.location_id, "room")
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertTrue(events[0]["bundle_rolled_back"])

	def test_failed_single_effect_restores_world_state(self) -> None:
		ws = WorldState()
		loc = Location(location_id="room", location_name="Room", description="")
		ws.register_location(loc)
		item = Entity(entity_id="item", template_id="Item", entity_name="Item")
		box = Entity(entity_id="box", template_id="Box", entity_name="Box")
		box.add_component(
			"ContainerComponent",
			ContainerComponent(slots={"main": ContainerSlot(config={"capacity_count": 0}, items=[])}),
		)
		ws.register_entity(item)
		ws.register_entity(box)
		ws.ensure_entity_in_location("item", "room")
		ws.ensure_entity_in_location("box", "room")
		executor = WorldExecutor()

		events = executor.execute(
			ws,
			{
				"effect": "MoveEntity",
				"entity_ref": "param:entity_id",
				"from_ref": "param:source_id",
				"to_ref": "param:destination_id",
			},
			{"parameters": {"entity_id": "item", "source_id": "room", "destination_id": "box"}},
		)

		item_location = ws.get_location_of_entity("item")
		self.assertIsNotNone(item_location)
		self.assertEqual(item_location.location_id, "room")
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertTrue(events[0]["effect_rolled_back"])


if __name__ == "__main__":
	unittest.main()
