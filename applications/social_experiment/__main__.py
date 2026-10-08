from __future__ import annotations

import argparse
from pathlib import Path

from KERN.log_manager import get_logger

from .runtime import create_runtime


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the social platform experiment")
    parser.add_argument("--config", required=True, help="runtime config file path")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args(argv)
    runtime = create_runtime(
        Path(__file__).resolve().parents[2], args.config,
        validate=not args.skip_validation,
    )
    try:
        events = runtime.run_configured()
        get_logger().info("system", "run_finished", context={
            "event_count": len(events), "ticks": int(runtime.world_state.game_time.total_ticks),
        })
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
