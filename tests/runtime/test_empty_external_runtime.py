from __future__ import annotations

import unittest

from KERN.external_runtimes import EmptyExternalRuntime


class EmptyExternalRuntimeTests(unittest.TestCase):
	def test_health_check_and_lifecycle(self) -> None:
		adapter = EmptyExternalRuntime(runtime_id="empty", options={"mode": "smoke"})

		self.assertEqual(adapter.start({})[0]["type"], "ExternalRuntimeStarted")
		self.assertEqual(adapter.invoke("health_check", {}, {})[0]["type"], "ExternalRuntimeHealthy")
		self.assertEqual(adapter.close({})[0]["type"], "ExternalRuntimeClosed")
		self.assertTrue(adapter.started)
		self.assertTrue(adapter.closed)

	def test_rejects_undefined_operations(self) -> None:
		adapter = EmptyExternalRuntime(runtime_id="empty")
		with self.assertRaisesRegex(ValueError, "unsupported"):
			adapter.invoke("repost", {}, {})


if __name__ == "__main__":
	unittest.main()
