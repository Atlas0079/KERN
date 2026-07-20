#!/usr/bin/env python3
"""Local OpenAI-compatible gateway for multiple llama-server workers.

The gateway is intentionally bound to loopback by default.  It routes each
non-streaming request to the healthy worker with the fewest in-flight requests,
then uses round-robin ordering to break ties.
"""

from __future__ import annotations

import argparse
import http.client
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from typing import Any
from urllib.parse import urlparse


@dataclass
class Worker:
	name: str
	url: str
	in_flight: int = 0
	healthy: bool = True
	retry_at: float = 0.0

	def __post_init__(self) -> None:
		parsed = urlparse(self.url)
		if parsed.scheme != "http" or not parsed.hostname:
			raise ValueError(f"worker URL must be an http URL: {self.url!r}")
		self.host = parsed.hostname
		self.port = parsed.port or 80


class Gateway:
	def __init__(self, workers: list[Worker], timeout_seconds: float = 180.0, failure_cooldown_seconds: float = 5.0):
		if not workers:
			raise ValueError("at least one worker is required")
		self.workers = workers
		self.timeout_seconds = timeout_seconds
		self.failure_cooldown_seconds = failure_cooldown_seconds
		self._lock = threading.Lock()
		self._tie_breaker = count()

	def reserve_worker(self, excluded: set[str] | None = None) -> Worker | None:
		excluded = excluded or set()
		with self._lock:
			now = time.monotonic()
			candidates = [
				worker
				for worker in self.workers
				if worker.name not in excluded and (worker.healthy or worker.retry_at <= now)
			]
			if not candidates:
				return None
			minimum = min(worker.in_flight for worker in candidates)
			tied = [worker for worker in candidates if worker.in_flight == minimum]
			worker = tied[next(self._tie_breaker) % len(tied)]
			worker.in_flight += 1
			return worker

	def release_worker(self, worker: Worker, healthy: bool) -> None:
		with self._lock:
			worker.in_flight -= 1
			worker.healthy = healthy
			worker.retry_at = 0.0 if healthy else time.monotonic() + self.failure_cooldown_seconds

	def status(self) -> dict[str, Any]:
		with self._lock:
			return {
				"ok": any(worker.healthy for worker in self.workers),
				"workers": [
					{"name": worker.name, "url": worker.url, "healthy": worker.healthy, "in_flight": worker.in_flight}
					for worker in self.workers
				],
			}

	def forward(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, str, bytes, dict[str, str]]:
		excluded: set[str] = set()
		last_error = "no healthy workers"
		for _ in range(len(self.workers)):
			worker = self.reserve_worker(excluded)
			if worker is None:
				break
			excluded.add(worker.name)
			try:
				connection = http.client.HTTPConnection(worker.host, worker.port, timeout=self.timeout_seconds)
				forward_headers = {
					key: value
					for key, value in headers.items()
					if key.lower() not in {"host", "connection", "content-length"}
				}
				forward_headers["Host"] = f"{worker.host}:{worker.port}"
				connection.request(method, path, body=body, headers=forward_headers)
				response = connection.getresponse()
				response_body = response.read()
				response_headers = {
					key: value
					for key, value in response.getheaders()
					if key.lower() not in {"connection", "content-length", "transfer-encoding"}
				}
				connection.close()
				healthy = response.status < 500
				self.release_worker(worker, healthy=healthy)
				if healthy:
					return response.status, response.reason, response_body, response_headers
				last_error = f"{worker.name} returned HTTP {response.status}"
			except (OSError, http.client.HTTPException) as error:
				self.release_worker(worker, healthy=False)
				last_error = f"{worker.name} is unavailable: {error}"
		return 503, "Service Unavailable", json.dumps({"error": {"message": last_error, "type": "gateway_error"}}).encode(), {"Content-Type": "application/json"}


def make_handler(gateway: Gateway) -> type[BaseHTTPRequestHandler]:
	class GatewayHandler(BaseHTTPRequestHandler):
		protocol_version = "HTTP/1.1"

		def log_message(self, format: str, *args: object) -> None:
			print(f"gateway {self.address_string()} - {format % args}", flush=True)

		def _send(self, status: int, reason: str, body: bytes, headers: dict[str, str] | None = None) -> None:
			self.send_response(status, reason)
			for key, value in (headers or {}).items():
				self.send_header(key, value)
			self.send_header("Content-Length", str(len(body)))
			self.send_header("Connection", "close")
			self.end_headers()
			self.wfile.write(body)

		def do_GET(self) -> None:  # noqa: N802
			if self.path == "/health":
				status = gateway.status()
				body = json.dumps(status).encode("utf-8")
				self._send(200 if status["ok"] else 503, "OK", body, {"Content-Type": "application/json"})
				return
			status, reason, body, headers = gateway.forward("GET", self.path, b"", dict(self.headers))
			self._send(status, reason, body, headers)

		def do_POST(self) -> None:  # noqa: N802
			length = int(self.headers.get("Content-Length", "0"))
			body = self.rfile.read(length)
			try:
				payload = json.loads(body) if body else {}
			except json.JSONDecodeError:
				payload = {}
			if payload.get("stream") is True:
				self._send(400, "Bad Request", b'{"error":{"message":"streaming is not supported by this gateway"}}', {"Content-Type": "application/json"})
				return
			status, reason, response_body, headers = gateway.forward("POST", self.path, body, dict(self.headers))
			self._send(status, reason, response_body, headers)

	return GatewayHandler


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--workers", required=True, help="comma-separated worker URLs, e.g. http://127.0.0.1:8081,http://127.0.0.1:8082")
	parser.add_argument("--host", default="127.0.0.1")
	parser.add_argument("--port", type=int, default=8080)
	parser.add_argument("--timeout-seconds", type=float, default=180.0)
	args = parser.parse_args()
	workers = [Worker(name=f"worker-{index + 1}", url=url.strip()) for index, url in enumerate(args.workers.split(",")) if url.strip()]
	gateway = Gateway(workers, timeout_seconds=args.timeout_seconds)
	server = ThreadingHTTPServer((args.host, args.port), make_handler(gateway))
	print(f"gateway listening on http://{args.host}:{args.port} for {len(workers)} workers", flush=True)
	server.serve_forever()


if __name__ == "__main__":
	main()
