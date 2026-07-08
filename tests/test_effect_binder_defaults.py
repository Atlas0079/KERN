from __future__ import annotations

import unittest

from KERN.executor._effect_binder import _resolve_param_token


class EffectBinderDefaultParamTests(unittest.TestCase):
	def test_param_token_can_use_default_value(self) -> None:
		self.assertEqual(_resolve_param_token("param:limit:8", {"parameters": {}}), "8")
		self.assertEqual(_resolve_param_token("param:limit:8", {"parameters": {"limit": 3}}), 3)
		self.assertEqual(_resolve_param_token("param:limit", {"parameters": {}}), "")


if __name__ == "__main__":
	unittest.main()
