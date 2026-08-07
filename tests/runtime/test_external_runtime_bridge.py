from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from KERN.data.archive import ArchiveRecorder
from KERN.agent_workflow.simple_policy import SimplePolicyActionProvider
from KERN.executor.executor import WorldExecutor
from KERN.effects import EffectSpec, build_core_effect_catalog
from KERN.external_runtime import ExternalRuntimeBridge, ExternalRuntimeLifecycleError
from KERN.interaction.engine import InteractionEngine
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.package import package_identity
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


class CheckpointExternalRuntime:
	def __init__(self, fail: bool = False) -> None:
		self.fail = bool(fail)
		self.saved: list[dict] = []
		self.restored: list[dict] = []

	def save_checkpoint(self, context: dict) -> list[dict]:
		if self.fail:
			raise RuntimeError("save failed")
		self.saved.append(dict(context))
		return [{"type": "ExternalCheckpointSaved", "runtime_id": str(context.get("runtime_id", "")), "tick": int(context.get("tick", 0) or 0)}]

	def restore_checkpoint(self, context: dict) -> list[dict]:
		if self.fail:
			raise RuntimeError("restore failed")
		self.restored.append(dict(context))
		return [{"type": "ExternalCheckpointRestored", "runtime_id": str(context.get("runtime_id", "")), "tick": int(context.get("tick", 0) or 0)}]


