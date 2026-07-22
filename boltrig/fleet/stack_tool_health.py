"""Owner-local liveness evidence for first-party stack tools.

The kernel image owns Herdr, while the fleet image owns OpenCode, Browser Use,
and the loopback Chromium instance Browser Use drives.  The kernel therefore
must not pretend it can execute fleet binaries.  Fleet publishes a short-lived,
redacted Redis receipt after probing its own tools; ``/readyz`` combines that
receipt with a kernel-local Herdr probe.

Receipts deliberately contain no command output, paths, versions, environment
values, or connection details.  Subprocess probes always use an argv vector and
never invoke a shell.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Mapping

from .stack_tool_receipts import (
    publish_fleet_tool_receipt,
    receipt_signing_key,
)

log = logging.getLogger("boltrig.stack_tool_health")

_DEFAULT_RECEIPT_TTL = 30.0
_DEFAULT_HEARTBEAT_INTERVAL = 10.0
_DEFAULT_PROBE_TIMEOUT = 4.0


def _bounded_number(
    env: Mapping[str, str], name: str, default: float, low: float, high: float
) -> float:
    try:
        value = float(env.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(low, min(value, high))


def receipt_ttl(env: Mapping[str, str]) -> float:
    """Configured receipt lifetime, bounded to avoid stale or durable claims."""
    return _bounded_number(
        env,
        "BOLTRIG_STACK_TOOL_RECEIPT_TTL",
        _DEFAULT_RECEIPT_TTL,
        15.0,
        300.0,
    )


def heartbeat_interval(env: Mapping[str, str]) -> float:
    """Heartbeat period leaves room for the next bounded probe and publish."""
    ttl = receipt_ttl(env)
    configured = _bounded_number(
        env,
        "BOLTRIG_STACK_TOOL_HEARTBEAT_INTERVAL",
        _DEFAULT_HEARTBEAT_INTERVAL,
        1.0,
        120.0,
    )
    return min(configured, ttl / 3.0)


def probe_timeout(env: Mapping[str, str]) -> float:
    configured = _bounded_number(
        env,
        "BOLTRIG_STACK_TOOL_PROBE_TIMEOUT",
        _DEFAULT_PROBE_TIMEOUT,
        0.1,
        10.0,
    )
    # One cycle costs at most a probe timeout plus a Redis publish timeout. In
    # combination with heartbeat_interval's TTL/3 ceiling this leaves a wide
    # margin before the previous receipt expires, even at the minimum TTL.
    return min(configured, receipt_ttl(env) / 4.0)


def _probe_environment(env: Mapping[str, str], *, state_root: str) -> dict[str, str]:
    """Minimal environment for version probes; deployment secrets stay out."""
    root = state_root.rstrip("/")
    return {
        # Use only the tool's stack-owned roots. Some CLIs initialise their
        # local harness even for --version, so an intentionally absent home
        # would create false negatives; no provider or deployment secrets flow.
        "HOME": f"{root}/home",
        "LANG": "C.UTF-8",
        "PATH": env.get("PATH") or os.defpath,
        "XDG_CACHE_HOME": f"{root}/cache",
        "XDG_CONFIG_HOME": f"{root}/config",
        "XDG_DATA_HOME": f"{root}/data",
        "XDG_STATE_HOME": f"{root}/state",
    }


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.kill()
    try:
        await process.wait()
    except ProcessLookupError:
        pass


async def _probe_version(
    executable: str,
    timeout_s: float,
    env: Mapping[str, str],
    *,
    state_root: str,
) -> bool:
    """Execute exactly ``<binary> --version`` with bounded, discarded output."""
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                executable,
                "--version",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=_probe_environment(env, state_root=state_root),
            ),
            timeout=timeout_s,
        )
        return await asyncio.wait_for(process.wait(), timeout=timeout_s) == 0
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        if process is not None:
            await _stop_process(process)


async def probe_herdr(env: Mapping[str, str], timeout_s: float) -> bool:
    """Prove the kernel-owned Herdr executable can actually start."""
    executable = (env.get("HERDR_BIN") or "herdr").strip()
    if not executable:
        return False
    state_root = (env.get("BOLTRIG_HERDR_HOME") or "/var/lib/boltrig/herdr").strip()
    return bool(state_root) and await _probe_version(
        executable,
        timeout_s,
        env,
        state_root=state_root,
    )


async def _probe_browser_cdp(
    timeout_s: float, *, host: str = "127.0.0.1", port: int = 9222
) -> bool:
    """Verify the fleet-owned loopback endpoint is a live Chromium CDP server."""
    writer: asyncio.StreamWriter | None = None
    try:
        reader, connected_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout_s
        )
        writer = connected_writer
        connected_writer.write(
            b"GET /json/version HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        await asyncio.wait_for(connected_writer.drain(), timeout=timeout_s)
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout_s)
        header_lines = head[:-4].split(b"\r\n")
        if not header_lines or b" 200 " not in header_lines[0]:
            return False
        headers: dict[bytes, bytes] = {}
        for line in header_lines[1:]:
            name, separator, value = line.partition(b":")
            if not separator:
                return False
            headers[name.strip().lower()] = value.strip()
        if b"transfer-encoding" in headers:
            return False
        try:
            length = int(headers.get(b"content-length", b""))
        except ValueError:
            return False
        if length < 2 or length > 65536:
            return False
        body = await asyncio.wait_for(reader.readexactly(length), timeout=timeout_s)
        payload = json.loads(body)
        return bool(
            isinstance(payload, Mapping)
            and isinstance(payload.get("Browser"), str)
            and isinstance(payload.get("webSocketDebuggerUrl"), str)
        )
    except (
        OSError,
        ValueError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
        asyncio.TimeoutError,
    ):
        return False
    finally:
        active_writer = writer
        if active_writer is not None:
            active_writer.close()
            try:
                await active_writer.wait_closed()
            except OSError:
                pass


async def probe_fleet_tools(env: Mapping[str, str], timeout_s: float) -> dict[str, bool]:
    """Probe only tools that execute in the fleet worker container.

    The probe pair matches the readiness required set (decision 0012): OpenCode
    is staged-cutover residue and is no longer probed - a missing/unhealthy
    residue binary must never trip the heartbeat warning."""
    browser = (env.get("BOLTRIG_BROWSER_CLI_BIN") or "browser-use").strip()
    browser_root = (env.get("BOLTRIG_BROWSER_CLI_HOME") or "/var/lib/boltrig/browser-cli").strip()
    if not browser or not browser_root:
        return {"browser-cli": False}
    try:
        browser_ok, cdp_ok = await asyncio.wait_for(
            asyncio.gather(
                _probe_version(browser, timeout_s, env, state_root=browser_root),
                _probe_browser_cdp(timeout_s),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return {"browser-cli": False}
    return {"browser-cli": browser_ok and cdp_ok}


async def run_fleet_tool_heartbeat(
    tenant_id: str,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Continuously publish fleet-local proof; failures remain retryable."""
    runtime_env = env if env is not None else os.environ
    redis_url = str(runtime_env.get("REDIS_URL") or "").strip()
    if not redis_url:
        log.info("fleet stack-tool heartbeat disabled (REDIS_URL not configured)")
        return
    signing_key = receipt_signing_key(runtime_env)
    if signing_key is None:
        log.warning("fleet stack-tool heartbeat disabled (audit HMAC key not configured)")
        return
    ttl_s = receipt_ttl(runtime_env)
    interval_s = heartbeat_interval(runtime_env)
    timeout_s = probe_timeout(runtime_env)
    while True:
        try:
            statuses = await probe_fleet_tools(runtime_env, timeout_s)
            await publish_fleet_tool_receipt(
                redis_url,
                tenant_id,
                statuses,
                ttl_s=ttl_s,
                timeout_s=timeout_s,
                signing_key=signing_key,
            )
            if not all(statuses.values()):
                log.warning("fleet stack-tool live probe failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            # No exception details: a Redis URL or tool wrapper may include
            # deployment-sensitive values. /readyz will report coarse failure.
            log.warning("fleet stack-tool heartbeat publish failed")
        await asyncio.sleep(interval_s)
