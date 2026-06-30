"""GET /v1/capabilities/changelog: a tenant-isolated timeline of authoring
changes, read from the audit log (authoring.* actions)."""

import asyncio

from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import ActionType, AuditEvent, GrantSet, TenantPermissions, utcnow
from boltrig.store import InMemoryStore

T = "acme"
OTHER = "globex"


def _seed_event(store, tenant, verb, ref):
    asyncio.run(
        store.audit_append(
            AuditEvent(
                tenant_id=tenant, ts=utcnow(), actor="alice", actor_tier="human",
                action_type=ActionType.TOOL_CALL, verb=verb, status="ok",
                detail={"id": ref},
            )
        )
    )


def _client():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    store.set_tenant_permissions(TenantPermissions(OTHER, GrantSet.of(["*"])))
    _seed_event(store, T, "authoring.verb.upsert", "ticket.create")
    _seed_event(store, T, "authoring.binding.set", "ticket.create")
    _seed_event(store, T, "ticket.create", "noise")  # a non-authoring action, excluded
    _seed_event(store, OTHER, "authoring.verb.upsert", "secret.verb")
    return TestClient(create_app(Kernel(store), platform={}))


def _h(tenant=T):
    return {"x-boltrig-tenant": tenant, "x-boltrig-subject": "alice",
            "x-boltrig-role": "org-admin", "x-boltrig-grants": "*"}


def test_changelog_lists_authoring_changes_tenant_isolated():
    c = _client()
    body = c.get("/v1/capabilities/changelog", headers=_h()).json()
    actions = [r["action"] for r in body["changes"]]
    assert "verb.upsert" in actions and "binding.set" in actions
    assert "ticket.create" not in actions  # non-authoring action filtered out
    refs = [r["ref"] for r in body["changes"]]
    assert "secret.verb" not in refs  # the other tenant's change is not visible
    # newest first
    assert body["changes"][0]["action"] == "binding.set"


def test_changelog_other_tenant_sees_only_its_own():
    c = _client()
    body = c.get("/v1/capabilities/changelog", headers=_h(OTHER)).json()
    assert [r["ref"] for r in body["changes"]] == ["secret.verb"]
