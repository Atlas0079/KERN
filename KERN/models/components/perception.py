from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerceptionComponent:
	enabled: bool = True
	# Inbox 暂存世界可提供给该实体的观察输入，不代表实体已经注意或记住了它们。
	# 各工作流自行决定哪些观察进入记忆；已处理但未写入记忆的观察表示被“忽视”。
	# 因此保留这层中转，不把所有可感知事件自动写入 MemoryComponent。
	# 决策瞬间的当前环境另行构造上下文，不与这里待处理的过去观察混为一谈。
	interaction_inbox: list[dict[str, Any]] = field(default_factory=list)
	record_inbox: list[dict[str, Any]] = field(default_factory=list)

	def enqueue_record(self, record: dict[str, Any]) -> bool:
		if not isinstance(record, dict):
			return False
		record_id = str(record.get("record_id", "") or "").strip()
		if not record_id:
			return False
		for item in list(self.record_inbox or []):
			if isinstance(item, dict) and str(item.get("record_id", "") or "") == record_id:
				return False
		self.record_inbox.append(deepcopy(record))
		return True

	def consume_records(self, record_ids: list[str]) -> int:
		wanted = {str(item or "").strip() for item in list(record_ids or []) if str(item or "").strip()}
		if not wanted:
			return 0
		before = len(self.record_inbox)
		self.record_inbox = [
			deepcopy(item)
			for item in list(self.record_inbox or [])
			if isinstance(item, dict) and str(item.get("record_id", "") or "") not in wanted
		]
		return max(0, before - len(self.record_inbox))

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
