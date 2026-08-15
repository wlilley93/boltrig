"""The fleet image's Chromium runs only where the manifest asks for it.

Until 2026-07-31 ``scripts/fleet-entrypoint.sh`` started Chromium unconditionally
with ``--no-sandbox`` and kept it alive for the life of the worker. Classical
Visas ran one from boot with six browser verbs registered and ZERO invocations
ever recorded, carrying the fleet image's standing HIGH chromium advisories -
including the sandbox-escape class that ``--no-sandbox`` disables the defence for.

Three consumers answer "does this tenant want a browser": the entrypoint that
STARTS it, the heartbeat that PROBES it, and the readiness gate that REQUIRES it.
Each test below removes one and shows what breaks, because the first two attempts
at this fix each left one of the three still demanding the tool - which is not a
smaller exposure, it is a permanent 503.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from boltrig.fleet.browser_runtime import browser_automation_wanted, main

REPO = Path(__file__).resolve().parents[2]

_BASE = """
organisation: Acme
tenant_id: acme
stack:
  cockpit: boltrig_ui
identity:
  provider: oidc
models:
  endpoints:
    - id: standard
      kind: openai
      model: gpt-5-mini
      data_class: standard
  default: standard
"""


def _manifest(tmp_path: Path, extra: str = "", name: str = "manifest.yaml") -> str:
    path = tmp_path / name
    path.write_text(_BASE + extra, encoding="utf-8")
    return str(path)


# --- the predicate -------------------------------------------------------


def test_plain_manifest_does_not_want_a_browser(tmp_path: Path) -> None:
    assert browser_automation_wanted(_manifest(tmp_path)) is False


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(
            "  browser_automation: browser_cli\n", id="stack-limb"
        ),
        pytest.param("browser_cli:\n  enabled: true\n", id="section-limb"),
        pytest.param("adapters:\n  - id: browser-cli\n    runtime: script\n", id="adapter-limb"),
    ],
)
def test_each_declaring_limb_wants_a_browser(tmp_path: Path, extra: str) -> None:
    """All three limbs must answer True.

    A gate that only read one of them would leave a tenant declaring browser
    automation by another route with no browser and a readiness gate still
    demanding it.
    """
    if extra.startswith("  "):  # a stack-section limb belongs under `stack:`
        text = _BASE.replace(
            "  cockpit: boltrig_ui\n",
            "  cockpit: boltrig_ui\n" + extra,
        )
        path = tmp_path / "m.yaml"
        path.write_text(text, encoding="utf-8")
        assert browser_automation_wanted(str(path)) is True
        return
    assert browser_automation_wanted(_manifest(tmp_path, extra)) is True


def test_absent_manifest_fails_closed(tmp_path: Path) -> None:
    """No manifest means no browser, never "assume yes".

    The whole point of the gate is that the expensive default is the dangerous
    one: a false negative is a loud failure at first use, a false positive is an
    unsandboxed browser running for months on a tenant that never asked.
    """
    assert browser_automation_wanted(str(tmp_path / "nope.yaml")) is False


def test_unreadable_manifest_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("organisation: [unclosed\n", encoding="utf-8")
    assert browser_automation_wanted(str(path)) is False


def test_exit_code_is_the_answer(tmp_path: Path) -> None:
    """The shell reads the exit code, so it is the contract, not a nicety."""
    assert main([_manifest(tmp_path)]) == 1
    assert main([_manifest(tmp_path, "browser_cli:\n  enabled: true\n", "want.yaml")]) == 0


# --- the entrypoint that starts it ---------------------------------------


def _stub_path(tmp_path: Path, *, wanted: bool) -> Path:
    """A PATH where python/chromium/browser-use are recorded, not executed."""
    binder = tmp_path / "bin"
    binder.mkdir()
    marker = tmp_path / "chromium-started"
    (binder / "python").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *boltrig.fleet.browser_runtime*) exit {0 if wanted else 1} ;;\n"
        "  *) exit 0 ;;\n"  # the CDP readiness poll
        "esac\n",
        encoding="utf-8",
    )
    # The stub stays alive only long enough to be observably "running"; a long
    # sleep here holds file descriptors and pads the wall clock for nothing.
    (binder / "chromium").write_text(
        f"#!/bin/sh\ntouch {marker}\nsleep 2\n", encoding="utf-8"
    )
    (binder / "browser-use").write_text(
        "#!/bin/sh\n"
        'test "${BU_CDP_URL:-}" = "http://127.0.0.1:9222" || exit 42\n'
        "cat > /dev/null\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for name in ("python", "chromium", "browser-use"):
        (binder / name).chmod(0o755)
    return binder


def _run_entrypoint(tmp_path: Path, *, wanted: bool) -> tuple[int, bool]:
    binder = _stub_path(tmp_path, wanted=wanted)
    env = dict(os.environ)
    env["PATH"] = f"{binder}:{env['PATH']}"
    env["BOLTRIG_BROWSER_CLI_HOME"] = str(tmp_path / "state")
    proc = subprocess.run(
        ["sh", str(REPO / "scripts" / "fleet-entrypoint.sh"), "true"],
        env=env,
        capture_output=True,
        # Generous on purpose: this test runs inside a fully parallel suite on a
        # box that may also be building; 60s blew once under load (2026-07-31)
        # and a timeout here reads as the GATE failing, which it was not.
        timeout=180,
    )
    # WAIT FOR THE MARKER; DO NOT SAMPLE IT ONCE.
    #
    # The entrypoint backgrounds chromium with `&` (fleet-entrypoint.sh:60) and
    # then polls readiness through the `python` stub -- which exits 0
    # immediately, so the poll waits for nothing. The chromium stub is
    # `touch <marker>; sleep 2`. So the entrypoint can return 0 before that
    # backgrounded shell has reached its `touch`, and a single .exists() call
    # races it. The symptom is exactly rc == 0 with started False.
    #
    # Measured 2026-08-14: fails 2 of 2 full `make quality-gate` runs inside
    # boltrig-vm, and passes 2 of 2 in the same VM in isolation, on the macOS
    # host, and in CI. That combination IS the diagnosis -- it needs the full
    # suite's parallel load AND the slower environment, so the fast machines
    # never see it and the VM always does.
    #
    # A short bounded wait is the fix rather than a longer subprocess timeout:
    # the 180s above already passed, so the process was never slow. Only the
    # observation was early. The negative test is unaffected -- it asserts the
    # marker is ABSENT, and waiting cannot make an absent file appear.
    deadline = time.monotonic() + 10.0
    marker = tmp_path / "chromium-started"
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return proc.returncode, marker.exists()


def test_entrypoint_does_not_start_chromium_when_unwanted(tmp_path: Path) -> None:
    """THE fix. Delete the guard in fleet-entrypoint.sh and this goes red.

    Asserted on the process actually being launched, not on the text of the
    script: a comment saying Chromium is conditional is not a condition.
    """
    rc, started = _run_entrypoint(tmp_path, wanted=False)
    assert rc == 0, "the worker must still start without a browser"
    assert started is False, "Chromium was launched for a tenant that declared none"


def test_entrypoint_still_starts_chromium_when_wanted(tmp_path: Path) -> None:
    """The negative control also proves the CLI is pinned to owned loopback CDP.

    Browser Harness otherwise follows its interactive desktop-Chrome recovery
    path and waits for a user to approve ``chrome://inspect``.  The browser-use
    stub exits 42 unless the entrypoint exports the exact endpoint started by
    this worker.
    """
    rc, started = _run_entrypoint(tmp_path, wanted=True)
    assert rc == 0
    assert started is True, "a declaring tenant lost its browser"


# --- the heartbeat that probes it ----------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_omits_the_key_rather_than_reporting_it_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent, not False.

    False is a claim the tool is broken: it would log "live probe failed" once
    per interval, forever, about a browser nobody asked to run.
    """
    from boltrig.fleet import stack_tool_health

    monkeypatch.setenv("BOLTRIG_MANIFEST", _manifest(tmp_path))
    statuses = await stack_tool_health.probe_fleet_tools({}, 0.1)
    assert statuses == {}


