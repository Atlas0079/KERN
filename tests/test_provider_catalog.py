from __future__ import annotations

import json
import unittest
from pathlib import Path

from KERN.agent_workflow.provider_catalog import build_workflow_provider_catalog
from KERN.agent_workflow.provider_routing import resolve_workflow_provider
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
		self.assertIs(resolve_workflow_provider(services, AgentControlComponent(provider_id="missing")), default)

	def test_registered_none_does_not_fall_back_to_default(self) -> None:
		services = {"default_action_provider": object(), "action_providers": {"disabled": None}}
		self.assertIsNone(resolve_workflow_provider(services, AgentControlComponent(provider_id="disabled")))

	def test_blank_ids_do_not_select_an_empty_registry_entry(self) -> None:
		default = object()
		services = {"default_action_provider": default, "action_providers": {"": object()}}
		self.assertIs(resolve_workflow_provider(services, AgentControlComponent()), default)


class ProviderCatalogTests(unittest.TestCase):
	def test_named_profile_overrides_default_llm_settings(self) -> None:
		profiles = {
			"fast_social": {
				"LLM_PROVIDER": "openai_compat",
				"LLM_PLANNER_MODEL": "fast-planner",
				"LLM_GROUNDER_MODEL": "fast-grounder",
			}
		}
		default, named = build_workflow_provider_catalog(
			{"LLM_PROVIDER": "openai_compat", "LLM_PLANNER_MODEL": "default-planner", "LLM_GROUNDER_MODEL": "default-grounder", "LLM_PROFILES_JSON": json.dumps(profiles)}
		)

		self.assertEqual(default.llm.planner_model, "default-planner")
		self.assertEqual(named["fast_social"].llm.planner_model, "fast-planner")
		self.assertEqual(named["fast_social"].llm.grounder_model, "fast-grounder")

	def test_invalid_profile_document_is_rejected(self) -> None:
		with self.assertRaisesRegex(ValueError, "LLM_PROFILES_JSON"):
			build_workflow_provider_catalog({"LLM_PROFILES_JSON": "[]"})

	def test_runtime_registers_named_llm_profile(self) -> None:
		profiles = {"fast_social": {"LLM_PROVIDER": "openai_compat", "LLM_PLANNER_MODEL": "fast-planner"}}
		runtime = KernRuntime.from_config(
			Path(__file__).resolve().parents[1],
			"runtime_config.camping.package.smoke.json",
			validate=False,
			configure_logging=False,
			overrides={"USE_LLM": "1", "CHECKPOINT_EVERY_TICK": "0", "LLM_PROFILES_JSON": json.dumps(profiles)},
		)

		self.assertIn("fast_social", runtime.action_providers)
		self.assertEqual(runtime.action_providers["fast_social"].llm.planner_model, "fast-planner")


if __name__ == "__main__":
	unittest.main()
