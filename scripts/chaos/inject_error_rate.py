#!/usr/bin/env python3
"""Make demo-api randomly fail a fraction of requests for a fixed duration.

Example:
    python scripts/chaos/inject_error_rate.py --service demo-api --probability 0.4 --duration-seconds 120
"""

import argparse

from _common import add_common_args, post, resolve_base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--probability", type=float, default=0.3, help="Chance (0-1) a request returns 500.")
    parser.add_argument("--duration-seconds", type=float, default=60.0, help="How long the errors last.")
    args = parser.parse_args()

    base_url = resolve_base_url(args)
    print(f"injecting {args.probability:.0%} error rate into {base_url} for {args.duration_seconds}s")
    status = post(
        base_url,
        "/debug/error-rate",
        {"probability": args.probability, "duration_seconds": args.duration_seconds},
    )
    print(status)


if __name__ == "__main__":
    main()
