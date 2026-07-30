"""Memory/PostgreSQL parity for envelope-sealed AI-key proposals."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import timedelta

import pytest

from boltrig.models import AiConfig, AiKeySecretProposal, utcnow

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "ai-key-proposal-parity"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore, set_current_tenant

    set_current_tenant(T)
    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE ai_key_secret_proposals,ai_configs,credential_refs CASCADE"
    )
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for PostgreSQL parity"
            ),
        ),
    ]
)
async def proposal_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _proposal(secret: str) -> AiKeySecretProposal:
    now = utcnow()
    proposal_id = f"akp_{uuid.uuid4().hex}"
    return AiKeySecretProposal(
        id=proposal_id,
        tenant_id=T,
        requested_by="admin",
        requested_on_behalf_of=None,
        workspace_id=None,
        level="org",
        scope_id=T,
        provider="openai",
        model="gpt-5",
        base_url=None,
        secret_ref=f"staged_ai_key:{proposal_id}",
        secret_digest=hashlib.sha256(secret.encode()).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        updated_at=now,
    )


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
async def test_staged_secret_lifecycle_matches_on_both_stores(proposal_store) -> None:
    store = proposal_store
    secret = "sk-store-parity-secret"
    proposal = _proposal(secret)
    await store.set_credential_ref(T, "old", {"secret": "old-key"})
    await store.set_ai_config(
        AiConfig(T, "org", T, "old", "old", "old")
    )

    await store.create_ai_key_secret_proposal(proposal, secret)
    raw = await store.get_ai_key_secret_proposal(T, proposal.id)
    assert secret not in repr(raw)
    assert await store.has_credential_ref(T, proposal.secret_ref)
    assert await store.list_ai_key_secret_proposals(T, "other", None) == []

    applied = await store.consume_ai_key_secret_proposal(
        T,
        proposal.id,
        requested_by="admin",
        requested_on_behalf_of=None,
        workspace_id=None,
        level="org",
        scope_id=T,
        provider="openai",
        model="gpt-5",
        base_url=None,
        secret_digest=proposal.secret_digest,
        now=utcnow(),
    )
    assert applied is not None
    assert (await store.get_credential_ref(T, applied.credential_ref))["secret"] == secret
    assert not await store.has_credential_ref(T, "old")
    consumed = await store.get_ai_key_secret_proposal(T, proposal.id)
    assert consumed.status == "consumed" and consumed.secret_ref is None
    assert await store.consume_ai_key_secret_proposal(
        T,
        proposal.id,
        requested_by="admin",
        requested_on_behalf_of=None,
        workspace_id=None,
        level="org",
        scope_id=T,
        provider="openai",
        model="gpt-5",
        base_url=None,
        secret_digest=proposal.secret_digest,
        now=utcnow(),
    ) is None


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
async def test_invalidation_deletes_only_the_exact_staged_reference(
    proposal_store,
) -> None:
    store = proposal_store
    proposal = _proposal("sk-invalidate")
    await store.create_ai_key_secret_proposal(proposal, "sk-invalidate")
    assert await store.invalidate_ai_key_secret_proposal(
        T, proposal.id, "other", "invalidated", utcnow()
    ) is None
    assert await store.has_credential_ref(T, proposal.secret_ref)
    ended = await store.invalidate_ai_key_secret_proposal(
        T, proposal.id, "admin", "invalidated", utcnow()
    )
    assert ended.status == "invalidated" and ended.secret_ref is None
    assert not await store.has_credential_ref(T, proposal.secret_ref)
