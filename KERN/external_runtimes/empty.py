from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmptyExternalRuntime:
	"""A no-state adapter used to verify external runtime wiring.

	It deliberately supports only ``health_check``. Domain Packages replace this
	adapter with a runtime that owns real state and operations.
	"""

	runtime_id: str
	options: dict[str, Any] = field(default_factory=dict)
	started: bool = False
	closed: bool = False

	def start(self, _context: dict[str, Any]) -> list[dict[str, Any]]:
		self.started = True
		return [{"type": "ExternalRuntimeStarted", "runtime_id": self.runtime_id}]

	def close(self, _context: dict[str, Any]) -> list[dict[str, Any]]:
		self.closed = True
		return [{"type": "ExternalRuntimeClosed", "runtime_id": self.runtime_id}]

	def invoke(self, operation: str, _payload: dict[str, Any], _context: dict[str, Any]) -> list[dict[str, Any]]:
		if str(operation or "") != "health_check":
			raise ValueError(f"unsupported empty runtime operation: {operation}")
		return [{"type": "ExternalRuntimeHealthy", "runtime_id": self.runtime_id}]
