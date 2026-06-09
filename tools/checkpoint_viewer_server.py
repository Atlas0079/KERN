from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

from KERN.data.archive import ARCHIVE_MANIFEST_FILE_NAME, materialize_archive_state


TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8765
FRAME_CACHE_LIMIT = 64


class ArchiveViewerData:
	def __init__(self, archive_dir: Path) -> None:
		self.archive_dir = archive_dir.resolve()
		self.manifest = self._load_manifest()
		self._log_rows_by_tick: dict[int, list[dict]] | None = None
		self._frame_cache: OrderedDict[int, dict] = OrderedDict()

	def _load_manifest(self) -> dict:
		path = self.archive_dir / ARCHIVE_MANIFEST_FILE_NAME
		if not path.exists():
			raise FileNotFoundError(f"archive manifest not found: {path}")
		with path.open("r", encoding="utf-8") as f:
			payload = json.load(f)
		if not isinstance(payload, dict):
			raise ValueError(f"archive manifest must be object: {path}")
		return payload

	def manifest_payload(self) -> dict:
		last_tick = int(self.manifest.get("last_tick", 0) or 0)
		ticks = list(range(max(0, last_tick) + 1))
		return {
			**self.manifest,
			"archive_dir": str(self.archive_dir),
			"ticks": ticks,
		}

	def frame_payload(self, tick: int) -> dict:
		target_tick = int(tick)
		last_tick = int(self.manifest.get("last_tick", 0) or 0)
		if target_tick < 0 or target_tick > last_tick:
			raise ValueError(f"tick out of archive range: {target_tick}")
		if target_tick in self._frame_cache:
			frame = self._frame_cache.pop(target_tick)
			self._frame_cache[target_tick] = frame
			return frame
		world = materialize_archive_state(self.archive_dir, target_tick)
		frame = {
			"fileName": f"archive:{target_tick}",
			"tick": target_tick,
			"timeStr": self._time_str_from_world(world),
			"runId": str(self.manifest.get("run_id", "") or ""),
			"logScope": "tick",
			"world": world,
			"log": self._log_rows_for_tick(target_tick),
		}
		self._frame_cache[target_tick] = frame
		while len(self._frame_cache) > FRAME_CACHE_LIMIT:
			self._frame_cache.popitem(last=False)
		return frame

	def _time_str_from_world(self, world: dict) -> str:
		world_state = world.get("world_state", {}) if isinstance(world, dict) else {}
		if not isinstance(world_state, dict):
			return ""
		return str(world_state.get("time_str", "") or world_state.get("current_time", "") or "")

	def _log_rows_for_tick(self, tick: int) -> list[dict]:
		if self._log_rows_by_tick is None:
			self._log_rows_by_tick = self._load_simulation_log()
		return list(self._log_rows_by_tick.get(int(tick), []))

	def _load_simulation_log(self) -> dict[int, list[dict]]:
		path = self.archive_dir / "simulation_log.json"
		if not path.exists():
			return {}
		with path.open("r", encoding="utf-8") as f:
			payload = json.load(f)
		if isinstance(payload, dict):
			rows = payload.get("rows", payload.get("log", []))
		else:
			rows = payload
		grouped: dict[int, list[dict]] = {}
		for row in rows if isinstance(rows, list) else []:
			if not isinstance(row, dict):
				continue
			try:
				row_tick = int(row.get("tick", 0) or 0)
			except Exception:
				continue
			grouped.setdefault(row_tick, []).append(row)
		return grouped


class CheckpointViewerHandler(BaseHTTPRequestHandler):
	server_version = "CheckpointViewer/1.0"

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path == "/api/manifest":
			self._write_json(self.server.viewer_data.manifest_payload())
			return
		if parsed.path.startswith("/api/tick/"):
			tick_text = unquote(parsed.path.removeprefix("/api/tick/")).strip()
			if not tick_text:
				self._write_error(HTTPStatus.BAD_REQUEST, "tick is required")
				return
			try:
				tick = int(tick_text)
				payload = self.server.viewer_data.frame_payload(tick)
			except Exception as error:
				self._write_error(HTTPStatus.BAD_REQUEST, str(error))
				return
			self._write_json(payload)
			return
		self._serve_static(parsed.path)

	def log_message(self, format: str, *args) -> None:
		print(f"{self.address_string()} - {format % args}")

	def _serve_static(self, request_path: str) -> None:
		relative = unquote(request_path.lstrip("/")) or "checkpoint_viewer.html"
		path = (TOOLS_DIR / relative).resolve()
		if not str(path).startswith(str(TOOLS_DIR.resolve())) or not path.is_file():
			self._write_error(HTTPStatus.NOT_FOUND, "not found")
			return
		content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
		data = path.read_bytes()
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _write_json(self, payload: dict) -> None:
		data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def _write_error(self, status: HTTPStatus, message: str) -> None:
		data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)


class CheckpointViewerServer(ThreadingHTTPServer):
	def __init__(self, server_address: tuple[str, int], handler_class, viewer_data: ArchiveViewerData) -> None:
		super().__init__(server_address, handler_class)
		self.viewer_data = viewer_data


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Serve checkpoint viewer for a run archive.")
	parser.add_argument("--archive-dir", required=True, help="Path to a run archive directory.")
	parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
	parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind.")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	viewer_data = ArchiveViewerData(Path(args.archive_dir))
	server = CheckpointViewerServer((str(args.host), int(args.port)), CheckpointViewerHandler, viewer_data)
	url = f"http://{args.host}:{args.port}/checkpoint_viewer.html"
	print(f"Serving checkpoint viewer at {url}")
	print(f"Archive: {viewer_data.archive_dir}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()


if __name__ == "__main__":
	main()
