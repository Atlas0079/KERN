from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..log_manager import get_logger



DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.aabao.top")
DEFAULT_API_PREFIX = os.environ.get("LLM_API_PREFIX", "/v1")
DEFAULT_API_KEY = os.environ.get("LLM_API_KEY", "REPLACE_ME")


class LLMRequestError(RuntimeError):
	"""
	Unified exception for LLM request failure (Network/HTTP/Response format).
	"""


class ChatClient(Protocol):
	def chat_text(
		self,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> str:
		...


def _join_url(base_url: str, path: str) -> str:
	b = str(base_url or "").rstrip("/")
	p = str(path or "").lstrip("/")
	return f"{b}/{p}"


def _parse_sse_chat_chunks(raw: str) -> dict[str, Any]:
	text_parts: list[str] = []
	last_model = ""
	last_id = ""
	last_created: int | None = None
	for line in str(raw or "").splitlines():
		s = str(line or "").strip()
		if not s.startswith("data:"):
			continue
		payload = s[5:].strip()
		if not payload or payload == "[DONE]":
			continue
		try:
			obj = json.loads(payload)
		except Exception as e:
			raise LLMRequestError(f"invalid sse json chunk: {payload}") from e
		if isinstance(obj, dict):
			last_model = str(obj.get("model", last_model) or last_model)
			last_id = str(obj.get("id", last_id) or last_id)
			created = obj.get("created", None)
			try:
				if created is not None:
					last_created = int(created)
			except Exception as e:
				raise LLMRequestError(f"invalid sse created field: {created}") from e
			choices = obj.get("choices", [])
			if isinstance(choices, list):
				for c in choices:
					if not isinstance(c, dict):
						continue
					delta = c.get("delta", {}) or {}
					if isinstance(delta, dict):
						content = delta.get("content", "")
						if content is not None:
							text_parts.append(str(content))
	content_text = "".join(text_parts)
	return {
		"id": last_id,
		"model": last_model,
		"created": last_created if last_created is not None else int(time.time()),
		"object": "chat.completion",
		"choices": [{"index": 0, "message": {"role": "assistant", "content": content_text}, "finish_reason": "stop"}],
	}


@dataclass
class OpenAICompatClient:
	"""
	OpenAI-compatible API Client (No dependency on official openai library).

	Supported Interfaces:
	- POST /chat/completions
	"""

	base_url: str = DEFAULT_BASE_URL
	api_prefix: str = DEFAULT_API_PREFIX
	api_key: str = DEFAULT_API_KEY
	timeout_seconds: int = 60
	max_retries: int = 2
	retry_backoff_seconds: float = 1.0
	user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
	extra_headers: dict[str, str] | None = None

	def chat_completions(
		self,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""
		Return full JSON response (Convenient for logging/debugging/parsing).

		messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
		response_format: OpenAI compatible response_format (e.g., {"type":"json_object"}), support depends on third-party platform.
		"""

		if not isinstance(messages, list) or not messages:
			raise ValueError("messages must be a non-empty list")
		if not str(model or "").strip():
			raise ValueError("model is required")

		# Most third-party OpenAI-compatible API paths are: {base_url}{api_prefix}/chat/completions
		prefix = str(self.api_prefix or "").strip() or "/v1"
		if not prefix.startswith("/"):
			prefix = f"/{prefix}"
		url = _join_url(self.base_url, f"{prefix}/chat/completions")

		payload: dict[str, Any] = {
			"model": str(model),
			"messages": list(messages),
			"temperature": float(temperature),
		}
		if max_tokens is not None:
			payload["max_tokens"] = int(max_tokens)
		if isinstance(response_format, dict) and response_format:
			payload["response_format"] = dict(response_format)
		if isinstance(extra, dict) and extra:
			# Allow injection of third-party fields (e.g., top_p, presence_penalty, seed, etc.)
			payload.update(dict(extra))

		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

		headers = {
			"Content-Type": "application/json",
			"Accept": "application/json",
			"User-Agent": str(self.user_agent or ""),
		}
		# Allow caller to supplement/override header (Some third-parties need extra header to pass)
		if isinstance(self.extra_headers, dict) and self.extra_headers:
			for k, v in self.extra_headers.items():
				headers[str(k)] = str(v)
		if str(self.api_key or "").strip() and self.api_key != "REPLACE_ME":
			headers["Authorization"] = f"Bearer {self.api_key}"

		last_err: Exception | None = None
		max_retries = int(self.max_retries)
		for attempt in range(max_retries + 1):
			try:
				req = Request(url=url, data=body, headers=headers, method="POST")
				with urlopen(req, timeout=int(self.timeout_seconds)) as resp:
					raw = resp.read().decode("utf-8", errors="replace")
					if str(raw).lstrip().startswith("data:"):
						data = _parse_sse_chat_chunks(raw)
					else:
						data = json.loads(raw)
					if not isinstance(data, dict):
						raise LLMRequestError("invalid response json: not an object")
					return data
			except HTTPError as e:
				last_err = e
				try:
					err_body = e.read().decode("utf-8", errors="replace")
				except Exception:
					err_body = ""
				msg = f"LLM HTTPError {getattr(e, 'code', '')}: {getattr(e, 'reason', '')} body={err_body}"
				# 4xx usually not retryable; 5xx/429 retryable
				code = int(getattr(e, "code", 0) or 0)
				if code and 400 <= code < 500 and code not in [429]:
					raise LLMRequestError(f"{msg} attempts={attempt + 1}/{max_retries + 1}") from e
				if attempt >= max_retries:
					raise LLMRequestError(f"{msg} attempts={attempt + 1}/{max_retries + 1}") from e
				sleep_seconds = float(self.retry_backoff_seconds) * float(2**attempt)
				get_logger().warn(
					"llm",
					"request_retry",
					context={
						"attempt": int(attempt + 1),
						"max_attempts": int(max_retries + 1),
						"sleep_seconds": float(sleep_seconds),
						"http_code": int(code),
					},
				)
			except (URLError, TimeoutError, json.JSONDecodeError) as e:
				last_err = e
				if attempt >= max_retries:
					raise LLMRequestError(f"LLM request failed after {attempt + 1}/{max_retries + 1} attempts: {e}") from e
				sleep_seconds = float(self.retry_backoff_seconds) * float(2**attempt)
				get_logger().warn(
					"llm",
					"request_retry",
					context={
						"attempt": int(attempt + 1),
						"max_attempts": int(max_retries + 1),
						"sleep_seconds": float(sleep_seconds),
						"error": str(e),
						"error_type": str(getattr(e, "__class__", type("x", (), {})).__name__ or ""),
					},
				)

			# retry backoff
			time.sleep(float(self.retry_backoff_seconds) * float(2**attempt))

		raise LLMRequestError(f"LLM request failed after {max_retries + 1}/{max_retries + 1} attempts: {last_err}")

	def chat_text(
		self,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> str:
		"""
		Convenience method: Directly return text of choices[0].message.content.
		"""

		data = self.chat_completions(
			messages=messages,
			model=model,
			temperature=temperature,
			max_tokens=max_tokens,
			response_format=response_format,
			extra=extra,
		)

		choices = data.get("choices", [])
		if not isinstance(choices, list) or not choices:
			raise LLMRequestError("invalid response: missing choices")
		msg = (choices[0] or {}).get("message", {}) or {}
		content = (msg or {}).get("content", "")
		if content is None:
			content = ""
		return str(content)


@dataclass
class DualModelLLM:
	"""
	Simple wrapper for Two-Layer LLM: Support different model names for planner/grounder.

	Explanation:
	- model name is completely custom (Depends on model ID supported by third-party platform).
	"""

	client: ChatClient
	planner_model: str
	grounder_model: str

	def planner_text(self, messages: list[dict[str, Any]], temperature: float = 0.4, max_tokens: int | None = None) -> str:
		return self.client.chat_text(
			messages=messages,
			model=str(self.planner_model),
			temperature=float(temperature),
			max_tokens=max_tokens,
		)

	def grounder_text(
		self,
		messages: list[dict[str, Any]],
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
	) -> str:
		return self.client.chat_text(
			messages=messages,
			model=str(self.grounder_model),
			temperature=float(temperature),
			max_tokens=max_tokens,
			response_format=response_format,
		)
