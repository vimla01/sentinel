#!/usr/bin/env python3
"""Clear all chaos state on demo-api (stop leaks/spikes/latency/errors).

Example:
    python scripts/chaos/reset.py --service demo-api
"""

import argparse

from _common import add_common_args, post, resolve_base_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    args = parser.parse_args()

    base_url = resolve_base_url(args)
    status = post(base_url, "/debug/reset")
    print("reset:", status)


if __name__ == "__main__":
    main()
