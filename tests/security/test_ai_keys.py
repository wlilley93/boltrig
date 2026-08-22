"""Per-org / workspace / user AI keys ([2026] VJS-COUNTY 8, D5).

FR-AIKEY-02 : resolve_ai_key precedence user -> workspace -> org -> unconfigured
              default. The Codex resolver loads only sealed, scoped material;
              ambient provider keys never revive a provider-native runtime.
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

from boltrig.fleet.runtime_resolver import RuntimeResolver
from boltrig.identity import load_ai_key_material, resolve_ai_key
from boltrig.identity.bifrost_user_binding import (
    BifrostUserBinding,
    BifrostUserGateway,
    binding_credential_ref,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AiConfig,
    CredentialResolution,
    GrantSet,
    InvocationContext,
    Organisation,
    TenantPermissions,
    User,
    WorkspaceMember,
)
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed

T = "acme"


@pytest.fixture(autouse=True)
def _bounded_bifrost(monkeypatch):
    """Existing route tests exercise governance, not a live Bifrost process."""

    monkeypatch.setenv("BOLTRIG_MODEL_GATEWAY_URL", "http://bifrost:8080/v1")

    async def ensure(self, store, tenant_id, resolution, provider_key):
        assert provider_key
        ref = binding_credential_ref(tenant_id, resolution)
        provider = str(resolution.provider)
        model = str(resolution.model)
        model_id = model if "/" in model else f"{provider}/{model}"
        binding = BifrostUserBinding(
            provider=provider,
            model_id=model_id,
            provider_key_id="provider-key",
            virtual_key_id="virtual-key",
            virtual_key="vk-test-only",
            credential_ref=ref,
        )
        await store.set_credential_ref(
            tenant_id,
            ref,
            {
                "secret": binding.virtual_key,
                "provider": binding.provider,
                "model_id": binding.model_id,
                "source_credential_ref": resolution.credential_ref,
                "provider_key_id": binding.provider_key_id,
                "virtual_key_id": binding.virtual_key_id,
            },
        )
        return binding

    async def usable(self, binding):
        return True

    monkeypatch.setattr(BifrostUserGateway, "ensure", ensure)
    monkeypatch.setattr(BifrostUserGateway, "is_usable", usable)


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


async def _put_config(store, level, scope_id, cred_id, key, *, modality="text") -> None:
    await _seal(store, cred_id, key)
    await store.set_ai_config(AiConfig(
        tenant_id=T, level=level, scope_id=scope_id,
        provider="openai", model="gpt", credential_ref=cred_id,
        modality=modality,
    ))


# --- FR-AIKEY-02: precedence user -> workspace -> org -> default -------------
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


@pytest.mark.invariant("FR-AIKEY-VISION-01")
def test_vision_key_is_optional_and_falls_back_to_the_main_text_key():
    async def go():
        store = await _store(allow_own=False)
        await _put_config(store, "org", T, "cred-text", "sk-main")

        fallback = await resolve_ai_key(store, T, modality="vision")
        assert fallback.level == "org"
        assert await load_ai_key_material(store, T, fallback) == "sk-main"

        await _put_config(
            store, "org", T, "cred-vision", "sk-vision", modality="vision"
        )
        dedicated = await resolve_ai_key(store, T, modality="vision")
        assert dedicated.level == "org"
        assert dedicated.credential_ref == "cred-vision"
        assert await load_ai_key_material(store, T, dedicated) == "sk-vision"

    _run(go())


@pytest.mark.invariant("FR-AIKEY-02")
def test_no_config_tenant_does_not_use_an_ambient_provider_key(monkeypatch):
    async def go():
        store = await _store(allow_own=None)  # no org row at all
        ctx = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")
        material, resolution = await RuntimeResolver(Kernel(store))._resolve_ai_key(
            T, ctx
        )
        assert material is None
        assert resolution is not None and resolution.is_default

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-default")
    _run(go())


@pytest.mark.invariant("FR-AIKEY-02")
def test_runtime_resolver_loads_the_scoped_sealed_key(monkeypatch):
    async def go():
        store = await _store(allow_own=True)
        await _put_config(store, "user", "u1", "cred-user", "sk-user-sealed")
        ctx = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")
        material, resolution = await RuntimeResolver(Kernel(store))._resolve_ai_key(
            T, ctx
        )
        assert material == "sk-user-sealed"
        assert resolution is not None and resolution.credential_ref == "cred-user"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-default")
    _run(go())


@pytest.mark.security
@pytest.mark.invariant("SEC-148")
def test_production_runtime_refuses_ambient_ai_key_fallback(monkeypatch):
    async def go():
        store = await _store(allow_own=None)
        context = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")

        with pytest.raises(CredentialResolution, match="scoped credential"):
            await RuntimeResolver(Kernel(store))._resolve_ai_key(T, context)

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
        context = InvocationContext(tenant_id=T, actor="w", on_behalf_of="u1")

        with pytest.raises(CredentialResolution, match="material is unavailable"):
            await RuntimeResolver(Kernel(store))._resolve_ai_key(T, context)

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


@pytest.mark.security
@pytest.mark.invariant("SEC-113")
@pytest.mark.invariant("FR-AIKEY-03")
def test_onboarding_connects_your_own_provider_in_one_press():
    """A member's OWN key completes inside the submit call itself.

    The requester is the person any approval would ask, so the kernel answers
    the approval in the same request (owner decision 2026-08-20: onboarding is
    click-through). Every SEC-113 property is unchanged underneath: the secret
    is sealed before any approval exists, the proposal is consumed exactly
    once, the set is audited, and no approval id ever crosses HTTP.
    """
    k, app, store = _app()
    _run(store.upsert_user(User(
        id="admin",
        tenant_id=T,
        email="admin@example.test",
        role="superadmin",
        status="active",
    )))
    client = TestClient(app)

    staged = client.put(
        "/v1/ai-keys",
        headers=_hdr(role="superadmin"),
        json={
            "level": "user",
            "scope_id": "admin",
            "provider": "openai",
            "model": "openai/gpt-5.4",
            "api_key": "provider-secret",
        },
    )
    assert staged.status_code == 200, staged.text
    assert staged.json()["status"] == "ok"
    assert "hitl_request_id" not in staged.text
    config = _run(store.get_ai_config(T, "user", "admin", "text"))
    assert config is not None and config.model == "openai/gpt-5.4"
    listed = client.get("/v1/ai-keys", headers=_hdr(role="superadmin")).json()
    assert listed["ai_keys"][0]["gateway_ready"] is True
    proposals = _run(store.list_ai_key_secret_proposals(T, "admin", None))
    assert proposals and proposals[0].status == "consumed"


@pytest.mark.security
@pytest.mark.invariant("SEC-113")
@pytest.mark.invariant("FR-AIKEY-03")
def test_org_level_key_still_pends_and_the_approve_route_finalizes_it():
    """Keys set for a SHARED scope keep the full approval stop.

    Folding the requester's own answer into the submit press must not widen:
    an org-level key changes everyone's model, so it still parks as
    pending_human with a plain reason, and the explicit approve route is what
    finalizes it. Approval ids stay server-side on both legs.
    """
    k, app, store = _app()
    _run(store.upsert_user(User(
        id="admin",
        tenant_id=T,
        email="admin@example.test",
        role="superadmin",
        status="active",
    )))
    client = TestClient(app)

    staged = client.put(
        "/v1/ai-keys",
        headers=_hdr(role="superadmin"),
        json={
            "level": "org",
            "provider": "openai",
            "model": "openai/gpt-5.4",
            "api_key": "provider-secret",
        },
    )
    assert staged.status_code == 202, staged.text
    body = staged.json()
    assert body["status"] == "pending_human"
    assert body["reason"]
    assert "hitl_request_id" not in staged.text
    proposal_id = body["proposal"]["id"]

    applied = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/approve",
        headers=_hdr(role="superadmin"),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "ok"
    assert "hitl_request_id" not in applied.text
    config = _run(store.get_ai_config(T, "org", T, "text"))
    assert config is not None and config.model == "openai/gpt-5.4"


@pytest.mark.security
@pytest.mark.invariant("SEC-113")
@pytest.mark.invariant("FR-AIKEY-03")
def test_existing_approved_key_can_be_reconciled_without_resubmitting_secret():
    k, app, store = _app()
    _run(_put_config(
        store,
        "user",
        "admin",
        "approved-provider-secret",
        "provider-secret",
    ))
    client = TestClient(app)

    response = client.post(
        "/v1/ai-keys/activate",
        headers=_hdr(role="superadmin"),
        json={"level": "user", "scope_id": "admin", "modality": "text"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    listed = client.get("/v1/ai-keys", headers=_hdr(role="superadmin")).json()
    assert listed["ai_keys"][0]["gateway_ready"] is True


# --- FR-AIKEY-04: keyless self-hosted providers -------------------------------
@pytest.mark.security
@pytest.mark.invariant("FR-AIKEY-04")
def test_keyless_self_hosted_provider_connects_without_an_api_key():
    """A self-hosted server that authenticates nothing (provider "ollama")
    must onboard without a key: the intake substitutes a fixed placeholder
    that is sealed, digested and never echoed exactly like a real key, so the
    sealed-proposal and Bifrost provisioning paths are unchanged. Every other
    provider still demands one."""
    k, app, store = _app()
    c = TestClient(app)

    # A keyed provider without a key is still refused.
    refused = c.put(
        "/v1/ai-keys",
        headers=_hdr(),
        json={"level": "org", "provider": "openai", "model": "gpt"},
    )
    assert refused.status_code == 400
    assert "API key" in refused.json()["reason"]

    # The keyless provider stages, approves and finalises with no api_key.
    staged = c.put(
        "/v1/ai-keys",
        headers=_hdr(),
        json={
            "level": "org",
            "provider": "ollama",
            "model": "ollama/qwen3vl-abliterated",
            "base_url": "http://mac-mini-m1:11434/v1",
            "api_key": "",
        },
    )
    assert staged.status_code == 202, staged.text
    proposal_id = staged.json()["proposal"]["id"]

    # The placeholder is sealed material, indistinguishable in storage shape.
    raw_stage = store._creds[(T, f"staged_ai_key:{proposal_id}")]
    assert is_sealed(raw_stage)
    assert "keyless" not in staged.text

    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    _run(k.hitl.answer(T, proposal.approval_id, "approve", "test-reviewer"))
    applied = c.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_hdr()
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["status"] == "ok" and body["provider"] == "ollama"
    # The bare name is stored under the provider's own default tag: that IS the
    # id the server lists, so gateway verification can match it byte-exactly.
    assert body["model"] == "ollama/qwen3vl-abliterated:latest"
    assert body["base_url"] == "http://mac-mini-m1:11434/v1"
    assert "keyless" not in applied.text

    cfg = _run(store.get_ai_config(T, "org", T))
    assert cfg is not None and cfg.credential_ref
    assert "keyless" not in repr(cfg)
