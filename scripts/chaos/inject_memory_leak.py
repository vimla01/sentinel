#!/usr/bin/env python3
"""Grow demo-api's memory usage in steps to simulate a slow memory leak.

Example:
    python scripts/chaos/inject_memory_leak.py --service demo-api
    python scripts/chaos/inject_memory_leak.py --base-url http://localhost:8080 --chunk-mb 30 --steps 8
"""

import argparse
import time

from _common import add_common_args, post, resolve_base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--chunk-mb", type=int, default=20, help="Memory to allocate per step, in MB.")
    parser.add_argument("--steps", type=int, default=10, help="Number of leak steps to run.")
    parser.add_argument("--interval-seconds", type=float, default=15.0, help="Delay between steps.")
    args = parser.parse_args()

    base_url = resolve_base_url(args)
    print(
        f"injecting memory leak into {base_url} "
        f"({args.steps} x {args.chunk_mb}MB, every {args.interval_seconds}s)"
    )
    for step in range(1, args.steps + 1):
        status = post(base_url, "/debug/leak-memory", {"chunk_mb": args.chunk_mb})
        print(f"step {step}/{args.steps}: memory_leak_mb={status['memory_leak_mb']}")
        if step < args.steps:
            time.sleep(args.interval_seconds)
    print(f"done. reset with: python scripts/chaos/reset.py --service {args.service}")


if __name__ == "__main__":
    main()
