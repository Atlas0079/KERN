from __future__ import annotations

import unittest

from KERN.external_runtime_catalog import ExternalRuntimeCatalog, ExternalRuntimeSpec


class ExternalRuntimeCatalogTests(unittest.TestCase):
	def test_registers_and_resolves_a_runtime_factory(self) -> None:
		def factory(_context: dict, _options: dict) -> object:
			return object()

		catalog = ExternalRuntimeCatalog()
		catalog.register(ExternalRuntimeSpec(provider_id="demo:runtime", factory=factory, origin="demo"))
		catalog.freeze()

		self.assertEqual(catalog.provider_ids(), frozenset({"demo:runtime"}))
		self.assertIs(catalog.require("demo:runtime").factory, factory)
		with self.assertRaisesRegex(RuntimeError, "frozen"):
			catalog.register(ExternalRuntimeSpec(provider_id="demo:other", factory=factory, origin="demo"))

	def test_rejects_blank_duplicate_and_non_callable_factories(self) -> None:
		catalog = ExternalRuntimeCatalog()
		with self.assertRaisesRegex(ValueError, "must not be blank"):
			catalog.register(ExternalRuntimeSpec(provider_id="", factory=lambda _context, _options: object()))
		with self.assertRaisesRegex(TypeError, "must be callable"):
			catalog.register(ExternalRuntimeSpec(provider_id="demo:runtime", factory=None))  # type: ignore[arg-type]

		catalog.register(ExternalRuntimeSpec(provider_id="demo:runtime", factory=lambda _context, _options: object()))
		with self.assertRaisesRegex(ValueError, "already registered"):
			catalog.register(ExternalRuntimeSpec(provider_id="demo:runtime", factory=lambda _context, _options: object()))


if __name__ == "__main__":
	unittest.main()
