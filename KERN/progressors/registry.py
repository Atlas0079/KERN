from __future__ import annotations

from typing import Any

from .base import Progressor


_REGISTRY: dict[str, Progressor] = {}


def register_progressor(progressor: Progressor) -> None:
	_REGISTRY[str(getattr(progressor, "progressor_id", ""))] = progressor


def get_progressor(progressor_id: str) -> Progressor:
	pid = str(progressor_id or "").strip()
	if pid in _REGISTRY:
		return _REGISTRY[pid]
	# Default Progressor (Linear Progression)
	return _REGISTRY["Linear"]

