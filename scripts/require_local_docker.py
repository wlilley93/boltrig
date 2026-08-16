"""Refuse to run a disposable recovery drill against a remote Docker daemon."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Mapping
from urllib.parse import urlsplit


def validate_local_docker_endpoint(endpoint: str) -> str:
    """Return a local endpoint or reject a remote/ambiguous Docker target."""
    value = endpoint.strip()
    if value.startswith(("unix://", "npipe://", "fd://")):
        return value
    parsed = urlsplit(value)
    if parsed.scheme in {"tcp", "http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        return value
    raise ValueError(
        "recovery rehearsal requires a local Docker endpoint; "
        "remote and ambiguous contexts are refused"
    )


def _docker(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("docker", *arguments),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ValueError("Docker context inspection failed") from exc
    return completed.stdout.strip()


def effective_docker_endpoint(env: Mapping[str, str] | None = None) -> str:
    """Resolve Docker's effective endpoint without contacting the daemon."""
    values = os.environ if env is None else env
    override = str(values.get("DOCKER_HOST") or "").strip()
    if override:
        return validate_local_docker_endpoint(override)

    context = str(values.get("DOCKER_CONTEXT") or "").strip()
    if not context:
        context = _docker("context", "show")
    if not context:
        raise ValueError("Docker context is empty")
    raw_endpoint = _docker(
        "context",
        "inspect",
        context,
        "--format",
        "{{json .Endpoints.docker.Host}}",
    )
    try:
        endpoint = json.loads(raw_endpoint)
    except json.JSONDecodeError as exc:
        raise ValueError("Docker context returned a malformed endpoint") from exc
    if not isinstance(endpoint, str):
        raise ValueError("Docker context did not return one endpoint")
    return validate_local_docker_endpoint(endpoint)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        effective_docker_endpoint()
    except ValueError as exc:
        parser.error(str(exc))
    print("local Docker endpoint verified for disposable recovery rehearsal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