# --- the readiness gate that requires it ----------------------------------


class _NoBrowserStatus:
    """What a worker that started no Chromium reports."""

    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict:
        del tenant_id, workspace_id
        return {
            "components": [],
            "runtimes": [],
        }


async def _stack_tools_check(manifest: str) -> dict:
    """Drive the REAL readiness path, not the helper it calls.

    An earlier version of this test asserted on ``_required_stack_tool_ids()``
    directly. Reverting the call site to the fixed set left it green, so it
    proved the helper existed and nothing about whether readiness used it. The
    only assertion worth making is on the check readiness actually emits.
    """
    from boltrig.api.readiness import ReadinessService
    from boltrig.config.manifest import load_manifest
    from boltrig.kernel import Kernel
    from boltrig.store import InMemoryStore

    os.environ["BOLTRIG_MANIFEST"] = manifest
    service = ReadinessService(
        Kernel(InMemoryStore()),
        tenant_id="acme",
        env={},
        manifest=load_manifest(manifest),
        status_provider=_NoBrowserStatus(),
    )
    stack, _gateway = await service._platform_checks({}, 0.5)
    return stack


@pytest.mark.asyncio
async def test_readiness_stops_requiring_a_browser_it_does_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this, deactivating the browser turns /readyz into a 503.

    That is the failure mode worth its own test: the health check reporting an
    outage it created itself, on a deployment working exactly as configured.
    """
    monkeypatch.setenv("BOLTRIG_MANIFEST", _manifest(tmp_path))
    stack = await _stack_tools_check(_manifest(tmp_path))
    assert stack["status"] == "ok", stack
    assert stack["expected"] == 0


@pytest.mark.asyncio
async def test_readiness_still_fails_when_a_declared_browser_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control: the gate must still be ABLE to fail.

    A derived required set that collapsed to empty unconditionally would pass
    the test above while gating nothing at all.
    """
    manifest = _manifest(tmp_path, "browser_cli:\n  enabled: true\n", "want.yaml")
    monkeypatch.setenv("BOLTRIG_MANIFEST", manifest)
    stack = await _stack_tools_check(manifest)
    assert stack["status"] == "failed", stack
    assert stack["expected"] == 1


