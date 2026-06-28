"""The full stack boots from the example manifest and serves the contract (DoD #1)."""

import os

import pytest
from fastapi.testclient import TestClient

from nankle.api.bootstrap import build_app


@pytest.fixture(scope="module")
def client():
    os.environ["NANKLE_MANIFEST"] = "manifest.example.yaml"
    return TestClient(build_app())


def _admin(grants="*"):
    return {"x-nankle-tenant": "acme", "x-nankle-grants": grants, "x-nankle-subject": "u1"}


def test_healthz_green(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_capabilities_registered_from_manifest(client):
    r = client.get("/v1/capabilities", headers=_admin())
    assert r.status_code == 200
    verbs = {v["id"] for v in r.json()["verbs"]}
    # builtin adapters named in the manifest registered their verbs as data (P1)
    assert "ticket.create" in verbs
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
