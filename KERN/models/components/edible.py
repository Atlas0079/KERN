from __future__ import annotations

from dataclasses import dataclass, field

from ...effect_bundle import EffectBundle


@dataclass
class EdibleComponent:
	on_consume_bundle: EffectBundle = field(default_factory=EffectBundle)
