"""Per-org / workspace / user AI keys ([2026] VJS-COUNTY 8, D5).

FR-AIKEY-02 : resolve_ai_key precedence user -> workspace -> org -> env/manifest
              default, and the spawner wires the resolved (sealed) key into the
              model-key seam; a tenant with no config falls back to the env key
              (backward-compat, the critical rule).
SEC-112     : allow_own_ai_keys=False makes a workspace/user key IGNORED - only the
              org (or env) key is used, so a member cannot bring their own key
              unless the org opts in.
SEC-113     : an AI key is stored ONLY as a sealed credential ref - the governed
              set-key route accepts it once, never echoes it, and no audit row
              carries the raw key; the ai_configs row holds only the reference.
SEC-115     : the governed set-key route is role-scoped - org level is admin-only,
              workspace level needs a workspace owner/admin (+ allow_own), user level
              is own-only (+ allow_own).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.spawn import Spawner
from boltrig.identity import load_ai_key_material, resolve_ai_key
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    AiConfig,
    CredentialResolution,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    Organisation,
    TenantPermissions,
    WorkspaceMember,
)
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed

T = "acme"


def _run(coro):
    return asyncio.run(coro)


async def _store(*, allow_own: bool | None = True) -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    if allow_own is not None:
        await store.create_org(
            Organisation(id=T, name="Acme", slug="acme", allow_own_ai_keys=allow_own)
        )
    return store


async def _seal(store, cred_id: str, key: str) -> None:
    await store.set_credential_ref(T, cred_id, {"secret": key})


async def _put_config(store, level, scope_id, cred_id, key) -> None:
    await _seal(store, cred_id, key)
    await store.set_ai_config(AiConfig(
        tenant_id=T, level=level, scope_id=scope_id,
        provider="openai", model="gpt", credential_ref=cred_id,
    ))


# --- FR-AIKEY-02: precedence user -> workspace -> org -> default ---------------
@pytest.mark.invariant("FR-AIKEY-02")
def test_resolve_precedence_user_workspace_org_default():
    async def go():
        store = await _store(allow_own=True)
        await _put_config(store, "org", T, "cred-org", "sk-org")
        await _put_config(store, "workspace", "ws1", "cred-ws", "sk-ws")
        await _put_config(store, "user", "u1", "cred-user", "sk-user")

        # user wins over workspace and org.
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "user" and r.credential_ref == "cred-user"
        assert await load_ai_key_material(store, T, r) == "sk-user"

        # no user config -> workspace.
        await store.delete_ai_config(T, "user", "u1")
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "workspace" and await load_ai_key_material(store, T, r) == "sk-ws"

        # no workspace config -> org.
        await store.delete_ai_config(T, "workspace", "ws1")
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "org" and await load_ai_key_material(store, T, r) == "sk-org"

        # no config at all -> default (env/manifest fallback), no credential ref.
        await store.delete_ai_config(T, "org", T)
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "default" and r.credential_ref is None and r.is_default
        assert await load_ai_key_material(store, T, r) is None

    _run(go())


@pytest.mark.invariant("FR-AIKEY-02")
def test_no_config_tenant_falls_back_to_env_key(monkeypatch):
    # The backward-compat rule: a tenant with NO org row and NO ai_config resolves to
    # the default level, and the spawner-built runtime uses the ENV provider key
    # exactly as before (an existing single-tenant deploy is unchanged).
    async def go():
        store = await _store(allow_own=None)  # no org row at all
        k = Kernel(store)
        await store.upsert_model_endpoint(
            ModelEndpoint(id="ep", tenant_id=T, kind="openai", model="gpt",
                          base_url="http://local/v1")
        )
        cap = AgentCapability("w", T, "openai", ["*"], 2, True, "standard",
                              model_endpoint="ep")
        ctx = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")
        rt = await Spawner(k)._runtime_for(T, cap, ctx)
        # No config -> the runtime carries no override and reads the env key.
        assert rt._api_key() == "sk-env-default"

    monkeypatch.delenv("BOLTRIG_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-default")
    # openai is a legacy lane (decision 0012): reachable only behind the flag.
    monkeypatch.setenv("BOLTRIG_ENABLE_LEGACY_RUNTIMES", "1")
    _run(go())


@pytest.mark.invariant("FR-AIKEY-02")
def test_spawner_wires_resolved_sealed_key_into_the_runtime(monkeypatch):
    # The model-key seam: with a user-level AI key configured (allow_own on), the
    # spawner resolves + loads the SEALED key and the runtime uses IT, not the env key.
    async def go():
        store = await _store(allow_own=True)
        k = Kernel(store)
        await _put_config(store, "user", "u1", "cred-user", "sk-user-sealed")
        await store.upsert_model_endpoint(
            ModelEndpoint(id="ep", tenant_id=T, kind="openai", model="gpt",
                          base_url="http://local/v1")
        )
        cap = AgentCapability("w", T, "openai", ["*"], 2, True, "standard",
                              model_endpoint="ep")
        ctx = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")
        rt = await Spawner(k)._runtime_for(T, cap, ctx)
        assert rt._api_key() == "sk-user-sealed"  # the sealed key, NOT the env key

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-default")
    # openai is a legacy lane (decision 0012): reachable only behind the flag.
    monkeypatch.setenv("BOLTRIG_ENABLE_LEGACY_RUNTIMES", "1")
    _run(go())


@pytest.mark.security
@pytest.mark.invariant("SEC-148")
def test_production_runtime_refuses_ambient_ai_key_fallback(monkeypatch):
    async def go():
        store = await _store(allow_own=None)
        kernel = Kernel(store)
        await store.upsert_model_endpoint(
            ModelEndpoint(
                id="ep",
                tenant_id=T,
                kind="openai",
                model="gpt",
                base_url="https://models.example/v1",
            )
        )
        capability = AgentCapability(
            "w", T, "openai", ["*"], 2, True, "standard", model_endpoint="ep"
        )
        context = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")

        with pytest.raises(CredentialResolution, match="scoped credential"):
            await Spawner(kernel)._runtime_for(T, capability, context)

    monkeypatch.setenv("BOLTRIG_ENV", "production")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-be-used")
    _run(go())


@pytest.mark.security
@pytest.mark.invariant("SEC-148")
def test_configured_missing_ai_key_never_falls_through_to_ambient(monkeypatch):
    async def go():
        store = await _store(allow_own=True)
        await store.set_ai_config(
            AiConfig(
                tenant_id=T,
                level="user",
                scope_id="u1",
                provider="openai",
                model="gpt",
                credential_ref="missing-ref",
            )
        )
        kernel = Kernel(store)
        capability = AgentCapability("w", T, "openai", ["*"], 2, True, "standard")
        context = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")

        with pytest.raises(CredentialResolution, match="material is unavailable"):
            await Spawner(kernel)._runtime_for(T, capability, context)

    monkeypatch.delenv("BOLTRIG_ENV", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-be-used")
    _run(go())


# --- SEC-112: allow_own_ai_keys=False ignores workspace/user keys --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-112")
def test_allow_own_false_ignores_workspace_and_user_keys():
    async def go():
        store = await _store(allow_own=False)
        # Even with workspace + user keys present, allow_own=False ignores them.
        await _put_config(store, "workspace", "ws1", "cred-ws", "sk-ws")
        await _put_config(store, "user", "u1", "cred-user", "sk-user")

        # With an ORG key set, resolution uses the ORG key (never the ignored ws/user).
        await _put_config(store, "org", T, "cred-org", "sk-org")
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "org" and await load_ai_key_material(store, T, r) == "sk-org"

        # With NO org key, resolution falls through to the env default - a member
        # cannot bring their own key when the org forbids it.
        await store.delete_ai_config(T, "org", T)
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "default" and r.is_default

        # Flip the org to ALLOW own keys: now the user key is honoured (precedence).
        org = await store.get_org(T)
        org.allow_own_ai_keys = True
        await store.update_org(org)
        r = await resolve_ai_key(store, T, workspace_id="ws1", user_id="u1")
        assert r.level == "user" and await load_ai_key_material(store, T, r) == "sk-user"

    _run(go())


# --- SEC-113: sealed storage - key never in the config row or the audit log -----
def _app():
    store = _run(_store(allow_own=True))
    k = Kernel(store)
    app = create_app(k, platform={})
    return k, app, store


def _hdr(role="org-admin", subject="admin"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject,
            "x-boltrig-role": role, "x-boltrig-grants": "*"}


def _approved_ai_key(c, k, body, headers):
    staged = c.put("/v1/ai-keys", headers=headers, json=body)
    assert staged.status_code == 202, staged.text
    assert "hitl_request_id" not in staged.json()
    proposal_id = staged.json()["proposal"]["id"]
    proposal = _run(k.store.get_ai_key_secret_proposal(T, proposal_id))
    assert proposal is not None and proposal.approval_id
    _run(k.hitl.answer(T, proposal.approval_id, "approve", "test-reviewer"))
    return c.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize",
        headers=headers,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-113")
def test_ai_key_is_sealed_never_returned_or_audited():
    k, app, store = _app()
    c = TestClient(app)
    secret = "sk-topsecretkeyvalue0987654321"
    key_body = {"level": "org", "provider": "openai", "model": "gpt",
                "api_key": secret}
    staged = c.put("/v1/ai-keys", headers=_hdr(), json=key_body)
    assert staged.status_code == 202
    proposal_id = staged.json()["proposal"]["id"]
    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert proposal is not None and proposal.approval_id

    # Plaintext is absent from every staging and approval representation. The
    # proposal row carries only an opaque sealed-reference id and a digest.
    held = _run(store.get_hitl_request(T, proposal.approval_id))
    raw_proposal = store._ai_key_proposals[(T, proposal_id)]
    raw_stage = store._creds[(T, f"staged_ai_key:{proposal_id}")]
    assert secret not in staged.text
    assert secret not in repr(raw_proposal)
    assert secret not in repr(held)
    assert secret not in json.dumps(raw_stage)
    assert is_sealed(raw_stage)

    _run(k.hitl.answer(T, proposal.approval_id, "approve", "test-reviewer"))
    resp = c.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_hdr()
    )
    assert resp.status_code == 200
    # The response NEVER echoes the key.
    assert secret not in resp.text
    body = resp.json()
    assert body["status"] == "ok" and body["provider"] == "openai"

    # The ai_configs row holds only a credential_ref, never the raw key.
    cfg = _run(store.get_ai_config(T, "org", T))
    assert cfg is not None and cfg.credential_ref
    assert secret not in repr(cfg)

    # The key IS retrievable from the sealed credential store (kernel-side only).
    ref = _run(store.get_credential_ref(T, cfg.credential_ref))
    assert ref.get("secret") == secret
    # At rest the row is a sealed envelope (SEC-169), never the plaintext key.
    raw = store._creds[(T, cfg.credential_ref)]
    assert is_sealed(raw) and secret not in json.dumps(raw)

    # No audit row carries the raw key.
    events = _run(store.audit_query(T, limit=1000))
    blob = repr([e.detail for e in events])
    assert secret not in blob
    # The set IS audited keys-only (level/scope/provider/model + the ref id).
    setrows = [e for e in events if e.verb == "ai_key.set"]
    assert setrows and setrows[-1].detail.get("level") == "org"

    # The list view reports has_key but never the secret.
    lst = c.get("/v1/ai-keys", headers=_hdr()).json()
    assert lst["allow_own_ai_keys"] is True
    assert lst["ai_keys"][0]["has_key"] is True
    assert secret not in repr(lst)
    consumed = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert consumed.status == "consumed" and consumed.secret_ref is None


# --- SEC-115: the set-key route is role-scoped --------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-115")
def test_set_key_route_is_role_scoped():
    k, app, store = _app()
    c = TestClient(app)
    _run(store.add_workspace_member(
        WorkspaceMember(user_id="wsadmin", workspace_id="ws1", tenant_id=T, role="owner")
    ))

    def put(level, scope_id, hdr):
        body = {"level": level, "provider": "openai", "model": "gpt", "api_key": "sk-x"}
        if scope_id is not None:
            body["scope_id"] = scope_id
        response = c.put("/v1/ai-keys", headers=hdr, json=body)
        if response.status_code != 202:
            return response
        proposal_id = response.json()["proposal"]["id"]
        proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
        _run(k.hitl.answer(T, proposal.approval_id, "approve", "test-reviewer"))
        return c.post(
            f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=hdr
        )

    # org level: a plain member is denied; an org-admin succeeds.
    assert put("org", None, _hdr(role="member", subject="bob")).status_code == 403
    assert put("org", None, _hdr()).status_code == 200

    # workspace level: a non-admin of the workspace is denied; its owner succeeds.
    assert put("workspace", "ws1", _hdr(role="member", subject="bob")).status_code == 403
    assert put("workspace", "ws1", _hdr(role="member", subject="wsadmin")).status_code == 200

    # user level: a caller may set their OWN user key but not another user's.
    assert put("user", "bob", _hdr(role="member", subject="bob")).status_code == 200
    assert put("user", "carol", _hdr(role="member", subject="bob")).status_code == 403

    # allow_own gate: with the org forbidding own keys, workspace/user sets are
    # refused even for the workspace owner (the key would be ignored anyway).
    org = _run(store.get_org(T))
    org.allow_own_ai_keys = False
    _run(store.update_org(org))
    assert put("workspace", "ws1", _hdr(role="member", subject="wsadmin")).status_code == 403
    assert put("user", "bob", _hdr(role="member", subject="bob")).status_code == 403
    # ...but the org itself may still set its own key.
    assert put("org", None, _hdr()).status_code == 200
