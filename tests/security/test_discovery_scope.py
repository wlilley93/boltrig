"""Caller-scoped discovery (US-KER-05): /v1/capabilities omits out-of-scope verbs.

Discovery returns only the verbs the caller is scoped to see (tenant ceiling
intersected with the caller's own grants), not the whole tenant ceiling. An
org-admin sees everything; a scoped caller sees only their verbs; dev discovery
(role-derived grants) is not empty.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from nankle.kernel import Kernel
from nankle.kernel.app import create_app
from nankle.models import GrantSet, TenantPermissions
from nankle.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    from nankle.adapters.builtin.memory_tickets import build as build_tickets
    from nankle.adapters.builtin.ms_graph import build as build_graph

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())  # ticket.* verbs
    await k.register_adapter(T, build_graph())  # document.* / email.* / ... verbs
    return k


def _client() -> TestClient:
    return TestClient(create_app(asyncio.run(_kernel())))


def _hdr(**kw):
    base = {"x-nankle-tenant": T, "x-nankle-subject": "u"}
    base.update(kw)
    return base


def _ids(resp):
    return {v["id"] for v in resp.json()["verbs"]}


@pytest.mark.security
@pytest.mark.invariant("US-KER-05")
def test_scoped_caller_sees_only_scoped_verbs():
    c = _client()
    admin = _ids(c.get("/v1/capabilities", headers=_hdr(**{"x-nankle-role": "org-admin"})))
    assert "ticket.create" in admin and any(i.startswith("document.") for i in admin)

    scoped = _ids(
        c.get("/v1/capabilities", headers=_hdr(**{"x-nankle-grants": "ticket.*"}))
    )
    assert "ticket.create" in scoped
    assert not any(i.startswith("document.") or i.startswith("email.") for i in scoped)


@pytest.mark.security
def test_dev_admin_discovery_not_empty():
    # role-derived grants (org-admin -> "*") keep dev discovery non-empty
    c = _client()
    verbs = _ids(c.get("/v1/capabilities", headers=_hdr(**{"x-nankle-role": "org-admin"})))
    assert len(verbs) > 0
