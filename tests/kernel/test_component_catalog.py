from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from KERN.component_catalog import ComponentCatalog, ComponentSpec, DataclassCodec, build_core_component_catalog
from KERN.data.archive import ArchiveRecorder, archive_state_from_world_state
from KERN.data.builder import build_world_state
from KERN.data.checkpoint import restore_world_state_from_checkpoint
from KERN.data.loader import DataBundle
from KERN.executor.executor import WorldExecutor
from KERN.models.components import CustomComponent, AgentWakePolicyComponent, TaskHostComponent
from KERN.models.location import Location
from KERN.models.world_state import WorldState
from KERN.runtime import KernRuntime
from tools.scenario_lint import lint_bundle


@dataclass
class ProbeComponent:
	level: int = 0
	label: str = ""


class ComponentCatalogTests(unittest.TestCase):
	def test_dataclass_codec_rejects_non_dataclass_type(self) -> None:
		with self.assertRaisesRegex(TypeError, "requires a dataclass type"):
			DataclassCodec(dict)

	def test_core_component_cannot_be_overridden_and_frozen_catalog_rejects_changes(self) -> None:
		catalog = build_core_component_catalog()
		with self.assertRaisesRegex(ValueError, "already registered: StatusComponent"):
			catalog.register(
				ComponentSpec(
					component_id="StatusComponent",
					component_type=ProbeComponent,
					codec=DataclassCodec(ProbeComponent),
					origin="scenario",
				)
			)

		catalog.freeze()
		with self.assertRaisesRegex(RuntimeError, "component catalog is frozen"):
			catalog.register(
				ComponentSpec(
					component_id="test:LateComponent",
					component_type=ProbeComponent,
					codec=DataclassCodec(ProbeComponent),
				)
			)

	def test_registered_dataclass_is_isolated_to_its_catalog(self) -> None:
		first = ComponentCatalog()
		second = ComponentCatalog()
		first.register(
			ComponentSpec(
				component_id="test:ProbeComponent",
				component_type=ProbeComponent,
				codec=DataclassCodec(ProbeComponent),
				origin="scenario",
			)
		)

		first_value = first.build("test:ProbeComponent", {"level": 3, "label": "ready"})
		second_value = second.build("test:ProbeComponent", {"level": 3, "label": "ready"})

		self.assertEqual(first_value, ProbeComponent(level=3, label="ready"))
		self.assertIsInstance(second_value, CustomComponent)
		self.assertEqual(second_value.data, {"level": 3, "label": "ready"})

	def test_registered_dataclass_round_trips_through_catalog(self) -> None:
		catalog = ComponentCatalog()
		catalog.register(
			ComponentSpec(
				component_id="test:ProbeComponent",
				component_type=ProbeComponent,
				codec=DataclassCodec(ProbeComponent),
				origin="scenario",
			)
		)
		component = catalog.build("test:ProbeComponent", {"level": 2, "label": "initial"})

		updated = catalog.apply_snapshot("test:ProbeComponent", component, {"level": 7, "label": "restored"})
		serialized = catalog.serialize("test:ProbeComponent", updated)
		rebuilt = catalog.build("test:ProbeComponent", serialized)

		self.assertIs(updated, component)
		self.assertEqual(serialized, {"level": 7, "label": "restored"})
		self.assertEqual(rebuilt, ProbeComponent(level=7, label="restored"))

	def test_unknown_component_round_trip_remains_flat_custom_data(self) -> None:
		catalog = build_core_component_catalog()
		component = catalog.build("scenario:UnknownComponent", {"value": 2, "label": "custom"})

		catalog.apply_snapshot("scenario:UnknownComponent", component, {"value": 5})
		serialized = catalog.serialize("scenario:UnknownComponent", component)
		rebuilt = catalog.build("scenario:UnknownComponent", serialized)

		self.assertIsInstance(rebuilt, CustomComponent)
		self.assertEqual(serialized, {"value": 5, "label": "custom"})
		self.assertEqual(rebuilt.data, serialized)

	def test_all_core_components_round_trip_default_state(self) -> None:
		catalog = build_core_component_catalog()

		for component_id in catalog.component_ids():
			with self.subTest(component_id=component_id):
				component = catalog.build(component_id, {})
				serialized = catalog.serialize(component_id, component)
				rebuilt = catalog.build(component_id, serialized)
				self.assertIsInstance(rebuilt, type(component))
				self.assertEqual(catalog.serialize(component_id, rebuilt), serialized)

	def test_world_build_and_archive_round_trip_use_same_catalog(self) -> None:
		catalog = build_core_component_catalog()
		catalog.register(
			ComponentSpec(
				component_id="test:ProbeComponent",
				component_type=ProbeComponent,
				codec=DataclassCodec(ProbeComponent),
				origin="scenario",
			)
		)
		templates = {
			"Probe": {
				"name": "Probe",
				"components": {"test:ProbeComponent": {"level": 2, "label": "template"}},
			}
		}
		world = {
			"world_state": {"current_tick": 0},
			"locations": [
				{
					"location_id": "room",
					"location_name": "Room",
					"entities": [
						{
							"instance_id": "probe_1",
							"template_id": "Probe",
							"component_overrides": {"test:ProbeComponent": {"level": 9, "label": "runtime"}},
						}
					],
				}
			],
			"paths": [],
		}

		built = build_world_state(world, templates, {}, component_catalog=catalog).world_state
		state = archive_state_from_world_state(built, component_catalog=catalog)
		rebuilt = build_world_state(state, templates, {}, component_catalog=catalog).world_state
		component = rebuilt.get_entity_by_id("probe_1").get_component("test:ProbeComponent")

		self.assertEqual(component, ProbeComponent(level=9, label="runtime"))
		with tempfile.TemporaryDirectory() as temp_dir:
			recorder = ArchiveRecorder(
				archive_dir=temp_dir,
				run_id="component_round_trip",
				component_catalog=catalog,
			)
			recorder.record_tick(built)
			restored = restore_world_state_from_checkpoint(
				Path(temp_dir) / "snapshots" / "snapshot_000000.json.gz",
				templates,
				component_catalog=catalog,
			)
			restored_component = restored.get_entity_by_id("probe_1").get_component("test:ProbeComponent")
			self.assertEqual(restored_component, ProbeComponent(level=9, label="runtime"))

	def test_container_codec_preserves_config_and_controls_item_restore(self) -> None:
		catalog = build_core_component_catalog()
		container = catalog.build(
			"ContainerComponent",
			{"slots": {"inventory": {"capacity_count": 2, "accepted_tags": ["food"]}}},
		)
		patch = {
			"slots": {
				"inventory": {
					"config": {"transparent": True},
					"items": ["apple_1"],
				}
			}
		}

		catalog.apply_snapshot("ContainerComponent", container, patch, restore_container_items=False)
		self.assertEqual(container.slots["inventory"].items, [])
		catalog.apply_snapshot("ContainerComponent", container, patch, restore_container_items=True)
		serialized = catalog.serialize("ContainerComponent", container)

		self.assertEqual(container.slots["inventory"].items, ["apple_1"])
		self.assertEqual(serialized["slots"]["inventory"]["config"]["capacity_count"], 2)
		self.assertTrue(serialized["slots"]["inventory"]["config"]["transparent"])
		self.assertEqual(
			catalog.serialize("ContainerComponent", catalog.build("ContainerComponent", serialized)),
			serialized,
		)

	def test_agent_wake_policy_codec_preserves_rules_presets_and_runtime_state(self) -> None:
		catalog = build_core_component_catalog()
		wake_policy = catalog.build(
			"AgentWakePolicyComponent",
			{
				"rules": [
					{"type": "NoActiveTask", "priority": 20},
					{"type": "LowNutrition", "priority": 5, "threshold": 30},
				],
				"active_interrupt_preset_id": "careful",
				"interrupt_presets": {"careful": {"LowNutrition": {"threshold": 40}}},
				"interrupt_preset_descriptions": {"careful": "Careful mode"},
				"interrupt_runtime_state": {"LowNutrition": {"latched": True, "last_fire_tick": 8}},
				"_runtime_preset_id": "careful",
			},
		)
		serialized = catalog.serialize("AgentWakePolicyComponent", wake_policy)
		rebuilt = catalog.build("AgentWakePolicyComponent", serialized)

		self.assertIsInstance(rebuilt, AgentWakePolicyComponent)
		self.assertEqual([rule["type"] for rule in rebuilt.ruleset], ["LowNutrition", "NoActiveTask"])
		self.assertEqual(rebuilt.interrupt_runtime_state["LowNutrition"]["last_fire_tick"], 8)
		self.assertEqual(catalog.serialize("AgentWakePolicyComponent", rebuilt), serialized)

	def test_task_host_codec_preserves_tasks_and_lifecycle_bundles(self) -> None:
		catalog = build_core_component_catalog()
		host = catalog.build(
			"TaskHostComponent",
			{
				"tasks": {
					"task_1": {
						"task_id": "task_1",
						"task_type": "Cook",
						"target_entity_id": "fire_1",
						"progress": 2,
						"required_progress": 5,
						"multiple_entity": False,
						"assigned_agent_ids": [],
						"task_status": "Inactive",
						"parameters": {},
						"progressor_id": "Linear",
						"progressor_params": {},
						"start_bundle": {"effects": [{"effect": "AddTag", "target": "self", "tag": "started"}]},
						"tick_bundle": {"effects": [{"effect": "EmitEvent", "event_type": "Cooking"}]},
						"cleanup_bundle": {"effects": [{"effect": "RemoveTag", "target": "self", "tag": "started"}]},
						"completion_bundle": {"effects": [{"effect": "EmitEvent", "event_type": "Cooked"}]},
					}
				}
			},
		)
		serialized = catalog.serialize("TaskHostComponent", host)
		rebuilt = catalog.build("TaskHostComponent", serialized)

		self.assertIsInstance(rebuilt, TaskHostComponent)
		self.assertEqual(rebuilt.get_task("task_1").tick_bundle.effects[0]["event_type"], "Cooking")
		self.assertEqual(rebuilt.get_task("task_1").completion_bundle.effects[0]["event_type"], "Cooked")
		self.assertEqual(catalog.serialize("TaskHostComponent", rebuilt), serialized)

	def test_task_host_codec_requires_complete_task_data(self) -> None:
		catalog = build_core_component_catalog()

		with self.assertRaisesRegex(ValueError, "task data missing fields"):
			catalog.build(
				"TaskHostComponent",
				{"tasks": {"task_1": {"task_id": "task_1", "task_type": "Cook"}}},
			)

	def test_stateful_core_dataclasses_preserve_values(self) -> None:
		catalog = build_core_component_catalog()
		cases = {
			"MemoryComponent": {
				"short_term_queue": [{"content": "remember", "tick": 3}],
			},
			"StatusComponent": {"statuses": ["wet"], "expire_at_tick": {"wet": 15}},
		}

		for component_id, raw in cases.items():
			with self.subTest(component_id=component_id):
				component = catalog.build(component_id, raw)
				serialized = catalog.serialize(component_id, component)
				rebuilt = catalog.build(component_id, serialized)
				self.assertEqual(catalog.serialize(component_id, rebuilt), serialized)

	def test_runtime_and_executor_share_a_frozen_component_catalog(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		runtime = KernRuntime.from_config(
			project_root,
			"runtime_config.camping.package.smoke.json",
			validate=True,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
		)

		self.assertIs(runtime.component_catalog, runtime.executor.component_catalog)
		with self.assertRaisesRegex(RuntimeError, "component catalog is frozen"):
			runtime.component_catalog.register(
				ComponentSpec(
					component_id="test:LateComponent",
					component_type=ProbeComponent,
					codec=DataclassCodec(ProbeComponent),
				)
			)

	def test_create_entity_effect_uses_executors_component_catalog(self) -> None:
		catalog = build_core_component_catalog()
		catalog.register(
			ComponentSpec(
				component_id="test:ProbeComponent",
				component_type=ProbeComponent,
				codec=DataclassCodec(ProbeComponent),
				origin="scenario",
			)
		)
		templates = {
			"Probe": {
				"name": "Probe",
				"components": {"test:ProbeComponent": {"level": 4, "label": "spawned"}},
			}
		}
		ws = WorldState()
		ws.register_location(Location(location_id="room", location_name="Room"))
		executor = WorldExecutor(entity_templates=templates, component_catalog=catalog)

		events = executor.execute(
			ws,
			{
				"effect": "CreateEntity",
				"template": "Probe",
				"instance_id": "probe_spawned",
				"destination": {"type": "location", "target": "room"},
			},
			{},
		)
		component = ws.get_entity_by_id("probe_spawned").get_component("test:ProbeComponent")

		self.assertEqual(events[0]["type"], "EntityCreated")
		self.assertEqual(component, ProbeComponent(level=4, label="spawned"))

	def test_lint_uses_the_callers_component_catalog(self) -> None:
		project_root = Path(__file__).resolve().parents[2]
		catalog = build_core_component_catalog()
		catalog.register(
			ComponentSpec(
				component_id="test:ProbeComponent",
				component_type=ProbeComponent,
				codec=DataclassCodec(ProbeComponent),
				origin="scenario",
			)
		)
		templates = {
			"Probe": {
				"name": "Probe",
				"components": {"test:ProbeComponent": {"level": 1, "label": "lint"}},
			}
		}
		world = {
			"world_state": {"current_tick": 0},
			"locations": [
				{
					"location_id": "room",
					"location_name": "Room",
					"entities": [{"instance_id": "probe_1", "template_id": "Probe"}],
				}
			],
			"paths": [],
		}
		bundle = DataBundle(entity_templates=templates, recipes={}, reactions={"rules": []}, world=world)
		common = {
			"project_root": project_root,
			"config_path": project_root / "runtime_config.camping.package.smoke.json",
			"env": {},
			"bundle": bundle,
			"world_json": "World.json",
			"recipes_jsons": [],
			"reactions_jsons": [],
			"entities_dirs": [],
			"bundles_jsons": [],
		}

		custom_result = lint_bundle(**common, component_catalog=catalog)
		core_result = lint_bundle(**common, component_catalog=build_core_component_catalog())

		self.assertFalse(any("test:ProbeComponent" in issue.message for issue in custom_result.issues))
		self.assertTrue(any("custom component name" in issue.message and "test:ProbeComponent" in issue.message for issue in core_result.issues))


if __name__ == "__main__":
	unittest.main()
