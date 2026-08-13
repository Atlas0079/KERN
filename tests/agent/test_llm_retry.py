from __future__ import annotations

import io
import json
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from KERN.llm.gemini_client import GeminiClient
from KERN.llm.openai_compat_client import LLMRequestError, OpenAICompatClient


class _Response:
	def __init__(self, payload: dict | bytes) -> None:
		self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False

	def read(self) -> bytes:
		return self._body


def _openai_response(text: str = "ok") -> _Response:
	return _Response({"choices": [{"message": {"content": text}}]})


def _gemini_response(text: str = "ok") -> _Response:
	return _Response({"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _http_error(code: int) -> HTTPError:
	return HTTPError("https://example.test", code, "error", None, io.BytesIO(b'{"error":"failed"}'))


class LLMRetryTests(unittest.TestCase):
	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_does_not_retry_invalid_json(self, urlopen, sleep) -> None:
		urlopen.return_value = _Response(b"not-json")
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=2)

		with self.assertRaisesRegex(LLMRequestError, "invalid response json"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(urlopen.call_count, 1)
		sleep.assert_not_called()

	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_retries_connection_error_then_succeeds(self, urlopen, sleep) -> None:
		urlopen.side_effect = [URLError("offline"), _openai_response("recovered")]
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=1, retry_backoff_seconds=0.25)

		text = client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(text, "recovered")
		self.assertEqual(urlopen.call_count, 2)
		sleep.assert_called_once_with(0.25)

	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_retries_429_but_not_other_4xx(self, urlopen, sleep) -> None:
		urlopen.side_effect = [_http_error(429), _openai_response()]
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=1, retry_backoff_seconds=0.1)
		self.assertEqual(client.chat_text([{"role": "user", "content": "hi"}], "model"), "ok")
		self.assertEqual(urlopen.call_count, 2)
		sleep.assert_called_once_with(0.1)

		urlopen.reset_mock()
		sleep.reset_mock()
		urlopen.side_effect = _http_error(400)
		with self.assertRaisesRegex(LLMRequestError, "400"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")
		self.assertEqual(urlopen.call_count, 1)
		sleep.assert_not_called()

		urlopen.reset_mock()
		sleep.reset_mock()
		urlopen.side_effect = _http_error(302)
		with self.assertRaisesRegex(LLMRequestError, "302"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")
		self.assertEqual(urlopen.call_count, 1)
		sleep.assert_not_called()

	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_exhaustion_raises_after_configured_retries(self, urlopen, sleep) -> None:
		urlopen.side_effect = URLError("offline")
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=2, retry_backoff_seconds=0.5)

		with self.assertRaisesRegex(LLMRequestError, "3/3 attempts"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(urlopen.call_count, 3)
		self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_retries_direct_connection_timeout_and_5xx(self, urlopen, sleep) -> None:
		urlopen.side_effect = [ConnectionResetError("reset"), TimeoutError("timeout"), _http_error(503), _openai_response("recovered")]
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=3, retry_backoff_seconds=0.1)

		self.assertEqual(client.chat_text([{"role": "user", "content": "hi"}], "model"), "recovered")
		self.assertEqual(urlopen.call_count, 4)
		self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.1, 0.2, 0.4])

	@patch("KERN.llm.openai_compat_client.time.sleep")
	@patch("KERN.llm.openai_compat_client.urlopen")
	def test_openai_compat_retries_ssl_read_failure(self, urlopen, sleep) -> None:
		urlopen.side_effect = [ssl.SSLError("record layer failure"), _openai_response("recovered")]
		client = OpenAICompatClient(base_url="https://example.test", api_key="key", max_retries=1, retry_backoff_seconds=0.25)

		self.assertEqual(client.chat_text([{"role": "user", "content": "hi"}], "model"), "recovered")
		self.assertEqual(urlopen.call_count, 2)
		sleep.assert_called_once_with(0.25)

	@patch("KERN.llm.gemini_client.time.sleep")
	@patch("KERN.llm.gemini_client.urlopen")
	def test_gemini_uses_the_same_bounded_retry_contract(self, urlopen, sleep) -> None:
		urlopen.side_effect = [URLError("offline"), _gemini_response("recovered")]
		client = GeminiClient(base_url="https://example.test", api_key="key", max_retries=1, retry_backoff_seconds=0.25)

		text = client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(text, "recovered")
		self.assertEqual(urlopen.call_count, 2)
		sleep.assert_called_once_with(0.25)

	@patch("KERN.llm.gemini_client.time.sleep")
	@patch("KERN.llm.gemini_client.urlopen")
	def test_gemini_does_not_retry_redirect_http_error(self, urlopen, sleep) -> None:
		urlopen.side_effect = _http_error(302)
		client = GeminiClient(base_url="https://example.test", api_key="key", max_retries=2)

		with self.assertRaisesRegex(LLMRequestError, "302"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(urlopen.call_count, 1)
		sleep.assert_not_called()

	@patch("KERN.llm.gemini_client.time.sleep")
	@patch("KERN.llm.gemini_client.urlopen")
	def test_gemini_does_not_retry_invalid_json(self, urlopen, sleep) -> None:
		urlopen.return_value = _Response(b"not-json")
		client = GeminiClient(base_url="https://example.test", api_key="key", max_retries=2)

		with self.assertRaisesRegex(LLMRequestError, "invalid gemini response json"):
			client.chat_text([{"role": "user", "content": "hi"}], "model")

		self.assertEqual(urlopen.call_count, 1)
		sleep.assert_not_called()

	@patch("KERN.llm.gemini_client.time.sleep")
	@patch("KERN.llm.gemini_client.urlopen")
	def test_gemini_retries_direct_connection_timeout_and_5xx(self, urlopen, sleep) -> None:
		urlopen.side_effect = [ConnectionResetError("reset"), TimeoutError("timeout"), _http_error(503), _gemini_response("recovered")]
		client = GeminiClient(base_url="https://example.test", api_key="key", max_retries=3, retry_backoff_seconds=0.1)

		self.assertEqual(client.chat_text([{"role": "user", "content": "hi"}], "model"), "recovered")
		self.assertEqual(urlopen.call_count, 4)
		self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.1, 0.2, 0.4])


if __name__ == "__main__":
	unittest.main()
