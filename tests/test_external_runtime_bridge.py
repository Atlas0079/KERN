from __future__ import annotations

import unittest

from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.executor.executor import WorldExecutor
from KERN.external_runtime import ExternalRuntimeBridge
from KERN.interaction.engine import InteractionEngine
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime


class MockExternalRuntime:
	def __init__(self) -> None:
		self.calls: list[dict[str, object]] = []

	def invoke(self, operation: str, payload: dict, context: dict) -> list[dict]:
		self.calls.append({"operation": operation, "payload": dict(payload), "context": dict(context)})
		return [
			{
				"type": "MockExternalOperationInvoked",
				"operation": operation,
				"text": str(payload.get("text", "")),
				"actor_id": str(context.get("self_id", "")),
			}
		]


class BadEventExternalRuntime:
	def invoke(self, operation: str, payload: dict, context: dict) -> list[object]:
		return [{"type": "GoodEvent"}, "bad"]


def _world() -> WorldState:
	ws = WorldState()
	loc = Location(location_id="room", location_name="Room", description="")
	ws.register_location(loc)
	ent = Entity(entity_id="agent_01", template_id="Agent", entity_name="Agent")
	ws.register_entity(ent)
	loc.add_entity_id(ent.entity_id)
	return ws


class ExternalRuntimeBridgeTests(unittest.TestCase):
	def test_invoke_routes_to_named_adapter(self) -> None:
		adapter = MockExternalRuntime()
		bridge = ExternalRuntimeBridge({"social": adapter})

		events = bridge.invoke("social", "send_message", {"text": "hello"}, {"self_id": "agent_01"})

		self.assertEqual(events[0]["type"], "MockExternalOperationInvoked")
		self.assertEqual(events[0]["operation"], "send_message")
		self.assertEqual(events[0]["text"], "hello")
		self.assertEqual(adapter.calls[0]["operation"], "send_message")

	def test_missing_adapter_returns_executor_error(self) -> None:
		bridge = ExternalRuntimeBridge()

		events = bridge.invoke("social", "send_message", {"text": "hello"}, {"self_id": "agent_01"})

		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertEqual(events[0]["code"], "EXTERNAL_RUNTIME_ADAPTER_MISSING")
		self.assertTrue(events[0]["recoverable"])

	def test_bad_adapter_event_shape_returns_contract_error(self) -> None:
		bridge = ExternalRuntimeBridge({"bad": BadEventExternalRuntime()})

		events = bridge.invoke("bad", "send_message", {}, {})

		self.assertEqual(events[0]["type"], "ExecutorError")
		self.assertEqual(events[0]["kind"], "contract")
		self.assertEqual(events[0]["code"], "EXTERNAL_RUNTIME_BAD_EVENT")

	def test_runtime_injects_external_runtime_bridge_service(self) -> None:
		adapter = MockExternalRuntime()
		runtime = KernRuntime(
			world_state=_world(),
			interaction_engine=InteractionEngine(recipe_db={}),
			executor=WorldExecutor(),
			action_provider=SimplePolicyActionProvider(),
			external_runtimes={"social": adapter},
			checkpoint_enabled=False,
		)

		runtime.advance_ticks(1)

		bridge = runtime.world_state.services.get("external_runtime_bridge")
		self.assertIsInstance(bridge, ExternalRuntimeBridge)
		events = bridge.invoke("social", "send_message", {"text": "hi"}, {"self_id": "agent_01"})
		self.assertEqual(events[0]["type"], "MockExternalOperationInvoked")
		self.assertEqual(adapter.calls[0]["payload"], {"text": "hi"})


if __name__ == "__main__":
	unittest.main()
