from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any


def _trace_root(run_dir: Path) -> Path:
	candidate = run_dir / "llm_traces"
	return candidate if candidate.is_dir() else run_dir


def load_traces(run_dir: str | Path, *, tick: int | None = None, agent_id: str = "") -> list[dict[str, Any]]:
	root = _trace_root(Path(run_dir))
	rows: list[dict[str, Any]] = []
	for path in sorted(root.rglob("*.json.gz")):
		with gzip.open(path, "rt", encoding="utf-8") as stream:
			payload = json.load(stream)
		if not isinstance(payload, dict):
			continue
		if tick is not None and int(payload.get("tick", 0) or 0) != int(tick):
			continue
		if agent_id and str(payload.get("actor_id", "") or "") != str(agent_id):
			continue
		rows.append(payload)
	return rows


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser(description="Inspect persisted KERN LLM decision traces")
	parser.add_argument("--run", required=True, help="checkpoint run directory or its llm_traces directory")
	parser.add_argument("--tick", type=int, default=None)
	parser.add_argument("--agent", default="", dest="agent_id")
	args = parser.parse_args(argv)
	print(json.dumps(load_traces(args.run, tick=args.tick, agent_id=args.agent_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
