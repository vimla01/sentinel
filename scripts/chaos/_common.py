"""Shared CLI helpers for the chaos injection scripts."""

import argparse
import sys

import httpx


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--service",
        default="demo-api",
        help="In-cluster service name to target (used to build the default base URL).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the target base URL, e.g. http://localhost:8080 when using kubectl port-forward.",
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port to use when deriving the URL from --service."
    )


def resolve_base_url(args: argparse.Namespace) -> str:
    if args.base_url:
        return args.base_url.rstrip("/")
    return f"http://{args.service}:{args.port}"


def _url(base_url: str, path: str) -> str:
    return f"{base_url}{path if path.startswith('/') else '/' + path}"


def post(base_url: str, path: str, payload: dict | None = None) -> dict:
    response = httpx.post(_url(base_url, path), json=payload or {}, timeout=10.0)
    response.raise_for_status()
    return response.json()


def get(base_url: str, path: str) -> dict:
    response = httpx.get(_url(base_url, path), timeout=10.0)
    response.raise_for_status()
    return response.json()


def eprint(*values: object) -> None:
    print(*values, file=sys.stderr)
