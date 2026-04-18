from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_LEVEL_VALUE = {
	"trace": 10,
	"debug": 20,
	"info": 30,
	"warn": 40,
	"error": 50,
}

_LEVEL_ANSI = {
	"trace": "\x1b[90m",
	"debug": "\x1b[36m",
	"info": "\x1b[37m",
	"warn": "\x1b[31m",
	"error": "\x1b[91m",
}

_ANSI_RESET = "\x1b[0m"


def _normalize_level(v: str) -> str:
	key = str(v or "").strip().lower()
	if key in _LEVEL_VALUE:
		return key
	return "info"


def _parse_categories(v: str) -> set[str]:
	text = str(v or "").strip()
	if not text:
		return {"*"}
	parts = [str(x).strip().lower() for x in text.split(",")]
	out = {x for x in parts if x}
	return out or {"*"}


def _colorize_line(level: str, text: str) -> str:
	code = _LEVEL_ANSI.get(_normalize_level(level), "")
	if not code:
		return text
	return f"{code}{text}{_ANSI_RESET}"


@dataclass
class LogManager:
	level: str = "info"
	categories: set[str] = field(default_factory=lambda: {"*"})
	json_mode: bool = False
	buffer_size: int = 1000
	buffer: list[dict[str, Any]] = field(default_factory=list)

	@classmethod
	def from_env(cls) -> "LogManager":
		return cls(level="info", categories={"*"}, json_mode=False, buffer_size=1000)

	def enabled(self, level: str, category: str) -> bool:
		lv = _normalize_level(level)
		cv = str(category or "system").strip().lower() or "system"
		if _LEVEL_VALUE[lv] < _LEVEL_VALUE[self.level]:
			return False
		if "*" in self.categories:
			return True
		return cv in self.categories

	def log(self, level: str, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		if not self.enabled(level, category):
			return
		record = {
			"ts": datetime.now(timezone.utc).isoformat(),
			"level": _normalize_level(level),
			"category": str(category or "system").strip().lower() or "system",
			"event": str(event or "").strip(),
			"message": str(message or ""),
			"context": dict(context or {}),
		}
		self.buffer.append(record)
		if len(self.buffer) > int(self.buffer_size):
			self.buffer = self.buffer[-int(self.buffer_size):]
		if self.json_mode:
			print(json.dumps(record, ensure_ascii=False))
		else:
			msg = record["message"]
			prefix = f"[{record['level'].upper()}][{record['category']}][{record['event']}]"
			ctx = record["context"] or {}
			ctx_text = json.dumps(ctx, ensure_ascii=False) if ctx else ""
			if msg and ctx_text:
				print(_colorize_line(record["level"], f"{prefix} {msg} {ctx_text}"))
			elif msg:
				print(_colorize_line(record["level"], f"{prefix} {msg}"))
			elif ctx_text:
				print(_colorize_line(record["level"], f"{prefix} {ctx_text}"))
			else:
				print(_colorize_line(record["level"], prefix))

	def trace(self, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		self.log("trace", category, event, message, context)

	def debug(self, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		self.log("debug", category, event, message, context)

	def info(self, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		self.log("info", category, event, message, context)

	def warn(self, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		self.log("warn", category, event, message, context)

	def error(self, category: str, event: str, message: str = "", context: dict[str, Any] | None = None) -> None:
		self.log("error", category, event, message, context)


_GLOBAL_LOGGER: LogManager | None = None


def get_logger() -> LogManager:
	global _GLOBAL_LOGGER
	if _GLOBAL_LOGGER is None:
		_GLOBAL_LOGGER = LogManager.from_env()
	return _GLOBAL_LOGGER


def reset_logger() -> None:
	global _GLOBAL_LOGGER
	_GLOBAL_LOGGER = None


def configure_logger(level: str = "info", categories: str = "*", json_mode: bool = False, buffer_size: int = 1000) -> LogManager:
	global _GLOBAL_LOGGER
	bs = int(buffer_size) if int(buffer_size) > 0 else 1000
	_GLOBAL_LOGGER = LogManager(
		level=_normalize_level(level),
		categories=_parse_categories(categories),
		json_mode=bool(json_mode),
		buffer_size=bs,
	)
	return _GLOBAL_LOGGER
