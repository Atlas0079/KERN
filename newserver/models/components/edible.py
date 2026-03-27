from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EdibleComponent:
	effects_on_consume: list[dict[str, Any]] = field(default_factory=list)
