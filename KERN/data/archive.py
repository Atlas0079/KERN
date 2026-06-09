from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.world_state import WorldState
from .checkpoint import _build_combined_log_rows, _world_dict_from_world_state


ARCHIVE_MANIFEST_FILE_NAME = "manifest.json"


def _json_bytes(value: Any) -> bytes:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def state_hash(state: dict[str, Any]) -> str:
	return hashlib.sha256(_json_bytes(state)).hexdigest()


def _write_json_gz(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp_path = path.with_suffix(path.suffix + ".tmp")
	with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	tmp_path.replace(path)


def _read_json_gz(path: Path) -> dict[str, Any]:
	with gzip.open(path, "rt", encoding="utf-8") as f:
		payload = json.load(f)
	if not isinstance(payload, dict):
		raise ValueError(f"archive json payload must be object: {path}")
	return payload


def archive_state_from_world_state(ws: WorldState) -> dict[str, Any]:
	return _world_dict_from_world_state(ws)


def _path_sort_key(path: list[str]) -> tuple[int, str]:
	return (len(path), ".".join(path))


def build_state_delta(before: Any, after: Any, path: list[str] | None = None) -> list[dict[str, Any]]:
	cur_path = list(path or [])
	if before == after:
		return []
	if isinstance(before, dict) and isinstance(after, dict):
		changes: list[dict[str, Any]] = []
		for key in sorted(set(before.keys()) - set(after.keys())):
			changes.append({"op": "delete", "path": cur_path + [str(key)]})
		for key in sorted(set(after.keys()) - set(before.keys())):
			changes.append({"op": "set", "path": cur_path + [str(key)], "value": after[key]})
		for key in sorted(set(before.keys()) & set(after.keys())):
			changes.extend(build_state_delta(before[key], after[key], cur_path + [str(key)]))
		return sorted(changes, key=lambda x: _path_sort_key([str(p) for p in x.get("path", [])]))
	if isinstance(before, list) and isinstance(after, list):
		if len(after) >= len(before) and after[: len(before)] == before:
			values = after[len(before) :]
			if values:
				return [{"op": "append", "path": cur_path, "values": values}]
			return []
		return [{"op": "replace", "path": cur_path, "value": after}]
	return [{"op": "replace", "path": cur_path, "value": after}]


def _resolve_parent(root: dict[str, Any], path: list[str]) -> tuple[Any, str]:
	if not path:
		raise ValueError("delta path must not be empty")
	cur: Any = root
	for key in path[:-1]:
		if not isinstance(cur, dict):
			raise ValueError(f"delta path parent is not object: {path}")
		cur = cur.setdefault(str(key), {})
	return cur, str(path[-1])


def apply_state_delta(state: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
	next_state = json.loads(json.dumps(state, ensure_ascii=False))
	for change in list(changes or []):
		if not isinstance(change, dict):
			continue
		op = str(change.get("op", "") or "")
		path = [str(x) for x in list(change.get("path", []) or [])]
		parent, key = _resolve_parent(next_state, path)
		if op == "delete":
			if isinstance(parent, dict):
				parent.pop(key, None)
			continue
		if op in {"set", "replace"}:
			if not isinstance(parent, dict):
				raise ValueError(f"delta {op} parent is not object: {path}")
			parent[key] = change.get("value")
			continue
		if op == "append":
			if not isinstance(parent, dict):
				raise ValueError(f"delta append parent is not object: {path}")
			current = parent.get(key, [])
			if not isinstance(current, list):
				raise ValueError(f"delta append target is not list: {path}")
			values = change.get("values", []) or []
			if not isinstance(values, list):
				raise ValueError(f"delta append values must be list: {path}")
			parent[key] = current + list(values)
			continue
		raise ValueError(f"unknown delta op: {op}")
	return next_state


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
	if not path.exists():
		return []
	rows: list[dict[str, Any]] = []
	with gzip.open(path, "rt", encoding="utf-8") as f:
		for line in f:
			text = line.strip()
			if not text:
				continue
			row = json.loads(text)
			if isinstance(row, dict):
				rows.append(row)
	return rows


@dataclass
class ArchiveRecorder:
	archive_dir: str
	run_id: str
	snapshot_interval_ticks: int = 60
	include_logs: bool = True
	last_state: dict[str, Any] | None = None
	last_hash: str = ""
	snapshots: list[dict[str, Any]] = field(default_factory=list)
	delta_chunks: dict[str, dict[str, Any]] = field(default_factory=dict)

	def __post_init__(self) -> None:
		self.snapshot_interval_ticks = max(1, int(self.snapshot_interval_ticks or 60))
		Path(self.archive_dir).mkdir(parents=True, exist_ok=True)
		(Path(self.archive_dir) / "snapshots").mkdir(parents=True, exist_ok=True)
		(Path(self.archive_dir) / "deltas").mkdir(parents=True, exist_ok=True)
		self._reset_archive_outputs()
		self._write_manifest(last_tick=0)

	def _reset_archive_outputs(self) -> None:
		root = Path(self.archive_dir)
		manifest = root / ARCHIVE_MANIFEST_FILE_NAME
		if manifest.exists():
			manifest.unlink()
		for path in (root / "snapshots").glob("snapshot_*.json.gz"):
			path.unlink()
		for path in (root / "deltas").glob("deltas_*.jsonl.gz"):
			path.unlink()
		for path in list(root.glob("tick_*.json")) + list(root.glob("tick_*.tmp")):
			path.unlink()

	def record_tick(self, ws: WorldState) -> None:
		tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
		state = archive_state_from_world_state(ws)
		cur_hash = state_hash(state)
		if self.last_state is None or tick % self.snapshot_interval_ticks == 0:
			self._write_snapshot(ws, state, cur_hash)
		else:
			changes = build_state_delta(self.last_state, state)
			self._append_delta(ws, tick, cur_hash, changes)
		self.last_state = state
		self.last_hash = cur_hash
		self._write_manifest(last_tick=tick)

	def _write_snapshot(self, ws: WorldState, state: dict[str, Any], cur_hash: str) -> None:
		tick = int(getattr(ws.game_time, "total_ticks", 0) or 0)
		path = Path(self.archive_dir) / "snapshots" / f"snapshot_{tick:06d}.json.gz"
		payload: dict[str, Any] = {
			"meta": {
				"schema_version": "run_snapshot.v1",
				"run_id": str(self.run_id or ""),
				"tick": tick,
				"time_str": ws.game_time.time_to_string(),
				"state_hash": cur_hash,
				"event_seq": int(getattr(ws, "_event_seq", 0) or 0),
				"interaction_seq": int(getattr(ws, "_interaction_seq", 0) or 0),
			},
			"world": state,
		}
		if self.include_logs:
			payload["log"] = _build_combined_log_rows(ws, tick=tick)
		_write_json_gz(path, payload)
		self.snapshots.append({"tick": tick, "path": str(path.relative_to(Path(self.archive_dir))), "state_hash": cur_hash})

	def _append_delta(self, ws: WorldState, tick: int, cur_hash: str, changes: list[dict[str, Any]]) -> None:
		start = (tick // self.snapshot_interval_ticks) * self.snapshot_interval_ticks
		end = start + self.snapshot_interval_ticks - 1
		path = Path(self.archive_dir) / "deltas" / f"deltas_{start:06d}_{end:06d}.jsonl.gz"
		row: dict[str, Any] = {
			"schema_version": "run_delta.v1",
			"run_id": str(self.run_id or ""),
			"tick": tick,
			"before_hash": str(self.last_hash or ""),
			"after_hash": cur_hash,
			"changes": changes,
		}
		if self.include_logs:
			row["log"] = _build_combined_log_rows(ws, tick=tick)
		with gzip.open(path, "at", encoding="utf-8") as f:
			f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
		key = path.name
		self.delta_chunks[key] = {"start_tick": start, "end_tick": end, "path": str(path.relative_to(Path(self.archive_dir)))}

	def _write_manifest(self, *, last_tick: int) -> None:
		payload = {
			"schema_version": "run_archive.v1",
			"run_id": str(self.run_id or ""),
			"last_tick": int(last_tick),
			"snapshot_interval_ticks": int(self.snapshot_interval_ticks),
			"snapshots": sorted(self.snapshots, key=lambda x: int(x.get("tick", 0) or 0)),
			"delta_chunks": sorted(self.delta_chunks.values(), key=lambda x: int(x.get("start_tick", 0) or 0)),
		}
		path = Path(self.archive_dir) / ARCHIVE_MANIFEST_FILE_NAME
		tmp_path = path.with_suffix(".tmp")
		with tmp_path.open("w", encoding="utf-8") as f:
			json.dump(payload, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
		tmp_path.replace(path)


def load_snapshot_state(snapshot_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
	payload = _read_json_gz(snapshot_path)
	meta = dict(payload.get("meta", {}) or {})
	state = payload.get("world", {}) or {}
	if not isinstance(state, dict) or not state:
		raise ValueError(f"snapshot world missing: {snapshot_path}")
	expected = str(meta.get("state_hash", "") or "")
	actual = state_hash(state)
	if expected and expected != actual:
		raise ValueError(f"snapshot hash mismatch: {snapshot_path}")
	return meta, state


def materialize_archive_state(archive_dir: str | Path, target_tick: int) -> dict[str, Any]:
	root = Path(str(archive_dir))
	snapshots = sorted((root / "snapshots").glob("snapshot_*.json.gz"))
	if not snapshots:
		raise ValueError(f"archive has no snapshots: {root}")
	target = int(target_tick)
	chosen: Path | None = None
	chosen_tick = -1
	for path in snapshots:
		name = path.stem.replace("snapshot_", "").replace(".json", "")
		try:
			tick = int(name)
		except Exception:
			continue
		if tick <= target and tick >= chosen_tick:
			chosen = path
			chosen_tick = tick
	if chosen is None:
		raise ValueError(f"archive has no snapshot at or before tick {target}: {root}")
	meta, state = load_snapshot_state(chosen)
	current_tick = int(meta.get("tick", chosen_tick) or chosen_tick)
	if current_tick == target:
		return state
	for chunk in sorted((root / "deltas").glob("deltas_*.jsonl.gz")):
		for row in _load_jsonl(chunk):
			tick = int(row.get("tick", 0) or 0)
			if tick <= current_tick or tick > target:
				continue
			before_hash = str(row.get("before_hash", "") or "")
			actual_before = state_hash(state)
			if before_hash and before_hash != actual_before:
				raise ValueError(f"delta before_hash mismatch at tick {tick}: {chunk}")
			state = apply_state_delta(state, list(row.get("changes", []) or []))
			after_hash = str(row.get("after_hash", "") or "")
			actual_after = state_hash(state)
			if after_hash and after_hash != actual_after:
				raise ValueError(f"delta after_hash mismatch at tick {tick}: {chunk}")
			current_tick = tick
			if current_tick == target:
				return state
	raise ValueError(f"archive cannot materialize tick {target}; stopped at {current_tick}")
