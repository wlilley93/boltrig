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


# --- POST /v1/me/permits ------------------------------------------------------
#
# The question a host asks INSTEAD of reimplementing GrantSet.permits. Opbox has
# to decide "may this caller do X" on every tool call; the only safe way for it
# to know is to ask the kernel that will actually enforce it, because a second
# implementation of deny-dominance and terminal wildcards is a divergence whose
# failure mode is a host granting what this kernel would refuse.


async def _permits_client(*, allow, deny=(), ceiling=("*",), ceiling_deny=()):
    from boltrig.models import GrantSet, TenantPermissions

    client, store = await _client("ws-alpha")
    store.set_tenant_permissions(
        TenantPermissions(T, GrantSet.of(allow=list(ceiling), deny=list(ceiling_deny)))
    )
    app = FastAPI()

    class _PG(_P):
        def __init__(self) -> None:
            super().__init__("ws-alpha", "pat")
            self.grants = GrantSet.of(allow=list(allow), deny=list(deny))

    class _K:
        pass

    k = _K()
    k.store = store
    register_org_discovery_routes(
        app, principal_dep=lambda: _PG(), get_kernel=lambda: k
    )
    return TestClient(app)


@pytest.mark.security
async def test_it_answers_the_verbs_it_was_asked_about():
    client = await _permits_client(allow=["matter.open", "matter.read"])

    body = client.post(
        "/v1/me/permits",
        json={"verbs": ["matter.open", "matter.close", "matter.read"]},
    ).json()

    assert body["verbs"] == {
        "matter.open": True,
        "matter.close": False,
        "matter.read": True,
    }
    assert body["active_workspace_id"] == "ws-alpha"


@pytest.mark.security
async def test_a_deny_beats_an_allow_and_a_wildcard():
    """Deny-dominance is the rule a host reimplementing this would most likely
    get wrong, because the allow reads as the answer."""
    client = await _permits_client(allow=["matter.*"], deny=["matter.delete"])

    body = client.post(
        "/v1/me/permits", json={"verbs": ["matter.open", "matter.delete"]}
    ).json()

    assert body["verbs"] == {"matter.open": True, "matter.delete": False}


@pytest.mark.security
async def test_the_tenant_ceiling_is_folded_in_not_just_the_caller_grants():
    """BOTH authorities, as the dispatcher composes them.

    The caller holds `matter.*` outright. The tenant does not permit
    `matter.delete` at all, so the honest answer is no, and answering on the
    caller's grants alone would report an upper bound as a selection.
    """
    client = await _permits_client(
        allow=["matter.*"], ceiling=["matter.open", "matter.read"]
    )

    body = client.post(
        "/v1/me/permits", json={"verbs": ["matter.open", "matter.delete"]}
    ).json()

    assert body["verbs"] == {"matter.open": True, "matter.delete": False}

    # The counterweight: widen the ceiling and the same caller, unchanged, now
    # gets a yes. Without this the refusal above is equally consistent with an
    # endpoint that says no to everything.
    wide = await _permits_client(allow=["matter.*"], ceiling=["*"])
    assert wide.post(
        "/v1/me/permits", json={"verbs": ["matter.delete"]}
    ).json()["verbs"] == {"matter.delete": True}


@pytest.mark.security
async def test_a_pattern_is_refused_rather_than_answered():
    """`permits` takes a verb id. "Do I hold matter.*" is a different question,
    and answering it as though it were an id would answer confidently and
    wrongly."""
    client = await _permits_client(allow=["matter.*"])

    refused = client.post("/v1/me/permits", json={"verbs": ["matter.*"]})

    assert refused.status_code == 400
    assert refused.json()["reason"] == "verb patterns are not questions"


@pytest.mark.security
async def test_an_empty_or_oversized_ask_is_refused():
    from boltrig.kernel.org_discovery_routes import MAX_PERMIT_QUESTIONS

    client = await _permits_client(allow=["*"])

    assert client.post("/v1/me/permits", json={"verbs": []}).status_code == 400
    assert client.post("/v1/me/permits", json={}).status_code == 400
    too_many = [f"noun.verb{i}" for i in range(MAX_PERMIT_QUESTIONS + 1)]
    over = client.post("/v1/me/permits", json={"verbs": too_many})
    assert over.status_code == 400
    assert over.json()["reason"] == "too_many_verbs"
    # At the bound exactly, it answers.
    at_bound = client.post("/v1/me/permits", json={"verbs": too_many[:-1]})
    assert at_bound.status_code == 200
    assert len(at_bound.json()["verbs"]) == MAX_PERMIT_QUESTIONS
