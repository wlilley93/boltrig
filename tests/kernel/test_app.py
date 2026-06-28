"""The HTTP surface honours the dispatch contract status codes (S7.1, S7.2)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from nankle.kernel.app import create_app
from tests.conftest import _build_kernel


def _client(blocking=None):
    kernel, _ = asyncio.run(_build_kernel(blocking_verbs=blocking or set()))
    return TestClient(create_app(kernel))


def _headers(grants: str, tenant="acme"):
    return {"x-nankle-tenant": tenant, "x-nankle-grants": grants, "x-nankle-subject": "u1"}


@pytest.mark.kernel
def test_invoke_ok_200():
    c = _client()
    r = c.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "x"}},
        headers=_headers("ticket.create"),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.kernel
def test_invoke_denied_403():
    c = _client()
    # a non-admin caller with no grants and no scope (role-derived grants are empty)
    r = c.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "x"}},
        headers={"x-nankle-tenant": "acme", "x-nankle-subject": "u1", "x-nankle-role": "agent"},
    )
    assert r.status_code == 403
    assert r.json()["status"] == "denied"


@pytest.mark.kernel
def test_invoke_pending_human_202():
    c = _client(blocking={"ticket.create"})
    r = c.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "x"}},
        headers=_headers("ticket.create"),
    )
    assert r.status_code == 202
    assert "hitl_request_id" in r.json()


@pytest.mark.kernel
def test_discovery_is_role_scoped():
    c = _client()
    r = c.get("/v1/capabilities", headers=_headers("ticket.create"))
    assert r.status_code == 200
    verb_ids = {v["id"] for v in r.json()["verbs"]}
    assert "ticket.create" in verb_ids
