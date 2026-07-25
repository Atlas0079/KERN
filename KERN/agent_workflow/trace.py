from __future__ import annotations

import gzip
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any


def _safe_segment(value: Any) -> str:
	text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
	return text.strip("._") or "unknown"


@dataclass
class LLMTraceRecorder:
	mode: str = "off"
	output_dir: Path = field(default_factory=lambda: Path("llm_traces"))
	agent_ids: frozenset[str] = field(default_factory=frozenset)
	ticks: frozenset[int] = field(default_factory=frozenset)
	_lock: Lock = field(default_factory=Lock, init=False, repr=False)
	_paths: dict[str, Path] = field(default_factory=dict, init=False, repr=False)

	def __post_init__(self) -> None:
		self.mode = str(self.mode or "off").strip().lower()
		if self.mode not in {"off", "full"}:
			raise ValueError("LLM_TRACE_MODE must be off or full")
		self.output_dir = Path(self.output_dir)
		self.agent_ids = frozenset(str(item).strip() for item in self.agent_ids if str(item).strip())
		self.ticks = frozenset(int(item) for item in self.ticks)

	@classmethod
	def from_config(cls, config: dict[str, Any] | None, output_dir: str | Path) -> "LLMTraceRecorder":
		cfg = dict(config or {})
		agents = frozenset(item.strip() for item in str(cfg.get("LLM_TRACE_AGENT_IDS", "") or "").split(",") if item.strip())
		ticks: set[int] = set()
		for item in str(cfg.get("LLM_TRACE_TICKS", "") or "").split(","):
			clean = item.strip()
			if not clean:
				continue
			try:
				ticks.add(int(clean))
			except ValueError as exc:
				raise ValueError(f"LLM_TRACE_TICKS contains a non-integer value: {clean!r}") from exc
		return cls(
			mode=str(cfg.get("LLM_TRACE_MODE", "off") or "off"),
			output_dir=Path(output_dir),
			agent_ids=agents,
			ticks=frozenset(ticks),
		)

	def enabled_for(self, actor_id: str, tick: int) -> bool:
		if self.mode != "full":
			return False
		actor = str(actor_id or "")
		return (not self.agent_ids or actor in self.agent_ids) and (not self.ticks or int(tick) in self.ticks)

	def record(self, trace: dict[str, Any]) -> str:
		payload = deepcopy(dict(trace or {}))
		trace_id = str(payload.get("trace_id", "") or "").strip()
		actor_id = str(payload.get("actor_id", "") or "").strip()
		tick = int(payload.get("tick", 0) or 0)
		if not trace_id or not self.enabled_for(actor_id, tick):
			return ""
		path = self._trace_path(trace_id, actor_id, tick)
		with self._lock:
			is_new = not path.exists()
			self._write(path, payload)
			self._paths[trace_id] = path
			if is_new:
				self.output_dir.mkdir(parents=True, exist_ok=True)
				with (self.output_dir / "index.jsonl").open("a", encoding="utf-8") as stream:
					stream.write(
						json.dumps(
							{
								"trace_id": trace_id,
								"tick": tick,
								"actor_id": actor_id,
								"context_type": str(payload.get("context_type", "") or ""),
								"path": path.relative_to(self.output_dir).as_posix(),
							},
							ensure_ascii=False,
						)
						+ "\n"
					)
		return trace_id

	def record_action_result(
		self,
		trace_id: str,
		*,
		action_id: str,
		intent: dict[str, Any],
		status: str,
		rejection_code: str = "",
		message: str = "",
	) -> None:
		clean_id = str(trace_id or "").strip()
		if not clean_id or self.mode != "full":
			return
		with self._lock:
			path = self._paths.get(clean_id)
			if path is None or not path.exists():
				return
			with gzip.open(path, "rt", encoding="utf-8") as stream:
				payload = json.load(stream)
			payload.setdefault("action_results", []).append(
				{
					"action_id": str(action_id or ""),
					"intent": deepcopy(dict(intent or {})),
					"status": str(status or ""),
					"rejection_code": str(rejection_code or ""),
					"message": str(message or ""),
				}
			)
			self._write(path, payload)

	def _trace_path(self, trace_id: str, actor_id: str, tick: int) -> Path:
		return self.output_dir / f"tick_{int(tick):06d}" / _safe_segment(actor_id) / f"{_safe_segment(trace_id)}.json.gz"

	@staticmethod
	def _write(path: Path, payload: dict[str, Any]) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(path.suffix + ".tmp")
		with gzip.open(tmp, "wt", encoding="utf-8") as stream:
			json.dump(payload, stream, ensure_ascii=False, indent=2, default=repr)
		tmp.replace(path)


__all__ = ["LLMTraceRecorder"]
