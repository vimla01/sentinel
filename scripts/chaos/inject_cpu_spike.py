#!/usr/bin/env python3
"""Spike demo-api's CPU usage for a fixed duration.

Example:
    python scripts/chaos/inject_cpu_spike.py --service demo-api --duration-seconds 90 --workers 2
"""

import argparse

from _common import add_common_args, post, resolve_base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--duration-seconds", type=float, default=60.0, help="How long the spike lasts.")
    parser.add_argument("--workers", type=int, default=2, help="Number of busy-loop threads to spin up.")
    args = parser.parse_args()

    base_url = resolve_base_url(args)
    print(f"triggering {args.duration_seconds}s CPU spike ({args.workers} workers) on {base_url}")
    status = post(
        base_url,
        "/debug/cpu-spike",
        {"duration_seconds": args.duration_seconds, "workers": args.workers},
    )
    print(status)


if __name__ == "__main__":
    main()
