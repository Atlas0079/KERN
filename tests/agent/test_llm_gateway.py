from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from llm_gateway import Gateway, Worker, make_handler  # noqa: E402


class _UpstreamHandler(BaseHTTPRequestHandler):
	def do_POST(self) -> None:  # noqa: N802
		self.server.started.set()
		if self.server.block_event is not None:
			self.server.block_event.wait(timeout=2)
		if self.headers.get("X-Test-Stream") == "true":
			self.send_response(200)
			self.send_header("Content-Type", "text/event-stream")
			self.send_header("Cache-Control", "no-cache")
			self.end_headers()
			self.wfile.write(b'data: {"worker":"' + self.server.label.encode() + b'","part":1}\n\n')
			self.wfile.flush()
			time.sleep(0.02)
			self.wfile.write(b"data: [DONE]\n\n")
			self.wfile.flush()
			return
		payload = json.dumps({"worker": self.server.label}).encode()
		self.send_response(200)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(payload)))
		self.end_headers()
		self.wfile.write(payload)

	def log_message(self, format: str, *args: object) -> None:
		return


class _ReusableServer(ThreadingHTTPServer):
	allow_reuse_address = True


def _start(server: ThreadingHTTPServer) -> threading.Thread:
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	return thread


class LLMGatewayTests(unittest.TestCase):
	def setUp(self) -> None:
		self.upstream_one = _ReusableServer(("127.0.0.1", 0), _UpstreamHandler)
		self.upstream_one.label = "one"
		self.upstream_one.started = threading.Event()
		self.upstream_one.block_event = None
		self.upstream_two = _ReusableServer(("127.0.0.1", 0), _UpstreamHandler)
		self.upstream_two.label = "two"
		self.upstream_two.started = threading.Event()
		self.upstream_two.block_event = None
		_start(self.upstream_one)
		_start(self.upstream_two)
		workers = [
			Worker("one", f"http://127.0.0.1:{self.upstream_one.server_port}"),
			Worker("two", f"http://127.0.0.1:{self.upstream_two.server_port}"),
		]
		self.gateway_state = Gateway(workers, timeout_seconds=0.5, failure_cooldown_seconds=0.05)
		self.gateway = _ReusableServer(("127.0.0.1", 0), make_handler(self.gateway_state))
		_start(self.gateway)
		self.base_url = f"http://127.0.0.1:{self.gateway.server_port}"

	def tearDown(self) -> None:
		for server in (self.gateway, self.upstream_one, self.upstream_two):
			server.shutdown()
			server.server_close()

	def _chat(self) -> dict[str, str]:
		request = Request(
			f"{self.base_url}/v1/chat/completions",
			data=b'{"model":"gemma","messages":[{"role":"user","content":"hello"}]}',
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		return json.loads(urlopen(request, timeout=2).read())

	def test_routes_tied_workers_round_robin(self) -> None:
		self.assertEqual("one", self._chat()["worker"])
		self.assertEqual("two", self._chat()["worker"])

	def test_skips_unavailable_worker(self) -> None:
		self.upstream_one.shutdown()
		self.upstream_one.server_close()
		self.assertEqual("two", self._chat()["worker"])

	def test_retries_a_recovered_worker_after_cooldown(self) -> None:
		self.upstream_one.shutdown()
		self.upstream_one.server_close()
		self.assertEqual("two", self._chat()["worker"])
		self.upstream_one = _ReusableServer(("127.0.0.1", self.gateway_state.workers[0].port), _UpstreamHandler)
		self.upstream_one.label = "one-restarted"
		self.upstream_one.started = threading.Event()
		self.upstream_one.block_event = None
		_start(self.upstream_one)
		time.sleep(0.06)
		self.assertEqual("one-restarted", self._chat()["worker"])

	def test_routes_concurrent_request_to_less_busy_worker(self) -> None:
		self.upstream_one.block_event = threading.Event()
		first_result: dict[str, str] = {}
		thread = threading.Thread(target=lambda: first_result.update(self._chat()))
		thread.start()
		self.assertTrue(self.upstream_one.started.wait(timeout=1))
		self.assertEqual("two", self._chat()["worker"])
		self.upstream_one.block_event.set()
		thread.join(timeout=2)
		self.assertEqual("one", first_result["worker"])

	def test_forwards_streaming_requests(self) -> None:
		request = Request(
			f"{self.base_url}/v1/chat/completions",
			data=b'{"stream":true}',
			headers={"Content-Type": "application/json", "X-Test-Stream": "true"},
			method="POST",
		)
		with urlopen(request, timeout=2) as response:
			self.assertEqual("text/event-stream", response.headers.get_content_type())
			self.assertEqual(
				b'data: {"worker":"one","part":1}\n\ndata: [DONE]\n\n',
				response.read(),
			)
