"""Shared harness for script-runtime builtin adapters (subprocess CLIs).

The browser-cli adapter shells out to an external CLI with the
same machinery: a scrubbed child environment (no user/provider secrets leak
into the child), an output cap, timeout-with-termination, and stdout
JSON-or-text decoding. One home so the two adapters cannot drift.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

MAX_OUTPUT = 128_000
BASE_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


def base_env() -> dict[str, str]:
    """The scrubbed base child environment: only the allow-listed process keys."""
    return {key: os.environ[key] for key in BASE_ENV_KEYS if os.environ.get(key)}


def schema(required: list[str] | None = None, props: dict[str, Any] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


def json_or_text(stdout: str) -> dict[str, Any]:
    try:
        data = json.loads(stdout or "{}")
    except ValueError:
        return {"text": stdout[:MAX_OUTPUT]}
    return data if isinstance(data, dict) else {"value": data}


async def terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except Exception:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                return
            await proc.wait()


async def run_process(
    argv: list[str],
    *,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
    missing: str,
    timed_out: str,
) -> tuple[int, str, str]:
    """Run ``argv`` with an output cap and timeout termination.

    ``missing`` / ``timed_out`` are the fixed stderr strings returned for a
    missing binary (exit 127) and a timeout (exit 124) - fixed strings, never
    anything derived from the child or the environment.
    """
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out_b, err_b = await asyncio.wait_for(
            proc.communicate(stdin.encode()) if stdin is not None else proc.communicate(),
            timeout,
        )
    except FileNotFoundError:
        return 127, "", missing
    except TimeoutError:
        if proc is not None:
            await terminate(proc)
        return 124, "", timed_out
    return (
        int(proc.returncode or 0),
        out_b.decode("utf-8", errors="replace")[:MAX_OUTPUT],
        err_b.decode("utf-8", errors="replace")[:MAX_OUTPUT],
    )
