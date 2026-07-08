from __future__ import annotations

import unittest

from KERN.agent_workflow.llm_action_provider import _operable_screen_contexts_text
from tools.run_rumor_spread_5agent_llm_smoke import _build_social_seed


class SocialPromptRedactionTests(unittest.TestCase):
	def test_screen_context_hides_internal_social_ids(self) -> None:
		text = _operable_screen_contexts_text(
			[
				{
					"entity_id": "phone_01",
					"entity_name": "Phone",
					"view": "feed",
					"updated_tick": 1,
					"feed_items": [
						{
							"post_id": "post_rumor_seed_001",
							"author_id": "acc_seed",
							"author_display_name": "本地生活观察",
							"summary": "有人说学校附近的饮水机不安全。",
						}
					],
				}
			]
		)

		self.assertIn("slot 0", text)
		self.assertIn("本地生活观察", text)
		self.assertIn("饮水机", text)
		self.assertNotIn("post_id", text)
		self.assertNotIn("author_id", text)
		self.assertNotIn("post_rumor", text)
		self.assertNotIn("acc_seed", text)

	def test_five_agent_smoke_seed_uses_neutral_visible_account_names(self) -> None:
		seed = _build_social_seed()
		names = {str(x.get("display_name", "")) for x in seed.get("accounts", []) if isinstance(x, dict)}

		self.assertIn("本地生活观察", names)
		self.assertIn("校务通知", names)
		self.assertNotIn("Local Rumor Watch", names)
		self.assertNotIn("Official Notice", names)


if __name__ == "__main__":
	unittest.main()
