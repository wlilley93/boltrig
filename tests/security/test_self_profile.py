"""A user may name themselves without gaining a directory-admin mutation path."""

import asyncio

from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import User
from boltrig.store import InMemoryStore


def test_self_profile_updates_only_the_bounded_display_name() -> None:
    store = InMemoryStore()
    user = User(
        id="alice",
        tenant_id="acme",
        email="alice@example.io",
        role="member",
        scope={"verbs": ["read"]},
        status="active",
    )
    asyncio.run(store.upsert_user(user))
    client = TestClient(create_app(Kernel(store), platform={}))
    headers = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "member",
    }

    changed = client.patch(
        "/v1/me/profile",
        json={"display_name": "  Alex   Example  ", "role": "superadmin"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["profile"]["display_name"] == "Alex Example"
    stored = asyncio.run(store.get_user("acme", "alice"))
    assert stored.display_name == "Alex Example"
    assert stored.role == "member" and stored.scope == {"verbs": ["read"]}
    events = asyncio.run(store.audit_query("acme"))
    event = next(item for item in events if item.verb == "profile.update")
    assert event.detail == {"fields": ["display_name"]}
    assert "Alex" not in str(event.detail)


def test_self_profile_rejects_control_characters_and_oversized_names() -> None:
    store = InMemoryStore()
    asyncio.run(store.upsert_user(User(id="alice", tenant_id="acme", role="member")))
    client = TestClient(create_app(Kernel(store), platform={}))
    headers = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "member",
    }
    for value in ("", "Alex\u202eAdmin", "x" * 81):
        response = client.patch(
            "/v1/me/profile", json={"display_name": value}, headers=headers
        )
        assert response.status_code == 400