class BundleLifecycleExternalRuntime:
	def __init__(self, fail_phase: str = "") -> None:
		self.fail_phase = str(fail_phase)
		self.calls: list[tuple[str, dict]] = []

	def commit_bundle(self, context: dict) -> list[dict]:
		self.calls.append(("bundle_commit", dict(context)))
		if self.fail_phase == "bundle_commit":
			raise RuntimeError("commit failed")
		return [{"type": "ExternalBundleCommitted"}]

	def rollback_bundle(self, context: dict) -> list[dict]:
		self.calls.append(("bundle_rollback", dict(context)))
		if self.fail_phase == "bundle_rollback":
			raise RuntimeError("rollback failed")
		return [{"type": "ExternalBundleRolledBack"}]


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

	def test_checkpoint_lifecycle_routes_to_named_adapters(self) -> None:
		adapter = CheckpointExternalRuntime()
		bridge = ExternalRuntimeBridge({"social": adapter})

		save_events = bridge.save_checkpoint({"run_id": "run_01", "tick": 3})
		restore_events = bridge.restore_checkpoint({"run_id": "run_01", "tick": 3})

		self.assertEqual(save_events[0]["type"], "ExternalCheckpointSaved")
		self.assertEqual(restore_events[0]["type"], "ExternalCheckpointRestored")
		self.assertEqual(adapter.saved[0]["runtime_id"], "social")
		self.assertEqual(adapter.restored[0]["runtime_id"], "social")
		self.assertEqual(adapter.saved[0]["run_id"], "run_01")

	def test_bundle_lifecycle_is_deterministic_and_carries_transaction_identity(self) -> None:
		first = BundleLifecycleExternalRuntime()
		second = BundleLifecycleExternalRuntime()
		bridge = ExternalRuntimeBridge({"zeta": second, "alpha": first})

		events = bridge.commit_bundle({"transaction_id": "tx_01", "receipts": [{"runtime_id": "alpha"}]})

		self.assertEqual([event["type"] for event in events], ["ExternalBundleCommitted", "ExternalBundleCommitted"])
		self.assertEqual(first.calls[0][1]["runtime_id"], "alpha")
		self.assertEqual(second.calls[0][1]["runtime_id"], "zeta")
		self.assertEqual(first.calls[0][1]["transaction_id"], "tx_01")

	def test_bundle_lifecycle_failure_is_a_typed_error(self) -> None:
		bridge = ExternalRuntimeBridge({"social": BundleLifecycleExternalRuntime(fail_phase="bundle_rollback")})

		with self.assertRaises(ExternalRuntimeLifecycleError) as caught:
			bridge.rollback_bundle({"transaction_id": "tx_02"})

		self.assertEqual(caught.exception.phase, "bundle_rollback")
		self.assertEqual(caught.exception.runtime_id, "social")

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

	def test_runtime_checkpoint_save_notifies_external_runtime(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			adapter = CheckpointExternalRuntime()
			runtime = KernRuntime(
				world_state=_world(),
				interaction_engine=InteractionEngine(recipe_db={}),
				executor=WorldExecutor(),
				action_provider=SimplePolicyActionProvider(),
				external_runtimes={"social": adapter},
				checkpoint_enabled=True,
				checkpoint_dir=td,
				checkpoint_snapshot_interval_ticks=1,
			)

			runtime.record_initial_state()

			self.assertEqual(len(adapter.saved), 1)
			self.assertEqual(adapter.saved[0]["tick"], 0)
			self.assertEqual(adapter.saved[0]["run_id"], runtime.run_id)

	def test_runtime_checkpoint_save_failure_interrupts(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			runtime = KernRuntime(
				world_state=_world(),
				interaction_engine=InteractionEngine(recipe_db={}),
				executor=WorldExecutor(),
				action_provider=SimplePolicyActionProvider(),
				external_runtimes={"social": CheckpointExternalRuntime(fail=True)},
				checkpoint_enabled=True,
				checkpoint_dir=td,
				checkpoint_snapshot_interval_ticks=1,
			)

			with self.assertRaises(RuntimeError):
				runtime.record_initial_state()
			self.assertTrue(runtime.is_terminal)
			with self.assertRaisesRegex(RuntimeError, "terminal"):
				runtime.advance_ticks(1)

	def test_from_config_restore_notifies_external_runtime_before_runtime_construction(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		with tempfile.TemporaryDirectory() as td:
			base_runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.camping.package.smoke.json",
				validate=False,
				configure_logging=False,
				overrides={"CHECKPOINT_EVERY_TICK": "0"},
			)
			recorder = ArchiveRecorder(
				archive_dir=td,
				run_id="restore_run",
				snapshot_interval_ticks=1,
				include_logs=True,
				package_identity={"package_identity": package_identity(base_runtime.loaded_packages)},
			)
			recorder.record_tick(base_runtime.world_state)
			adapter = CheckpointExternalRuntime()

			restored_runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.camping.package.smoke.json",
				validate=False,
				configure_logging=False,
				overrides={"CHECKPOINT_RESTORE_DIR": td, "CHECKPOINT_EVERY_TICK": "0"},
				external_runtimes={"social": adapter},
			)

			self.assertEqual(restored_runtime.world_state.game_time.total_ticks, 0)
			self.assertEqual(len(adapter.restored), 1)
			self.assertEqual(adapter.restored[0]["run_id"], "restore_run")
			self.assertEqual(adapter.restored[0]["tick"], 0)

	def test_from_config_restore_failure_interrupts(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		with tempfile.TemporaryDirectory() as td:
			base_runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.camping.package.smoke.json",
				validate=False,
				configure_logging=False,
				overrides={"CHECKPOINT_EVERY_TICK": "0"},
			)
			recorder = ArchiveRecorder(
				archive_dir=td,
				run_id="restore_run",
				snapshot_interval_ticks=1,
				include_logs=True,
				package_identity={"package_identity": package_identity(base_runtime.loaded_packages)},
			)
			recorder.record_tick(base_runtime.world_state)

			with self.assertRaises(RuntimeError):
				KernRuntime.from_config(
					project_root,
					"runtime_config.camping.package.smoke.json",
					validate=False,
					configure_logging=False,
					overrides={"CHECKPOINT_RESTORE_DIR": td, "CHECKPOINT_EVERY_TICK": "0"},
					external_runtimes={"social": CheckpointExternalRuntime(fail=True)},
				)

	def test_restore_output_conflict_is_rejected_before_external_restore(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		with tempfile.TemporaryDirectory() as td:
			base_runtime = KernRuntime.from_config(
				project_root,
				"runtime_config.camping.package.smoke.json",
				validate=False,
				configure_logging=False,
				overrides={"CHECKPOINT_EVERY_TICK": "0"},
			)
			recorder = ArchiveRecorder(
				archive_dir=td,
				run_id="restore_run",
				snapshot_interval_ticks=1,
				include_logs=True,
				package_identity={"package_identity": package_identity(base_runtime.loaded_packages)},
			)
			recorder.record_tick(base_runtime.world_state)
			adapter = CheckpointExternalRuntime()

			with self.assertRaisesRegex(ValueError, "CHECKPOINT_DIR must differ"):
				KernRuntime.from_config(
					project_root,
					"runtime_config.camping.package.smoke.json",
					validate=False,
					configure_logging=False,
					overrides={
						"CHECKPOINT_RESTORE_DIR": td,
						"CHECKPOINT_DIR": td,
						"CHECKPOINT_EVERY_TICK": "1",
					},
					external_runtimes={"social": adapter},
				)

			self.assertEqual(adapter.restored, [])


if __name__ == "__main__":
	unittest.main()
