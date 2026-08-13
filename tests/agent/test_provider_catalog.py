from __future__ import annotations

import json
import unittest
from pathlib import Path

from KERN.agent_workflow.provider_catalog import build_workflow_catalog
from KERN.agent_workflow.provider_routing import resolve_workflow_provider
from KERN.agent_workflow.registry import WorkflowRegistry
from KERN.models.components import AgentControlComponent
from KERN.runtime import KernRuntime


class ProviderRoutingTests(unittest.TestCase):
	def test_explicit_then_controller_then_default_precedence(self) -> None:
		default = object()
		controller_provider = object()
		explicit_provider = object()
		services = {"default_action_provider": default, "action_providers": {"controller": controller_provider, "explicit": explicit_provider}}
		controller = AgentControlComponent(provider_id="controller")

		self.assertIs(resolve_workflow_provider(services, controller, "explicit"), explicit_provider)
		self.assertIs(resolve_workflow_provider(services, controller), controller_provider)
		with self.assertRaises(KeyError):
			resolve_workflow_provider(services, AgentControlComponent(provider_id="missing"))

	def test_registered_none_does_not_fall_back_to_default(self) -> None:
		services = {"default_action_provider": object(), "action_providers": {"disabled": None}}
		self.assertIsNone(resolve_workflow_provider(services, AgentControlComponent(provider_id="disabled")))

	def test_blank_ids_do_not_select_an_empty_registry_entry(self) -> None:
		default = object()
		services = {"default_action_provider": default, "action_providers": {"": object()}}
		self.assertIs(resolve_workflow_provider(services, AgentControlComponent()), default)

	def test_runtime_scoped_registry_uses_controller_then_default(self) -> None:
		default = object()
		named = object()
		registry = WorkflowRegistry(default)
		registry.register("named", named)
		registry.freeze()
		services = {"workflow_registry": registry}

		self.assertIs(resolve_workflow_provider(services, AgentControlComponent(provider_id="named")), named)
		with self.assertRaises(KeyError):
			resolve_workflow_provider(services, AgentControlComponent(provider_id="missing"))
		with self.assertRaisesRegex(RuntimeError, "frozen"):
			registry.register("late", object())


class ProviderCatalogTests(unittest.TestCase):
	def _workflow_config(self) -> dict:
		return {
			"llm_providers": {
				"main": {
					"protocol": "openai_compat",
					"base_url": "https://example.test",
					"api_prefix": "/v1",
					"api_key": "test-key",
				}
			},
			"workflows": {
				"default": {
					"kind": "llm",
					"roles": {
						"planner": {"provider_id": "main", "model": "default-planner"},
						"grounder": {"provider_id": "main", "model": "default-grounder"},
						"dialogue": {"provider_id": "main", "model": "default-dialogue"},
					},
				},
				"fast_social": {
					"kind": "llm",
					"roles": {
						"planner": {"provider_id": "main", "model": "fast-planner"},
						"grounder": {"provider_id": "main", "model": "fast-grounder"},
						"dialogue": {"provider_id": "main", "model": "fast-dialogue"},
					},
				},
			},
			"default_workflow_id": "default",
		}

	def test_named_workflow_binds_provider_and_role_models(self) -> None:
		default, named = build_workflow_catalog(self._workflow_config())

		self.assertEqual(default.roles["planner"]["model"], "default-planner")
		self.assertEqual(default.roles["grounder"]["model"], "default-grounder")
		self.assertEqual(default.roles["dialogue"]["model"], "default-dialogue")
		self.assertEqual(named["fast_social"].roles["planner"]["model"], "fast-planner")
		self.assertEqual(named["fast_social"].roles["grounder"]["model"], "fast-grounder")

	def test_runtime_registers_named_llm_profile(self) -> None:
		runtime = KernRuntime.from_config(
			Path(__file__).resolve().parents[2],
			"runtime_config.camping.package.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={
				"DEFAULT_WORKFLOW_PROVIDER_JSON": json.dumps({"kind": "llm"}),
				"CHECKPOINT_EVERY_TICK": "0",
				"LLM_WORKFLOW_CONFIG_JSON": json.dumps(self._workflow_config()),
			},
		)

		self.assertIn("fast_social", runtime.action_providers)
		self.assertEqual(runtime.action_providers["fast_social"].roles["planner"]["model"], "fast-planner")

	def test_from_config_accepts_custom_workflow_registry(self) -> None:
		custom = object()
		registry = WorkflowRegistry(custom)
		runtime = KernRuntime.from_config(
			Path(__file__).resolve().parents[2],
			"runtime_config.camping.package.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={"CHECKPOINT_EVERY_TICK": "0"},
			workflow_registry=registry,
		)

		self.assertIs(runtime.workflow_registry, registry)
		self.assertIs(runtime.workflow_registry.default_workflow, custom)
		with self.assertRaisesRegex(RuntimeError, "frozen"):
			registry.set_default(object())

	def test_runtime_registers_builtin_workflow_provider(self) -> None:
		runtime = KernRuntime.from_config(
			Path(__file__).resolve().parents[2],
			"runtime_config.camping.package.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={
				"CHECKPOINT_EVERY_TICK": "0",
				"WORKFLOW_PROVIDERS_JSON": json.dumps([{"workflow_id": "extra_simple", "kind": "simple"}]),
			},
		)

		workflow = runtime.workflow_registry.resolve(AgentControlComponent(provider_id="extra_simple"))
		self.assertIsNotNone(workflow)


if __name__ == "__main__":
	unittest.main()
