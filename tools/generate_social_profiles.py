from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import generate_social_profiles


DEFAULT_OUTPUT = "KERN/external_runtimes/social_profiles/generated_social_profiles.json"


def _write_json(path: Path, data: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
	path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate deterministic weighted social-account profile samples.")
	parser.add_argument("--count", type=int, default=100, help="Number of profiles to generate.")
	parser.add_argument("--seed", default="kern-social-profiles-v1", help="Random seed. Same seed gives same output.")
	parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output path.")
	parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format.")
	parser.add_argument("--include-debug", action="store_true", help="Include sampling trace and adjusted weights.")
	args = parser.parse_args()

	profiles = generate_social_profiles(count=max(0, int(args.count)), seed=str(args.seed), include_debug=bool(args.include_debug))
	out_path = Path(args.output)
	if not out_path.is_absolute():
		out_path = ROOT / out_path

	if args.format == "jsonl":
		_write_jsonl(out_path, profiles)
	else:
		_write_json(out_path, {"seed": str(args.seed), "count": len(profiles), "profiles": profiles})
	print(f"wrote {len(profiles)} social profiles to {out_path}")


if __name__ == "__main__":
	main()
