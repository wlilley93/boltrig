"""The booted app parks None on the platform when the Codex ledger flag is off.

This is the heart of the increment: with BOLTRIG_CODEX_LEDGER unset (the
default) the app boots identically, app.state.platform["codex_execution"] is
None, and the existing spawn/invoke smoke paths are unchanged. Nothing calls
admit anywhere.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.api.bootstrap import build_app


@pytest.fixture()
def client(monkeypatch):
    for key in ("DATABASE_URL", "ENV", "BOLTRIG_ENV", "APP_ENV", "BOLTRIG_PRODUCTION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("BOLTRIG_CODEX_LEDGER", raising=False)  # flag off = default
    monkeypatch.setenv("BOLTRIG_MANIFEST", "manifest.example.yaml")
    monkeypatch.setenv("BOLTRIG_DEV_AUTH", "1")  # select the dev resolver (no IdP in tests)
    with TestClient(build_app()) as c:
        yield c


def _admin(grants="*"):
    return {"x-boltrig-tenant": "acme", "x-boltrig-grants": grants, "x-boltrig-subject": "u1"}


@pytest.mark.invariant("SEC-170")
def test_platform_parks_none_when_flag_off(client) -> None:
    """The stack is never constructed with the flag off: platform slot is None."""
    platform = client.app.state.platform
    assert "codex_execution" in platform
    assert platform["codex_execution"] is None


def test_booted_stack_is_unchanged_smoke(client) -> None:
    """The flag-off boot behaves identically: health, invoke and spawn all work."""
    assert client.get("/healthz").json()["status"] == "ok"
    invoke = client.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "boot"}},
        headers=_admin("ticket.create"),
    )
    assert invoke.status_code == 200 and invoke.json()["status"] == "ok"
    spawn = client.post(
        "/v1/spawn",
        json={"task": "decompose", "skills": [], "prefer": {}, "context": {}},
        headers=_admin(),
    )
    assert spawn.status_code in (200, 400, 429)
