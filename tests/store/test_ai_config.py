"""Per-org / workspace / user AI-key store contract ([2026] VJS-COUNTY 8, D5).

Proves the ai_configs table on BOTH stores (parity): the in-memory store always,
Postgres when BOLTRIG_TEST_DATABASE_URL is set (skips cleanly offline). The row
carries a provider/model selection and a SEALED credential_ref - never a raw key -
and every read is tenant-scoped.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from boltrig.models import AiConfig
from boltrig.models.errors import SchemaValidationError

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "ai_configs,credential_refs"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    return await _make_store(request.param)


@pytest.mark.invariant("FR-AIKEY-01")
async def test_ai_config_row_holds_a_credential_ref_never_a_raw_key(store):
    # D5: an ai_config row carries provider/model + a credential_ref (the id of a
    # SEALED credential), and the model itself has NO field that could hold a raw key.
    key_fields = {f.name for f in dataclasses.fields(AiConfig)}
    assert "credential_ref" in key_fields
    # There is no plaintext key column on the row.
    assert not (key_fields & {"api_key", "key", "secret", "material"})

    await store.set_ai_config(AiConfig(
        tenant_id=T, level="org", scope_id=T,
        provider="anthropic", model="claude", credential_ref="cred-1",
    ))
    got = await store.get_ai_config(T, "org", T)
    assert got is not None
    assert got.provider == "anthropic" and got.model == "claude"
    assert got.credential_ref == "cred-1"
    assert got.base_url is None  # optional routing host defaults to NULL (backward-compat)
    # A repeat set at the same key REPLACES (upsert), never duplicates - and the
    # optional base_url routing host round-trips on both stores when named (D5).
    await store.set_ai_config(AiConfig(
        tenant_id=T, level="org", scope_id=T,
        provider="openai", model="gpt", credential_ref="cred-2",
        base_url="http://byo/v1",
    ))
    replaced = await store.get_ai_config(T, "org", T)
    assert replaced.credential_ref == "cred-2" and replaced.base_url == "http://byo/v1"
    assert len(await store.list_ai_configs(T)) == 1

    await store.set_ai_config(AiConfig(
        tenant_id=T, level="org", scope_id=T,
        provider="openai", model="gpt-vision", credential_ref="cred-vision",
        modality="vision",
    ))
    vision = await store.get_ai_config(T, "org", T, "vision")
    assert vision is not None and vision.modality == "vision"
    assert len(await store.list_ai_configs(T)) == 2


@pytest.mark.invariant("FR-AIKEY-01")
async def test_ai_config_level_must_be_valid(store):
    # An out-of-set level can never be persisted (mirrors the workspace-role guard).
    with pytest.raises(SchemaValidationError):
        await store.set_ai_config(AiConfig(
            tenant_id=T, level="tenant", scope_id=T,
            provider="anthropic", model="claude", credential_ref="cred-x",
        ))
    # Each allowed level round-trips.
    for level, scope in (("org", T), ("workspace", "ws1"), ("user", "u1")):
        await store.set_ai_config(AiConfig(
            tenant_id=T, level=level, scope_id=scope,
            provider="anthropic", model="claude", credential_ref=f"cred-{level}",
        ))
        assert (await store.get_ai_config(T, level, scope)).credential_ref == f"cred-{level}"


@pytest.mark.security
@pytest.mark.invariant("SEC-114")
async def test_ai_config_reads_are_tenant_scoped(store):
    # A caller can never read another org's AI key: the reads are keyed on tenant_id,
    # so the same (level, scope_id) under a different tenant resolves to None and the
    # list is empty (fail-closed, never crosses the boundary).
    await store.set_ai_config(AiConfig(
        tenant_id=T, level="org", scope_id=T,
        provider="anthropic", model="claude", credential_ref="cred-1",
    ))
    assert await store.get_ai_config("other-tenant", "org", T) is None
    assert await store.get_ai_config("other-tenant", "org", "other-tenant") is None
    assert await store.list_ai_configs("other-tenant") == []
    # A delete under the wrong tenant is a no-op that cannot reach this tenant's row.
    await store.delete_ai_config("other-tenant", "org", T)
    assert await store.get_ai_config(T, "org", T) is not None
