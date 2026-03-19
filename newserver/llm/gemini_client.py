from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..log_manager import get_logger
from .openai_compat_client import LLMRequestError


DEFAULT_GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
DEFAULT_GEMINI_API_PREFIX = os.environ.get("GEMINI_API_PREFIX", "/v1beta")
DEFAULT_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCzeZXBGPE3Hu9ZX4XQJA5LX9pV8OE8qi8")


def _join_url(base_url: str, path: str) -> str:
	b = str(base_url or "").rstrip("/")
	p = str(path or "").lstrip("/")
	return f"{b}/{p}"


def _extract_text_from_gemini_response(data: dict[str, Any]) -> str:
	cands = data.get("candidates", [])
	if not isinstance(cands, list) or not cands:
		raise LLMRequestError("invalid gemini response: missing candidates")
	content = (cands[0] or {}).get("content", {}) or {}
	parts = content.get("parts", []) or []
	if not isinstance(parts, list) or not parts:
		raise LLMRequestError("invalid gemini response: missing content.parts")
	texts: list[str] = []
	for p in parts:
		if not isinstance(p, dict):
			continue
		t = p.get("text", None)
		if t is None:
			continue
		texts.append(str(t))
	out = "".join(texts).strip()
	if not out:
		raise LLMRequestError("invalid gemini response: empty text")
	return out


def _messages_to_gemini_payload(messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
	system_texts: list[str] = []
	contents: list[dict[str, Any]] = []
	for m in list(messages or []):
		if not isinstance(m, dict):
			continue
		role = str(m.get("role", "") or "").strip().lower()
		content = m.get("content", "")
		if content is None:
			content = ""
		text = str(content)
		if role == "system":
			if text.strip():
				system_texts.append(text)
			continue
		g_role = "user"
		if role in {"assistant", "model"}:
			g_role = "model"
		contents.append({"role": g_role, "parts": [{"text": text}]})
	system_instruction = None
	if system_texts:
		system_instruction = {"parts": [{"text": "\n".join(system_texts)}]}
	return system_instruction, contents


@dataclass
class GeminiClient:
	base_url: str = DEFAULT_GEMINI_BASE_URL
	api_prefix: str = DEFAULT_GEMINI_API_PREFIX
	api_key: str = DEFAULT_GEMINI_API_KEY
	timeout_seconds: int = 60
	max_retries: int = 2
	retry_backoff_seconds: float = 1.0

	def chat_text(
		self,
		messages: list[dict[str, Any]],
		model: str,
		temperature: float = 0.2,
		max_tokens: int | None = None,
		response_format: dict[str, Any] | None = None,
		extra: dict[str, Any] | None = None,
	) -> str:
		if not isinstance(messages, list) or not messages:
			raise ValueError("messages must be a non-empty list")
		model_name = str(model or "").strip()
		if not model_name:
			raise ValueError("model is required")
		key = str(self.api_key or "").strip()
		if not key or key == "REPLACE_ME":
			raise LLMRequestError("Gemini API key missing (set GEMINI_API_KEY)")

		prefix = str(self.api_prefix or "").strip() or "/v1"
		if not prefix.startswith("/"):
			prefix = f"/{prefix}"
		path = f"{prefix}/models/{model_name}:generateContent"
		url = _join_url(self.base_url, path)
		url = f"{url}?{urlencode({'key': key})}"

		system_instruction, contents = _messages_to_gemini_payload(messages)
		payload: dict[str, Any] = {"contents": contents}
		if system_instruction is not None:
			payload["systemInstruction"] = system_instruction

		gen: dict[str, Any] = {"temperature": float(temperature)}
		if max_tokens is not None:
			gen["maxOutputTokens"] = int(max_tokens)
		if isinstance(response_format, dict) and response_format.get("type") == "json_object":
			gen["responseMimeType"] = "application/json"
		if isinstance(extra, dict) and extra:
			gen.update(dict(extra))
		if gen:
			payload["generationConfig"] = gen

		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		headers = {
			"Content-Type": "application/json",
			"Accept": "application/json",
		}

		last_err: Exception | None = None
		max_retries = int(self.max_retries)
		for attempt in range(max_retries + 1):
			try:
				req = Request(url=url, data=body, headers=headers, method="POST")
				with urlopen(req, timeout=int(self.timeout_seconds)) as resp:
					raw = resp.read().decode("utf-8", errors="replace")
					data = json.loads(raw)
					if not isinstance(data, dict):
						raise LLMRequestError("invalid gemini response json: not an object")
					return _extract_text_from_gemini_response(data)
			except HTTPError as e:
				last_err = e
				try:
					err_body = e.read().decode("utf-8", errors="replace")
				except Exception:
					err_body = ""
				msg = f"Gemini HTTPError {getattr(e, 'code', '')}: {getattr(e, 'reason', '')} body={err_body}"
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
						"provider": "gemini",
					},
				)
			except (URLError, TimeoutError, json.JSONDecodeError) as e:
				last_err = e
				if attempt >= max_retries:
					raise LLMRequestError(f"Gemini request failed after {attempt + 1}/{max_retries + 1} attempts: {e}") from e
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
						"provider": "gemini",
					},
				)

			time.sleep(float(self.retry_backoff_seconds) * float(2**attempt))

		raise LLMRequestError(f"Gemini request failed after {max_retries + 1}/{max_retries + 1} attempts: {last_err}")
