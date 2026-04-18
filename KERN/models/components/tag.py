from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TagComponent:
	tags: list[str] = field(default_factory=list)

	def has_tag(self, tag_name: str) -> bool:
		return tag_name in self.tags

