from __future__ import annotations

from typing import Any

from .gemini_client import GeminiClient
from .openai_compat_client import ChatClient, OpenAICompatClient


def build_chat_provider(config: dict[str, Any]) -> ChatClient:
	"""Assemble one protocol provider; it has no KERN workflow dependency."""
	cfg = dict(config)

	def required(key: str) -> str:
		value = str(cfg.get(key, "") or "").strip()
		if not value:
			raise ValueError(f"llm provider field is required: {key}")
		return value

	timeout_seconds = int(str(cfg.get("timeout_seconds", 60) or 60))
	max_retries = int(str(cfg.get("max_retries", 2) or 2))
	retry_backoff_seconds = float(str(cfg.get("retry_backoff_seconds", 1.0) or 1.0))
	provider_id = required("protocol").lower()
	if provider_id in {"openai", "openai_compat", "openai_compatible", "openai_chat"}:
		return OpenAICompatClient(
			base_url=required("base_url"), api_prefix=str(cfg.get("api_prefix", "/v1")), api_key=required("api_key"),
			timeout_seconds=timeout_seconds, max_retries=max_retries, retry_backoff_seconds=retry_backoff_seconds,
		)
	if provider_id in {"gemini", "gemini_generate_content"}:
		return GeminiClient(
			base_url=required("base_url"), api_prefix=str(cfg.get("api_prefix", "/v1beta")), api_key=required("api_key"),
			timeout_seconds=timeout_seconds, max_retries=max_retries, retry_backoff_seconds=retry_backoff_seconds,
		)
	raise ValueError(f"unsupported llm provider protocol: {provider_id}")
