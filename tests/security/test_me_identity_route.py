"""``GET /v1/me``: the contract a host application reads instead of its own session.

Opbox stops owning identity and asks Boltrig, per request, who this person is
and where they may act. Two properties make that safe to rely on: the answer is
the resolver's ALREADY re-authorised view (a revoked membership disappears
without waiting for anything to expire), and it reports which credential the
caller holds, because a PAT may select a workspace but may not switch the org.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from boltrig.kernel.org_discovery_routes import register_org_discovery_routes
from boltrig.models import User, Workspace, WorkspaceMember
from boltrig.store import InMemoryStore

T = "acme"


class _P:
    def __init__(self, workspace: str | None, kind: str = "pat") -> None:
        self.tenant_id, self.subject, self.role = T, "u1", "engineer"
        self.actor_tier, self.credential_kind = "human", kind
        self.active_workspace_id = workspace


async def _client(workspace: str | None, *, kind: str = "pat", member_of=("ws-alpha",)):
    store = InMemoryStore()
    await store.upsert_user(
        User(id="u1", tenant_id=T, role="engineer", status="active", email="a@b.c",
             display_name="Ada")
    )
    for ws in ("ws-alpha", "ws-beta"):
        await store.create_workspace(Workspace(id=ws, tenant_id=T, name=ws, slug=ws))
    for ws in member_of:
        await store.add_workspace_member(
            WorkspaceMember(user_id="u1", workspace_id=ws, tenant_id=T, role="owner")
        )

    class _K:
        pass

    k = _K()
    k.store = store
    app = FastAPI()
    register_org_discovery_routes(
        app, principal_dep=lambda: _P(workspace, kind), get_kernel=lambda: k
    )
    return TestClient(app), store


@pytest.mark.security
async def test_it_answers_who_and_where():
    client, _ = await _client("ws-alpha")

    body = client.get("/v1/me").json()

    assert body["subject"] == "u1"
    assert body["email"] == "a@b.c"
    assert body["tenant_id"] == T
    assert body["active_workspace_id"] == "ws-alpha"


@pytest.mark.security
async def test_it_lists_only_the_callers_own_memberships():
    """ws-beta exists and the caller is not in it, so it must not appear."""
    client, _ = await _client("ws-alpha", member_of=("ws-alpha",))

    body = client.get("/v1/me").json()

    assert [w["id"] for w in body["workspaces"]] == ["ws-alpha"]
    assert body["workspaces"][0]["active"] is True


@pytest.mark.security
async def test_it_reports_the_credential_because_it_changes_what_is_possible():
    """A PAT may select a workspace by header; only a session may switch org.

    A host rendering a switcher has to know which it holds, rather than
    discovering it from a 400 on the org route.
    """
    pat, _ = await _client("ws-alpha", kind="pat")
    session, _ = await _client("ws-alpha", kind="session")

    assert pat.get("/v1/me").json()["credential_kind"] == "pat"
    assert session.get("/v1/me").json()["credential_kind"] == "session"


@pytest.mark.security
async def test_an_unscoped_caller_says_so_rather_than_guessing():
    client, _ = await _client(None, member_of=("ws-alpha", "ws-beta"))

    body = client.get("/v1/me").json()

    assert body["active_workspace_id"] is None
    assert {w["id"] for w in body["workspaces"]} == {"ws-alpha", "ws-beta"}
    assert not any(w["active"] for w in body["workspaces"])


@pytest.mark.security
async def test_a_revoked_membership_disappears_from_the_answer():
    client, store = await _client("ws-alpha", member_of=("ws-alpha", "ws-beta"))
    assert len(client.get("/v1/me").json()["workspaces"]) == 2

    await store.remove_workspace_member(T, "ws-beta", "u1")

    assert [w["id"] for w in client.get("/v1/me").json()["workspaces"]] == ["ws-alpha"]
