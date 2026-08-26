#!/usr/bin/env python3
"""Add artificial latency to every demo-api response for a fixed duration.

Example:
    python scripts/chaos/inject_latency.py --service demo-api --delay-ms 800 --duration-seconds 120
"""

import argparse

from _common import add_common_args, post, resolve_base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--delay-ms", type=int, default=500, help="Extra latency to add per request.")
    parser.add_argument("--duration-seconds", type=float, default=60.0, help="How long the latency lasts.")
    args = parser.parse_args()

    base_url = resolve_base_url(args)
    print(f"injecting {args.delay_ms}ms latency into {base_url} for {args.duration_seconds}s")
    status = post(
        base_url,
        "/debug/latency",
        {"delay_ms": args.delay_ms, "duration_seconds": args.duration_seconds},
    )
    print(status)


if __name__ == "__main__":
    main()
