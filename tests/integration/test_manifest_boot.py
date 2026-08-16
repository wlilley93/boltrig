"""The full stack boots from the example manifest and serves the contract (DoD #1)."""

import pytest
from fastapi.testclient import TestClient

from boltrig.api.bootstrap import build_app


@pytest.fixture()
def client(monkeypatch):
    for key in ("DATABASE_URL", "ENV", "BOLTRIG_ENV", "APP_ENV", "BOLTRIG_PRODUCTION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOLTRIG_MANIFEST", "manifest.example.yaml")
    monkeypatch.setenv("BOLTRIG_DEV_AUTH", "1")  # select the dev resolver (no IdP in tests)
    # enter the context so the lifespan builds the kernel on the serving loop
    with TestClient(build_app()) as c:
        yield c


def _admin(grants="*"):
    return {"x-boltrig-tenant": "default", "x-boltrig-grants": grants, "x-boltrig-subject": "u1"}


def test_healthz_green(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_capabilities_registered_from_manifest(client):
    r = client.get("/v1/capabilities", headers=_admin())
    assert r.status_code == 200
    verbs = {v["id"] for v in r.json()["verbs"]}
    # builtin adapters named in the manifest registered their verbs as data (P1)
    assert "ticket.create" in verbs
    assert "memory.remember" in verbs
    assert "memory.recall" in verbs
    assert "browser.page.info" in verbs
    assert "browser.tab.open" in verbs
    assert len(verbs) >= 5


def test_invoke_through_booted_stack(client):
    r = client.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "boot"}},
        headers=_admin("ticket.create"),
    )
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_spawn_endpoint_is_wired(client):
    # spawn must be reachable (not 503 spawner_unavailable). It may 200 or return a
    # clean validation error, but never an unhandled 500.
    r = client.post(
        "/v1/spawn",
        json={"task": "decompose", "skills": [], "prefer": {}, "context": {}},
        headers=_admin(),
    )
    assert r.status_code in (200, 400, 429)


def test_example_manifest_memory_boots_without_live_projections(client):
    r = client.post(
        "/v1/memory/remember",
        json={"content": "boot memory note"},
        headers=_admin("memory.remember"),
    )

    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["projections"] == []
