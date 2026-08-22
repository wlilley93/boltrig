"""Memory/PostgreSQL parity for durable external-MCP lifecycle evidence."""

from __future__ import annotations

from datetime import timedelta
import json
import os

import pytest

from boltrig.models import (
    AdapterHealth,
    AdapterRecord,
    MCP_PROBE_RECEIPTS_PER_SERVER,
    McpProbeReceipt,
    McpToolSnapshot,
    utcnow,
)
from boltrig.store.mcp_lifecycle import (
    McpCredentialAmendment,
    mcp_credential_config_digest,
    mcp_registration_spec_digest,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "mcp-lifecycle-a"
OTHER = "mcp-lifecycle-b"
MODULE = "boltrig.adapters.mcp_consumer"


def _adapter(
    tenant_id: str,
    server_id: str,
    *,
    module_ref: str = MODULE,
    spec_ref: str = '{"url":"https://mcp.example.test"}',
):
    return AdapterRecord(
        id=server_id,
        tenant_id=tenant_id,
        version="1",
        runtime="http",
        source="manual",
        module_ref=module_ref,
        spec_ref=spec_ref,
    )


def _tool(name: str) -> McpToolSnapshot:
    return McpToolSnapshot(
        name=name,
        description=f"{name} description",
        consequence="low",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        output_schema={"type": "object"},
    )


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE mcp_probe_receipts,mcp_servers,adapters CASCADE"
    )
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def store(request):
    value = await _make_store(request.param)
    yield value
    close = getattr(value, "close", None)
    if close is not None:
        await close()


