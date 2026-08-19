"""A companion follows the workspace, and a user with one keeps it (0083).

The ask: one account running two businesses gets a different main character in
each. The scope lives in the SETTING KEY rather than in a new column, because
``user_settings`` is PK ``(tenant_id, user_id, key)`` and is read from a dozen
places; the ladder is written once in ``models/workspace_settings.py``.

The fallback leg is the one that protects an existing user: someone who chose
Jarvis before workspaces existed must still see Jarvis in a workspace they have
never set a companion in, or the feature reads as data loss.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.chat_persona import CHARACTER_SETTING, chosen_persona
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import UserSetting
from boltrig.models.workspace_settings import (
    resolve_user_settings,
    storage_key,
    workspace_setting_key,
)
from boltrig.store import InMemoryStore

WS_A = "ws-northwind"
WS_B = "ws-acme"


def _headers(workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "x-boltrig-tenant": "acme",
        "x-boltrig-subject": "alice",
        "x-boltrig-role": "member",
    }
    if workspace_id:
        headers["x-boltrig-workspace"] = workspace_id
    return headers


# --- the ladder itself, with no HTTP in the way ------------------------------


def test_the_ladder_is_workspace_then_user_then_default() -> None:
    stored = {
        CHARACTER_SETTING: "jarvis",
        workspace_setting_key(WS_A, CHARACTER_SETTING): "familiar",
        "locale": "en-GB",
    }
    defaults = {CHARACTER_SETTING: "none", "timezone": "UTC"}

    in_a, sources_a = resolve_user_settings(defaults, stored, WS_A)
    assert in_a[CHARACTER_SETTING] == "familiar"
    assert sources_a[CHARACTER_SETTING] == "workspace_override"

    in_b, sources_b = resolve_user_settings(defaults, stored, WS_B)
    assert in_b[CHARACTER_SETTING] == "jarvis"
    assert sources_b[CHARACTER_SETTING] == "user_override"

    at_org, sources_org = resolve_user_settings(defaults, stored, None)
    assert at_org[CHARACTER_SETTING] == "jarvis"
    assert sources_org["timezone"] == "tenant_default"

    # A namespaced key is STORAGE, never API: it must not appear under its raw
    # name in any scope, or one workspace's choice leaks into another's view.
    for bag in (in_a, in_b, at_org):
        assert not any(key.startswith("ws:") for key in bag)


def test_only_the_listed_keys_are_scoped() -> None:
    assert storage_key(CHARACTER_SETTING, WS_A) == workspace_setting_key(
        WS_A, CHARACTER_SETTING
    )
    # Approval posture and locale are facts about a person, not about which
    # business they are looking at. Forking a consent decision per workspace is
    # the failure this allowlist prevents.
    assert storage_key("locale", WS_A) == "locale"
    assert storage_key("approval.posture", WS_A) == "approval.posture"
    # At org scope even a scoped key writes bare, which is what a user with one
    # business has always had.
    assert storage_key(CHARACTER_SETTING, None) == CHARACTER_SETTING


# --- through the route -------------------------------------------------------


def test_two_workspaces_hold_two_companions_for_one_user() -> None:
    client = TestClient(create_app(Kernel(InMemoryStore())))

    assert client.put(
        "/v1/me/settings",
        json={"settings": {CHARACTER_SETTING: "familiar"}},
        headers=_headers(WS_A),
    ).status_code == 200
    assert client.put(
        "/v1/me/settings",
        json={"settings": {CHARACTER_SETTING: "jarvis"}},
        headers=_headers(WS_B),
    ).status_code == 200

    in_a = client.get("/v1/me/settings", headers=_headers(WS_A)).json()
    in_b = client.get("/v1/me/settings", headers=_headers(WS_B)).json()
    assert in_a["settings"][CHARACTER_SETTING] == "familiar"
    assert in_b["settings"][CHARACTER_SETTING] == "jarvis"
    assert in_a["active_workspace_id"] == WS_A
    assert in_a["setting_sources"][CHARACTER_SETTING] == "workspace_override"

    # Writing in one workspace left the other alone, and left org scope with no
    # companion at all rather than silently adopting either.
    at_org = client.get("/v1/me/settings", headers=_headers()).json()
    assert CHARACTER_SETTING not in at_org["settings"]


def test_an_existing_companion_survives_into_a_workspace_never_configured() -> None:
    client = TestClient(create_app(Kernel(InMemoryStore())))
    # The pre-workspace world: chosen at org scope, stored on the bare key.
    assert client.put(
        "/v1/me/settings",
        json={"settings": {CHARACTER_SETTING: "jarvis"}},
        headers=_headers(),
    ).status_code == 200

    in_a = client.get("/v1/me/settings", headers=_headers(WS_A)).json()
    assert in_a["settings"][CHARACTER_SETTING] == "jarvis"
    assert in_a["setting_sources"][CHARACTER_SETTING] == "user_override"

    # And choosing a different one there does not rewrite the original.
    client.put(
        "/v1/me/settings",
        json={"settings": {CHARACTER_SETTING: "familiar"}},
        headers=_headers(WS_A),
    )
    assert (
        client.get("/v1/me/settings", headers=_headers()).json()["settings"][
            CHARACTER_SETTING
        ]
        == "jarvis"
    )


# --- the voice a turn actually speaks in -------------------------------------


@pytest.mark.security
async def test_the_chat_persona_reads_the_same_ladder_as_the_settings_screen() -> None:
    store = InMemoryStore()
    for key, value in (
        (CHARACTER_SETTING, "jarvis"),
        (workspace_setting_key(WS_A, CHARACTER_SETTING), "familiar"),
    ):
        await store.upsert_user_setting(
            UserSetting(tenant_id="acme", user_id="alice", key=key, value=value)
        )

    in_a = await chosen_persona(store, "acme", "alice", WS_A)
    in_b = await chosen_persona(store, "acme", "alice", WS_B)
    at_org = await chosen_persona(store, "acme", "alice", None)

    # Both resolve to a real persona, and to DIFFERENT ones. Asserting only that
    # they differ would pass if one of them were empty, which is the failure
    # mode a missing character produces.
    assert in_a and in_b and at_org
    assert in_a != in_b
    assert in_b == at_org
