from __future__ import annotations

from dataclasses import dataclass, field

from KERN.package_definitions import package_component


BIG_FIVE_FIELDS = frozenset(
	{"openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"}
)


@package_component("sea_level_social_experiment:SocialIdentityComponent")
@dataclass
class SocialIdentityComponent:
	"""Experiment identity facts exposed to the social decision workflow."""

	profile_id: str
	natural_language_background: str
	platform_friend_categories: list[str]
	big_five: dict[str, float] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if not isinstance(self.profile_id, str) or not self.profile_id.strip() or self.profile_id != self.profile_id.strip():
			raise ValueError("social identity profile_id must be a non-blank trimmed string")
		if not isinstance(self.natural_language_background, str) or not self.natural_language_background.strip():
			raise ValueError("social identity natural_language_background must be non-blank")
		if "我" not in self.natural_language_background:
			raise ValueError("social identity natural_language_background must use first-person voice")
		categories = self.platform_friend_categories
		if not isinstance(categories, list) or not 1 <= len(categories) <= 5:
			raise ValueError("social identity platform_friend_categories must contain one to five categories")
		if any(not isinstance(item, str) or not item or item != item.strip() for item in categories):
			raise ValueError("social identity friend categories must be non-blank trimmed strings")
		if len(set(categories)) != len(categories):
			raise ValueError("social identity friend categories must be unique")
		self.platform_friend_categories = list(categories)
		if not isinstance(self.big_five, dict) or set(self.big_five) != BIG_FIVE_FIELDS:
			raise ValueError("social identity big_five must contain exactly five dimensions")
		normalized: dict[str, float] = {}
		for field_name in sorted(BIG_FIVE_FIELDS):
			value = self.big_five[field_name]
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
				raise ValueError(f"social identity big_five.{field_name} must be between 0 and 1")
			normalized[field_name] = float(value)
		self.big_five = normalized


__all__ = ["BIG_FIVE_FIELDS", "SocialIdentityComponent"]
