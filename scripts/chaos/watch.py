#!/usr/bin/env python3
"""Watch the predictor's live risk assessment while a chaos scenario runs.

Run this in a second terminal alongside any inject_*.py script.

Example:
    kubectl -n sentinel port-forward svc/predictor 8000:8080
    python scripts/chaos/watch.py --predictor-url http://localhost:8000
"""

import argparse
import time

import httpx

from _common import eprint, get


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predictor-url",
        default="http://localhost:8000",
        help="Predictor base URL (e.g. after `kubectl port-forward svc/predictor 8000:8080`).",
    )
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args()

    print(f"watching {args.predictor_url}/risk every {args.interval_seconds}s (Ctrl+C to stop)")
    try:
        while True:
            try:
                risk = get(args.predictor_url, "/risk")
            except httpx.HTTPError as exc:
                eprint(f"predictor unreachable: {exc}")
            else:
                metrics = " ".join(
                    f"{name}(z={data['z_score']:.2f}{'!' if data['alerting'] else ''})"
                    for name, data in risk["metrics"].items()
                )
                print(f"overall_risk={risk['overall_risk']:.2f} {metrics}")
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