def test_receipt_round_trips_with_no_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third consumer, and the one the first two fixes missed.

    The receipt VALIDATOR carried its own fixed required set, so a fleet worker
    correctly publishing no browser-cli result produced a receipt the kernel
    rejected as ``malformed`` - readiness down, for the change working.
    """
    from boltrig.fleet.stack_tool_receipts import (
        _receipt_payload,
        fleet_tool_ids,
        validate_fleet_tool_receipt,
    )

    key = b"k" * 32
    monkeypatch.setenv("BOLTRIG_MANIFEST", _manifest(tmp_path))
    assert fleet_tool_ids() == frozenset()
    raw = _receipt_payload({}, key, "acme")
    assert validate_fleet_tool_receipt(
        raw, max_age_s=30.0, signing_key=key, tenant_id="acme"
    ) == (True, "ok")


def test_receipt_does_not_publish_a_failure_for_a_browser_nobody_wanted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The publisher half, which the round-trip test alone cannot reach.

    With an empty required set the validator accepts a receipt either way, so
    reverting the publisher stayed green while it still wrote
    ``browser-cli: "failed"`` - a claim the tool is BROKEN about one deliberately
    not started. Anything else reading the receipt (the status snapshot, an
    operator) would see an outage that does not exist.
    """
    import json

    from boltrig.fleet.stack_tool_receipts import _receipt_payload

    monkeypatch.setenv("BOLTRIG_MANIFEST", _manifest(tmp_path))
    body = json.loads(_receipt_payload({}, b"k" * 32, "acme"))
    assert body["components"] == {}, body["components"]


def test_receipt_still_rejects_a_missing_browser_where_one_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control for the above: the check must still be able to fail."""
    from boltrig.fleet.stack_tool_receipts import (
        _receipt_payload,
        validate_fleet_tool_receipt,
    )

    key = b"k" * 32
    monkeypatch.setenv(
        "BOLTRIG_MANIFEST",
        _manifest(tmp_path, "browser_cli:\n  enabled: true\n", "want.yaml"),
    )
    raw = _receipt_payload({"browser-cli": False}, key, "acme")
    assert validate_fleet_tool_receipt(
        raw, max_age_s=30.0, signing_key=key, tenant_id="acme"
    ) == (False, "degraded")
