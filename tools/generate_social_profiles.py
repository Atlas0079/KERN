from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import (
	CONFIG_SCHEMA_VERSION,
	DEFAULT_CONFIG_PATH,
	GENERATOR_VERSION,
	SCHEMA_VERSION,
	GenerationSpec,
	generate_social_profiles,
)


DEFAULT_OUTPUT = "KERN/external_runtimes/social_profiles/generated_social_profiles.json"


def _write_json_atomically(path: Path, data: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
		handle.write(json.dumps(data, ensure_ascii=False, indent=2))
		temporary = Path(handle.name)
	temporary.replace(path)


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate validated social_profile.v4 population data.")
	parser.add_argument("--count", type=int, default=100, help="Number of profiles to generate.")
	parser.add_argument("--seed", default="kern-social-profiles-v2", help="Experiment seed. Same spec and seed give identical profiles.")
	parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Complete or extending social_profile_generation.v3 population config.")
	parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output JSON path.")
	parser.add_argument("--include-audit", action="store_true", help="Embed eligible weights and applied soft-rule IDs in each profile.")
	args = parser.parse_args()

	if int(args.count) < 0:
		parser.error("--count cannot be negative")
	config_path = Path(args.config)
	if not config_path.is_absolute():
		config_path = ROOT / config_path
	spec = GenerationSpec.from_path(config_path)
	profiles = generate_social_profiles(count=int(args.count), seed=str(args.seed), spec=spec, include_audit=bool(args.include_audit))
	payload = {
		"schema_version": SCHEMA_VERSION,
		"generation": {
			"generator_version": GENERATOR_VERSION,
			"seed": str(args.seed),
			"population_id": spec.population_id,
			"rule_set": spec.rule_set,
			"config_schema_version": CONFIG_SCHEMA_VERSION,
			"config_sha256": spec.config_sha256,
			"config_source": spec.source_path,
			"count": len(profiles),
			"resolved_config": spec.config,
		},
		"profiles": profiles,
	}
	out_path = Path(args.output)
	if not out_path.is_absolute():
		out_path = ROOT / out_path
	_write_json_atomically(out_path, payload)
	print(f"wrote {len(profiles)} validated social profiles to {out_path}")


if __name__ == "__main__":
	main()
