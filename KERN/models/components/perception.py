from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerceptionComponent:
	enabled: bool = True
	interaction_inbox: list[dict[str, Any]] = field(default_factory=list)

	def enqueue_interaction(self, record: dict[str, Any]) -> bool:
		if not isinstance(record, dict):
			return False
		interaction_id = str(record.get("interaction_id", "") or "").strip()
		if not interaction_id:
			return False
		for item in list(self.interaction_inbox or []):
			if isinstance(item, dict) and str(item.get("interaction_id", "") or "") == interaction_id:
				return False
		self.interaction_inbox.append(deepcopy(record))
		return True

	def consume_interactions(self, interaction_ids: list[str]) -> int:
		wanted = {str(item or "").strip() for item in list(interaction_ids or []) if str(item or "").strip()}
		if not wanted:
			return 0
		before = len(self.interaction_inbox)
		self.interaction_inbox = [
			deepcopy(item)
			for item in list(self.interaction_inbox or [])
			if isinstance(item, dict) and str(item.get("interaction_id", "") or "") not in wanted
		]
		return max(0, before - len(self.interaction_inbox))
