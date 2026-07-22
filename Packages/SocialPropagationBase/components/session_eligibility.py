from __future__ import annotations

from dataclasses import dataclass

from KERN.package_definitions import package_component


@package_component("social_propagation:SocialSessionEligibilityComponent")
@dataclass
class SocialSessionEligibilityComponent:
	"""Scenario-owned, deterministic input to social-session selection."""

	session_rate: float = 0.2
	extraversion: float = 0.0