def _spec(
    url: str,
    *,
    allow_internal: bool = False,
    credential_id: str | None = None,
) -> str:
    return json.dumps(
        {
            "url": url,
            "allow_internal": allow_internal,
            "credential_id": credential_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


async def _create_lifecycle(
    store,
    tenant_id: str,
    server_id: str,
    at,
    *,
    spec_ref: str | None = None,
):
    await store.upsert_adapter(
        _adapter(
            tenant_id,
            server_id,
            spec_ref=(
                '{"url":"https://mcp.example.test"}'
                if spec_ref is None
                else spec_ref
            ),
        )
    )
    row = await store.set_mcp_server_lifecycle(
        tenant_id,
        server_id,
        expected_state=None,
        expected_config_revision=None,
        new_state="inactive",
        changed_at=at,
    )
    assert row is not None
    return row


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-08")
async def test_lifecycle_cas_restore_and_adapter_activation_are_one_write(store):
    now = utcnow()
    await _create_lifecycle(store, T, "ext-mcp", now)
    await _create_lifecycle(store, OTHER, "ext-mcp", now)

    active = await store.set_mcp_server_lifecycle(
        T,
        "ext-mcp",
        expected_state="inactive",
        expected_config_revision=1,
        new_state="active",
        changed_at=now + timedelta(seconds=1),
        last_known_tools=(_tool("ticket.read"),),
        tools_observed_at=now,
    )
    assert active is not None and active.state == "active"
    assert active.tools_observed_at == now
    assert (await store.get_adapter(T, "ext-mcp")).activated is True

    lost = await store.set_mcp_server_lifecycle(
        T,
        "ext-mcp",
        expected_state="inactive",
        expected_config_revision=1,
        new_state="retired",
        changed_at=now + timedelta(seconds=2),
    )
    assert lost is None
    assert (await store.get_adapter(T, "ext-mcp")).activated is True

    with pytest.raises(ValueError, match="active->retired"):
        await store.set_mcp_server_lifecycle(
            T,
            "ext-mcp",
            expected_state="active",
            expected_config_revision=1,
            new_state="retired",
            changed_at=now + timedelta(seconds=3),
        )
    inactive = await store.set_mcp_server_lifecycle(
        T,
        "ext-mcp",
        expected_state="active",
        expected_config_revision=1,
        new_state="inactive",
        changed_at=now + timedelta(seconds=3),
    )
    assert inactive is not None
    retired = await store.set_mcp_server_lifecycle(
        T,
        "ext-mcp",
        expected_state="inactive",
        expected_config_revision=1,
        new_state="retired",
        changed_at=now + timedelta(seconds=4),
    )
    assert retired is not None and retired.retired_at is not None
    assert [tool.name for tool in retired.last_known_tools] == ["ticket.read"]
    assert (await store.get_adapter(T, "ext-mcp")).activated is False
    with pytest.raises(ValueError, match="retired->active"):
        await store.set_mcp_server_lifecycle(
            T,
            "ext-mcp",
            expected_state="retired",
            expected_config_revision=1,
            new_state="active",
            changed_at=now + timedelta(seconds=5),
        )

    restored = await store.set_mcp_server_lifecycle(
        T,
        "ext-mcp",
        expected_state="retired",
        expected_config_revision=1,
        new_state="inactive",
        changed_at=now + timedelta(seconds=6),
    )
    assert restored is not None and restored.retired_at is None
    assert restored.tools_observed_at == now
    assert [tool.name for tool in restored.last_known_tools] == ["ticket.read"]
    assert await store.get_mcp_server_lifecycle(OTHER, "ext-mcp") != restored
    assert [row.server_id for row in await store.list_mcp_server_lifecycles(T)] == [
        "ext-mcp"
    ]


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-08")
async def test_probe_receipts_are_content_free_monotonic_and_drive_health(store):
    now = utcnow()
    await _create_lifecycle(store, T, "ext-mcp", now)
    first = McpProbeReceipt(
        tenant_id=T,
        server_id="ext-mcp",
        probe_id="mcp_probe_1",
        outcome="succeeded",
        failure_code=None,
        observed_at=now + timedelta(seconds=2),
        tool_count=1,
    )
    await store.record_mcp_probe_receipt(
        first,
        expected_config_revision=1,
        last_known_tools=(_tool("ticket.read"),),
    )
    assert (await store.get_adapter(T, "ext-mcp")).health is AdapterHealth.OK

    failure = McpProbeReceipt(
        tenant_id=T,
        server_id="ext-mcp",
        probe_id="mcp_probe_2",
        outcome="failed",
        failure_code="transport_unavailable",
        observed_at=now + timedelta(seconds=4),
        tool_count=0,
    )
    await store.record_mcp_probe_receipt(
        failure, expected_config_revision=1
    )
    assert (await store.get_adapter(T, "ext-mcp")).health is AdapterHealth.DOWN

    stale = McpProbeReceipt(
        tenant_id=T,
        server_id="ext-mcp",
        probe_id="mcp_probe_stale",
        outcome="succeeded",
        failure_code=None,
        observed_at=now + timedelta(seconds=1),
        tool_count=1,
    )
    await store.record_mcp_probe_receipt(
        stale,
        expected_config_revision=1,
        last_known_tools=(_tool("stale.tool"),),
    )
    lifecycle = await store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert lifecycle is not None
    assert lifecycle.tools_observed_at == first.observed_at
    assert [tool.name for tool in lifecycle.last_known_tools] == ["ticket.read"]
    assert (await store.get_adapter(T, "ext-mcp")).health is AdapterHealth.DOWN

    rows = await store.list_mcp_probe_receipts(T, "ext-mcp")
    assert [row.probe_id for row in rows] == [
        "mcp_probe_2",
        "mcp_probe_1",
        "mcp_probe_stale",
    ]
    assert await store.get_latest_mcp_probe_receipt(T, "ext-mcp") == failure
    assert "raw" not in repr(rows).lower()
    assert "credential" not in repr(rows).lower()
    assert await store.list_mcp_probe_receipts(OTHER, "ext-mcp") == []

    with pytest.raises(ValueError, match="failed MCP probe"):
        await store.record_mcp_probe_receipt(
            McpProbeReceipt(
                tenant_id=T,
                server_id="ext-mcp",
                probe_id="mcp_probe_bad",
                outcome="failed",
                failure_code="discovery_invalid",
                observed_at=now + timedelta(seconds=5),
                tool_count=1,
            ),
            expected_config_revision=1,
            last_known_tools=(_tool("must.not.persist"),),
        )


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
async def test_probe_ids_are_immutable_and_history_has_a_hard_bound(store):
    now = utcnow()
    await _create_lifecycle(store, T, "ext-mcp", now)
    total = MCP_PROBE_RECEIPTS_PER_SERVER + 3
    for index in range(total):
        await store.record_mcp_probe_receipt(
            McpProbeReceipt(
                tenant_id=T,
                server_id="ext-mcp",
                probe_id=f"mcp_probe_{index:04d}",
                outcome="succeeded",
                failure_code=None,
                observed_at=now + timedelta(seconds=index),
                tool_count=0,
            ),
            expected_config_revision=1,
            last_known_tools=(),
        )
    rows = await store.list_mcp_probe_receipts(T, "ext-mcp", limit=10_000)
    assert len(rows) == MCP_PROBE_RECEIPTS_PER_SERVER
    assert rows[0].probe_id == f"mcp_probe_{total - 1:04d}"
    assert rows[-1].probe_id == "mcp_probe_0003"

    replay = rows[0]
    assert await store.record_mcp_probe_receipt(
        replay, expected_config_revision=1, last_known_tools=()
    ) == replay
    with pytest.raises(ValueError, match="different attempt"):
        await store.record_mcp_probe_receipt(
            McpProbeReceipt(
                tenant_id=T,
                server_id="ext-mcp",
                probe_id=replay.probe_id,
                outcome="failed",
                failure_code="protocol_invalid",
                observed_at=replay.observed_at,
                tool_count=0,
            ),
            expected_config_revision=1,
        )


@pytest.mark.store
@pytest.mark.invariant("SEC-08")
async def test_lifecycle_refuses_missing_and_non_mcp_adapter_rows(store):
    now = utcnow()
    with pytest.raises(LookupError, match="not found"):
        await store.set_mcp_server_lifecycle(
            T,
            "missing",
            expected_state=None,
            expected_config_revision=None,
            new_state="inactive",
            changed_at=now,
        )
    await store.upsert_adapter(_adapter(T, "ordinary", module_ref="example.adapter"))
    with pytest.raises(ValueError, match="not an external MCP"):
        await store.set_mcp_server_lifecycle(
            T,
            "ordinary",
            expected_state=None,
            expected_config_revision=None,
            new_state="inactive",
            changed_at=now,
        )


def test_persisted_tool_snapshot_shape_fails_closed():
    from boltrig.store.mcp_lifecycle_codec import tools

    with pytest.raises(ValueError, match="entries must be objects"):
        tools(["not-an-object"])
    with pytest.raises(ValueError, match="fields are invalid"):
        tools([{"name": "missing-fields"}])
    with pytest.raises(ValueError, match="fields are invalid"):
        tools(
            [
                {
                    "name": "tool",
                    "description": "",
                    "consequence": "low",
                    "input_schema": {},
                    "output_schema": {},
                    "unexpected": "field",
                }
            ]
        )


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
async def test_deliberate_adapter_delete_cascades_lifecycle_evidence(store):
    now = utcnow()
    await _create_lifecycle(store, T, "delete-mcp", now)
    await store.record_mcp_probe_receipt(
        McpProbeReceipt(
            tenant_id=T,
            server_id="delete-mcp",
            probe_id="mcp_probe_delete",
            outcome="succeeded",
            failure_code=None,
            observed_at=now,
            tool_count=0,
        ),
        expected_config_revision=1,
        last_known_tools=(),
    )

    await store.delete_adapter(T, "delete-mcp")

    assert await store.get_mcp_server_lifecycle(T, "delete-mcp") is None
    assert await store.list_mcp_probe_receipts(T, "delete-mcp") == []
    if hasattr(store, "_mcp_lifecycles"):
        assert (T, "delete-mcp") not in store._mcp_lifecycles
        assert not any(key[:2] == (T, "delete-mcp") for key in store._mcp_probe_receipts)
    else:
        assert await store._pool.fetchval(
            "SELECT count(*) FROM mcp_servers WHERE tenant_id=$1 AND id=$2",
            T,
            "delete-mcp",
        ) == 0
        assert await store._pool.fetchval(
            "SELECT count(*) FROM mcp_probe_receipts "
            "WHERE tenant_id=$1 AND server_id=$2",
            T,
            "delete-mcp",
        ) == 0


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-08")
async def test_amendment_invalidates_old_evidence_and_fences_late_probe(store):
    now = utcnow()
    old_credential_id = "mcp-amend-old"
    new_credential_id = "mcp-amend-new"
    old_spec = _spec(
        "https://old-mcp.example.test",
        credential_id=old_credential_id,
    )
    await store.set_credential_ref(
        T,
        old_credential_id,
        {"store": "env", "ref": "OLD_MCP_TOKEN", "kind": "api_key"},
    )
    await _create_lifecycle(
        store, T, "amend-mcp", now, spec_ref=old_spec
    )
    old_probe = McpProbeReceipt(
        tenant_id=T,
        server_id="amend-mcp",
        probe_id="mcp_probe_before_amend",
        outcome="succeeded",
        failure_code=None,
        observed_at=now + timedelta(seconds=1),
        tool_count=1,
    )
    await store.record_mcp_probe_receipt(
        old_probe,
        expected_config_revision=1,
        last_known_tools=(_tool("old.tool"),),
    )
    before = await store.get_mcp_server_lifecycle(T, "amend-mcp")
    assert before is not None and before.updated_at is not None
    changed_at = before.updated_at + timedelta(seconds=1)
    new_metadata = {
        "store": "env",
        "ref": "NEW_MCP_TOKEN",
        "kind": "api_key",
    }
    new_spec = _spec(
        "https://new-mcp.example.test",
        allow_internal=True,
        credential_id=new_credential_id,
    )

    result = await store.amend_mcp_server_registration(
        T,
        "amend-mcp",
        expected_state="inactive",
        expected_created_at=before.created_at,
        expected_updated_at=before.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(old_spec),
        expected_credential_config_digest=mcp_credential_config_digest(
            {
                "store": "env",
                "ref": "OLD_MCP_TOKEN",
                "kind": "api_key",
            }
        ),
        expected_config_revision=1,
        spec_ref=new_spec,
        changed_at=changed_at,
        credential_amendment=McpCredentialAmendment(
            "replace", new_credential_id, new_metadata
        ),
    )

    assert result is not None
    assert result.lifecycle.config_revision == 2
    assert result.lifecycle.last_known_tools == ()
    assert result.lifecycle.tools_observed_at is None
    assert result.adapter.spec_ref == new_spec
    assert result.adapter.health is AdapterHealth.UNKNOWN
    assert result.adapter.activated is False
    assert await store.get_credential_ref(T, old_credential_id) == {
        "store": "env",
        "ref": "OLD_MCP_TOKEN",
        "kind": "api_key",
    }
    assert await store.get_credential_ref(T, new_credential_id) == new_metadata
    assert await store.list_mcp_probe_receipts(T, "amend-mcp") == []

    late_old_probe = McpProbeReceipt(
        tenant_id=T,
        server_id="amend-mcp",
        probe_id="mcp_probe_late_old_revision",
        outcome="succeeded",
        failure_code=None,
        observed_at=changed_at + timedelta(seconds=1),
        tool_count=1,
    )
    assert await store.record_mcp_probe_receipt(
        late_old_probe,
        expected_config_revision=1,
        last_known_tools=(_tool("must.not.return"),),
    ) is None
    current = await store.get_mcp_server_lifecycle(T, "amend-mcp")
    assert current is not None
    assert current.config_revision == 2
    assert current.last_known_tools == ()
    assert current.tools_observed_at is None
    assert (await store.get_adapter(T, "amend-mcp")).health is AdapterHealth.UNKNOWN
    assert await store.list_mcp_probe_receipts(T, "amend-mcp") == []

    assert await store.amend_mcp_server_registration(
        T,
        "amend-mcp",
        expected_state="inactive",
        expected_created_at=before.created_at,
        expected_updated_at=before.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(old_spec),
        expected_credential_config_digest=mcp_credential_config_digest(
            {
                "store": "env",
                "ref": "OLD_MCP_TOKEN",
                "kind": "api_key",
            }
        ),
        expected_config_revision=1,
        spec_ref=new_spec,
        changed_at=changed_at,
        credential_amendment=McpCredentialAmendment(
            "replace", new_credential_id, new_metadata
        ),
    ) is None


@pytest.mark.store
@pytest.mark.invariant("SEC-08")
async def test_shared_credential_cannot_be_overwritten_and_is_not_deleted(store):
    now = utcnow()
    shared_id = "mcp-shared-reference"
    old_id = "mcp-exclusive-reference"
    shared_metadata = {
        "store": "env",
        "ref": "SHARED_MCP_TOKEN",
        "kind": "api_key",
    }
    await store.set_credential_ref(T, shared_id, shared_metadata)
    await store.set_credential_ref(
        T,
        old_id,
        {"store": "env", "ref": "EXCLUSIVE_MCP_TOKEN", "kind": "api_key"},
    )
    await _create_lifecycle(
        store,
        T,
        "shared-owner",
        now,
        spec_ref=_spec(
            "https://shared-owner.example.test",
            credential_id=shared_id,
        ),
    )
    await _create_lifecycle(
        store,
        T,
        "shared-peer",
        now,
        spec_ref=_spec(
            "https://shared-peer.example.test",
            credential_id=shared_id,
        ),
    )
    old_spec = _spec(
        "https://changing-owner.example.test",
        credential_id=old_id,
    )
    before = await _create_lifecycle(
        store, T, "changing-owner", now, spec_ref=old_spec
    )
    replacement_spec = _spec(
        "https://changed.example.test",
        credential_id=shared_id,
    )

    with pytest.raises(ValueError, match="metadata is immutable"):
        await store.amend_mcp_server_registration(
            T,
            "changing-owner",
            expected_state="inactive",
            expected_created_at=before.created_at,
            expected_updated_at=before.updated_at,
            expected_spec_digest=mcp_registration_spec_digest(old_spec),
            expected_credential_config_digest=mcp_credential_config_digest(
                {
                    "store": "env",
                    "ref": "EXCLUSIVE_MCP_TOKEN",
                    "kind": "api_key",
                }
            ),
            expected_config_revision=1,
            spec_ref=replacement_spec,
            changed_at=now + timedelta(seconds=1),
            credential_amendment=McpCredentialAmendment(
                "replace",
                shared_id,
                {
                    "store": "env",
                    "ref": "ATTEMPTED_SHARED_OVERWRITE",
                    "kind": "api_key",
                },
            ),
        )
    assert await store.get_credential_ref(T, shared_id) == shared_metadata
    assert (await store.get_adapter(T, "changing-owner")).spec_ref == old_spec
    assert (
        await store.get_mcp_server_lifecycle(T, "changing-owner")
    ).config_revision == 1

    deleted = await store.delete_mcp_server_registration(
        T,
        "shared-owner",
        expected_state="inactive",
        expected_created_at=now,
        expected_updated_at=now,
        expected_spec_digest=mcp_registration_spec_digest(
            _spec(
                "https://shared-owner.example.test",
                credential_id=shared_id,
            )
        ),
        expected_credential_config_digest=mcp_credential_config_digest(
            shared_metadata
        ),
        expected_config_revision=1,
        changed_at=now + timedelta(seconds=1),
    )
    assert deleted is not None
    assert await store.get_credential_ref(T, shared_id) == shared_metadata


@pytest.mark.store
@pytest.mark.invariant("FR-MCP-03")
async def test_registration_delete_cleans_state_but_retains_credential_ref(store):
    now = utcnow()
    credential_id = "mcp-delete-owned-reference"
    spec_ref = _spec(
        "https://delete-owned.example.test",
        credential_id=credential_id,
    )
    await store.set_credential_ref(
        T,
        credential_id,
        {"store": "env", "ref": "DELETE_MCP_TOKEN", "kind": "api_key"},
    )
    await _create_lifecycle(
        store, T, "delete-owned", now, spec_ref=spec_ref
    )
    await store.record_mcp_probe_receipt(
        McpProbeReceipt(
            tenant_id=T,
            server_id="delete-owned",
            probe_id="mcp_probe_delete_owned",
            outcome="succeeded",
            failure_code=None,
            observed_at=now + timedelta(milliseconds=1),
            tool_count=0,
        ),
        expected_config_revision=1,
        last_known_tools=(),
    )
    lifecycle = await store.get_mcp_server_lifecycle(T, "delete-owned")
    assert lifecycle is not None and lifecycle.updated_at is not None
    changed_at = lifecycle.updated_at + timedelta(seconds=1)

    with pytest.raises(ValueError, match="inactive or retired"):
        await store.delete_mcp_server_registration(
            T,
            "delete-owned",
            expected_state="active",
            expected_created_at=lifecycle.created_at,
            expected_updated_at=lifecycle.updated_at,
            expected_spec_digest=mcp_registration_spec_digest(spec_ref),
            expected_credential_config_digest=mcp_credential_config_digest(
                {
                    "store": "env",
                    "ref": "DELETE_MCP_TOKEN",
                    "kind": "api_key",
                }
            ),
            expected_config_revision=1,
            changed_at=changed_at,
        )
    assert await store.delete_mcp_server_registration(
        T,
        "delete-owned",
        expected_state="inactive",
        expected_created_at=lifecycle.created_at,
        expected_updated_at=lifecycle.updated_at,
        expected_spec_digest="0" * 64,
        expected_credential_config_digest=mcp_credential_config_digest(
            {
                "store": "env",
                "ref": "DELETE_MCP_TOKEN",
                "kind": "api_key",
            }
        ),
        expected_config_revision=1,
        changed_at=changed_at,
    ) is None

    result = await store.delete_mcp_server_registration(
        T,
        "delete-owned",
        expected_state="inactive",
        expected_created_at=lifecycle.created_at,
        expected_updated_at=lifecycle.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=mcp_credential_config_digest(
            {
                "store": "env",
                "ref": "DELETE_MCP_TOKEN",
                "kind": "api_key",
            }
        ),
        expected_config_revision=1,
        changed_at=changed_at,
    )
    assert result is not None
    assert result.previous_config_revision == 1
    assert await store.get_adapter(T, "delete-owned") is None
    assert await store.get_mcp_server_lifecycle(T, "delete-owned") is None
    assert await store.list_mcp_probe_receipts(T, "delete-owned") == []
    assert await store.get_credential_ref(T, credential_id) == {
        "store": "env",
        "ref": "DELETE_MCP_TOKEN",
        "kind": "api_key",
    }


def test_credential_amendment_modes_are_secret_free_and_unambiguous():
    with pytest.raises(ValueError, match="reject credential fields"):
        McpCredentialAmendment("preserve", "unexpected")
    with pytest.raises(ValueError, match="store, ref and kind"):
        McpCredentialAmendment(
            "replace",
            "credential",
            {"store": "env", "ref": "TOKEN"},
        )
    with pytest.raises(ValueError, match="store, ref and kind"):
        McpCredentialAmendment(
            "replace",
            "credential",
            {
                "store": "env",
                "ref": "TOKEN",
                "kind": "api_key",
                "token": "plaintext",
            },
        )


@pytest.mark.store
@pytest.mark.invariant("SEC-08")
async def test_credential_rotation_invalidates_amend_and_delete_approval(store):
    now = utcnow()
    credential_id = "mcp-credential-cas"
    spec_ref = _spec(
        "https://credential-cas.example.test",
        credential_id=credential_id,
    )
    original = {
        "store": "env",
        "ref": "MCP_TOKEN_BEFORE_APPROVAL",
        "kind": "api_key",
    }
    rotated = {
        "store": "env",
        "ref": "MCP_TOKEN_AFTER_APPROVAL",
        "kind": "api_key",
    }
    await store.set_credential_ref(T, credential_id, original)
    approved = await _create_lifecycle(
        store, T, "credential-cas", now, spec_ref=spec_ref
    )
    assert approved.created_at is not None and approved.updated_at is not None
    approved_digest = mcp_credential_config_digest(original)

    # Deterministic approval/mutation race: another governed writer rotates the
    # reference after approval was stamped but before the atomic store call.
    await store.set_credential_ref(T, credential_id, rotated)
    changed_at = approved.updated_at + timedelta(seconds=1)
    assert await store.amend_mcp_server_registration(
        T,
        "credential-cas",
        expected_state="inactive",
        expected_created_at=approved.created_at,
        expected_updated_at=approved.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=approved_digest,
        expected_config_revision=1,
        spec_ref=_spec(
            "https://credential-cas-new.example.test",
            credential_id=credential_id,
        ),
        changed_at=changed_at,
        credential_amendment=McpCredentialAmendment("preserve"),
    ) is None
    assert await store.delete_mcp_server_registration(
        T,
        "credential-cas",
        expected_state="inactive",
        expected_created_at=approved.created_at,
        expected_updated_at=approved.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=approved_digest,
        expected_config_revision=1,
        changed_at=changed_at,
    ) is None
    assert (await store.get_adapter(T, "credential-cas")).spec_ref == spec_ref
    assert (
        await store.get_mcp_server_lifecycle(T, "credential-cas")
    ).config_revision == 1
    assert await store.get_credential_ref(T, credential_id) == rotated


@pytest.mark.store
@pytest.mark.invariant("SEC-08")
async def test_recreated_server_generation_refuses_stale_generation_cas(store):
    now = utcnow()
    spec_ref = _spec("https://generation.example.test")
    original = await _create_lifecycle(
        store, T, "generation-cas", now, spec_ref=spec_ref
    )
    assert original.created_at is not None and original.updated_at is not None
    deleted = await store.delete_mcp_server_registration(
        T,
        "generation-cas",
        expected_state="inactive",
        expected_created_at=original.created_at,
        expected_updated_at=original.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=None,
        expected_config_revision=1,
        changed_at=now + timedelta(seconds=1),
    )
    assert deleted is not None

    recreated = await _create_lifecycle(
        store,
        T,
        "generation-cas",
        now + timedelta(seconds=2),
        spec_ref=spec_ref,
    )
    assert recreated.created_at != original.created_at
    assert recreated.updated_at is not None
    changed_at = recreated.updated_at + timedelta(seconds=1)

    # All mutable CAS fields are current; only the approved registration
    # generation is stale. It must still be impossible to touch the new row.
    assert await store.delete_mcp_server_registration(
        T,
        "generation-cas",
        expected_state="inactive",
        expected_created_at=original.created_at,
        expected_updated_at=recreated.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=None,
        expected_config_revision=1,
        changed_at=changed_at,
    ) is None
    assert await store.amend_mcp_server_registration(
        T,
        "generation-cas",
        expected_state="inactive",
        expected_created_at=original.created_at,
        expected_updated_at=recreated.updated_at,
        expected_spec_digest=mcp_registration_spec_digest(spec_ref),
        expected_credential_config_digest=None,
        expected_config_revision=1,
        spec_ref=_spec("https://generation-new.example.test"),
        changed_at=changed_at,
        credential_amendment=McpCredentialAmendment("preserve"),
    ) is None
    assert await store.get_mcp_server_lifecycle(T, "generation-cas") == recreated
    assert (await store.get_adapter(T, "generation-cas")).spec_ref == spec_ref


@pytest.mark.store
async def test_a_probe_the_size_of_opbox_persists_on_both_stores(store):
    """A 633-tool probe passed every Python bound and died at the INSERT.

    ``MCP_MAX_TOOL_SNAPSHOT`` was raised 500 -> 5000 precisely because Opbox
    publishes 633 verbs, and every Python bound moved with it - the snapshot
    validator, the receipt's own ``__post_init__``. The column's CHECK did not,
    so the refusal arrived from the database, after the network round trip, on
    the exact server the Opbox integration depends on. The memory store was
    green throughout, which is why a parity test is the one that catches it.
    """
    now = utcnow()
    await _create_lifecycle(store, T, "ext-mcp", now)
    tools = tuple(_tool(f"opbox.verb_{index:04d}") for index in range(633))
    await store.record_mcp_probe_receipt(
        McpProbeReceipt(
            tenant_id=T,
            server_id="ext-mcp",
            probe_id="mcp_probe_opbox_sized",
            outcome="succeeded",
            failure_code=None,
            observed_at=now + timedelta(seconds=2),
            tool_count=len(tools),
        ),
        expected_config_revision=1,
        last_known_tools=tools,
    )
    latest = await store.get_latest_mcp_probe_receipt(T, "ext-mcp")
    assert latest is not None and latest.tool_count == 633
