from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DescriptionComponent:
	description: str = ""
	base_description: str = ""
	observed_description: str = ""
	recipe_description: str = ""

	def passive_text(self) -> str:
		return str(self.base_description or self.description or "")

	def observed_text(self) -> str:
		return str(self.observed_description or self.description or self.base_description or "")

	def recipe_text(self) -> str:
		return str(self.recipe_description or "")
