"""Tenant locale/timezone defaults are effective until caller override."""

from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.store import InMemoryStore


def test_account_preferences_merge_tenant_defaults_without_persisting_them() -> None:
    client = TestClient(
        create_app(
            Kernel(InMemoryStore()),
            platform={
                "user_defaults": {
                    "locale": "en-GB",
                    "timezone": "Europe/London",
                }
            },
        )
    )
    headers = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "member",
    }

    initial = client.get("/v1/me/settings", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["settings"] == {
        "locale": "en-GB",
        "timezone": "Europe/London",
    }
    assert initial.json()["setting_sources"] == {
        "locale": "tenant_default",
        "timezone": "tenant_default",
    }

    changed = client.put(
        "/v1/me/settings",
        json={"settings": {"timezone": "America/New_York"}},
        headers=headers,
    )
    assert changed.status_code == 200
    effective = client.get("/v1/me/settings", headers=headers).json()
    assert effective["settings"] == {
        "locale": "en-GB",
        "timezone": "America/New_York",
    }
    assert effective["setting_sources"] == {
        "locale": "tenant_default",
        "timezone": "user_override",
    }
