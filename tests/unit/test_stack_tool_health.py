"""Owner-local stack-tool probes and redacted receipt validation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from boltrig.fleet.stack_tool_health import (
    _probe_browser_cdp,
    heartbeat_interval,
    probe_fleet_tools,
    probe_herdr,
    probe_timeout,
)
from boltrig.fleet.stack_tool_receipts import (
    _receipt_payload,
    validate_fleet_tool_receipt,
)

pytestmark = pytest.mark.unit
_SIGNING_KEY = b"unit-test-stack-tool-receipt-key"
_TENANT = "acme"
# These cases are all about a deployment that DOES declare browser automation.
# Since 2026-07-31 the required tool set is derived from the manifest, so a test
# that left it implicit would silently become a test of the empty set - passing
# while asserting nothing (the receipt cases below would all read 'ok').
_WANTS_BROWSER = frozenset({"browser-cli"})


@pytest.mark.invariant("FR-OPS-03")
async def test_herdr_probe_executes_exact_argv_without_a_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Shell metacharacters are legal filename characters.  This succeeds only
    # when the configured path is passed as one exact executable argv element.
    executable = tmp_path / "herdr; exit 9"
    executable.write_text(
        "#!/bin/sh\n"
        "printf 'deployment-secret'\n"
        "printf 'deployment-secret' >&2\n"
        '[ "$#" -eq 1 ] && [ "$1" = \'--version\' ]\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)

    assert await probe_herdr({"HERDR_BIN": str(executable)}, 0.5) is True
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.invariant("FR-OPS-03")
async def test_fleet_probe_requires_both_binaries_and_live_loopback_cdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def version(executable: str, _timeout: float, _env, *, state_root: str) -> bool:
        assert state_root.startswith("/var/lib/boltrig/")
        seen.append(executable)
        return True

    async def dead_cdp(_timeout: float) -> bool:
        return False

    monkeypatch.setattr("boltrig.fleet.stack_tool_health._probe_version", version)
    monkeypatch.setattr("boltrig.fleet.stack_tool_health._probe_browser_cdp", dead_cdp)
    # This test is about a deployment that WANTS a browser: what the probe does
    # when it is not wanted at all is tested separately
    # (tests/security/test_browser_runtime_gate.py), and leaving it implicit here
    # would quietly turn this into a test of the no-browser path - green, and
    # asserting nothing about either binary.
    monkeypatch.setattr(
        "boltrig.fleet.browser_runtime.browser_automation_wanted", lambda *_a, **_k: True
    )

    statuses = await probe_fleet_tools(
        {
            "BOLTRIG_OPENCODE_BIN": "/stack/opencode",  # residue: must be ignored
            "BOLTRIG_BROWSER_CLI_BIN": "/stack/browser-use",
        },
        0.5,
    )

    assert seen == ["/stack/browser-use"]
    assert statuses == {"browser-cli": False}


@pytest.mark.invariant("FR-OPS-03")
async def test_browser_probe_accepts_only_a_chromium_cdp_response() -> None:
    async def handler(reader, writer) -> None:
        await reader.readuntil(b"\r\n\r\n")
        body = json.dumps(
            {
                "Browser": "Chrome/150",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/test",
            }
        ).encode("utf-8")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
        )
        await writer.drain()
        # Real HTTP transports may split headers and body across packets.
        await asyncio.sleep(0.05)
        writer.write(body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        assert await _probe_browser_cdp(0.5, port=port) is True


@pytest.mark.invariant("FR-OPS-03")
@pytest.mark.parametrize(
    ("payload", "now", "expected"),
    [
        (None, 100.0, (False, "missing")),
        ("not-json", 100.0, (False, "malformed")),
        (
            _receipt_payload(
                {"browser-cli": True},
                _SIGNING_KEY,
                _TENANT,
                required=_WANTS_BROWSER,
                now=60.0,
            ),
            100.0,
            (False, "stale"),
        ),
        (
            _receipt_payload(
                {"browser-cli": True},
                _SIGNING_KEY,
                _TENANT,
                required=_WANTS_BROWSER,
                now=110.0,
            ),
            100.0,
            (False, "future"),
        ),
        (
            _receipt_payload(
                {"browser-cli": False},
                _SIGNING_KEY,
                _TENANT,
                required=_WANTS_BROWSER,
                now=100.0,
            ),
            100.0,
            (False, "degraded"),
        ),
        (
            _receipt_payload(
                {"browser-cli": True},
                _SIGNING_KEY,
                _TENANT,
                required=_WANTS_BROWSER,
                now=100.0,
            ),
            100.0,
            (True, "ok"),
        ),
    ],
)
def test_fleet_receipt_requires_schema_freshness_and_all_tools(
    payload, now: float, expected: tuple[bool, str]
) -> None:
    assert (
        validate_fleet_tool_receipt(
            payload,
            max_age_s=30.0,
            signing_key=_SIGNING_KEY,
            tenant_id=_TENANT,
            now=now,
            required=_WANTS_BROWSER,
        )
        == expected
    )


@pytest.mark.invariant("FR-OPS-03")
def test_fleet_receipt_rejects_forged_or_cross_deployment_evidence() -> None:
    receipt = _receipt_payload(
        {"browser-cli": True},
        b"different-deployment-key",
        _TENANT,
        required=_WANTS_BROWSER,
        now=100.0,
    )

    assert validate_fleet_tool_receipt(
        receipt,
        max_age_s=30.0,
        signing_key=_SIGNING_KEY,
        tenant_id=_TENANT,
        now=100.0,
    ) == (False, "unauthenticated")

    copied_receipt = _receipt_payload(
        {"browser-cli": True},
        _SIGNING_KEY,
        "healthy-tenant",
        now=100.0,
    )
    assert validate_fleet_tool_receipt(
        copied_receipt,
        max_age_s=30.0,
        signing_key=_SIGNING_KEY,
        tenant_id="different-tenant",
        now=100.0,
    ) == (False, "unauthenticated")


@pytest.mark.invariant("FR-OPS-03")
def test_heartbeat_budget_cannot_outlive_its_previous_receipt() -> None:
    env = {
        "BOLTRIG_STACK_TOOL_RECEIPT_TTL": "5",
        "BOLTRIG_STACK_TOOL_HEARTBEAT_INTERVAL": "120",
        "BOLTRIG_STACK_TOOL_PROBE_TIMEOUT": "10",
    }

    # An unsafe operator request is raised to the bounded minimum; the interval
    # plus a worst-case probe and Redis publish still fit before expiry.
    assert heartbeat_interval(env) + (2 * probe_timeout(env)) < 15.0
