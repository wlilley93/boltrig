"""PostgreSQL external-MCP lifecycle parity implementation."""

from __future__ import annotations

from .tenant_scope import bind_conn_to_tenant

from boltrig.models import (
    MCP_MAX_RETURNED_PROBE_RECEIPTS,
)

from .mcp_lifecycle_codec import (
    MCP_CONSUMER_MODULE,
    aware,
    lifecycle,
    receipt,
    validate_probe_snapshot,
    validate_snapshot,
)
from .mcp_lifecycle_contract import (
    McpCredentialAmendment,
    validate_mcp_registration_cas,
)
from .mcp_lifecycle_postgres_rows import (
    insert_probe,
    require_mcp_adapter,
    update_health_and_prune,
    update_snapshot,
    upsert_lifecycle_row,
)
from .mcp_registration_postgres import (
    RegistrationExpectation,
    amend_registration,
    delete_registration,
)


class McpLifecycleStorePG:
    async def get_mcp_server_lifecycle(self, tenant_id, server_id):
        row = await self._pool.fetchrow(
            """SELECT m.* FROM mcp_servers m
               JOIN adapters a ON a.tenant_id=m.tenant_id AND a.id=m.id
               WHERE m.tenant_id=$1 AND m.id=$2
                 AND a.module_ref=$3""",
            tenant_id,
            server_id,
            MCP_CONSUMER_MODULE,
        )
        return lifecycle(row)

    async def list_mcp_server_lifecycles(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT m.* FROM mcp_servers m
               JOIN adapters a ON a.tenant_id=m.tenant_id AND a.id=m.id
               WHERE m.tenant_id=$1 AND a.module_ref=$2
               ORDER BY m.id""",
            tenant_id,
            MCP_CONSUMER_MODULE,
        )
        return [lifecycle(row) for row in rows]

    async def set_mcp_server_lifecycle(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_config_revision,
        new_state,
        changed_at,
        last_known_tools=None,
        tools_observed_at=None,
    ):
        aware(changed_at, "changed_at")
        payload = validate_snapshot(last_known_tools, tools_observed_at)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                await require_mcp_adapter(conn, tenant_id, server_id)
                row = await upsert_lifecycle_row(
                    conn,
                    tenant_id,
                    server_id,
                    expected_state,
                    expected_config_revision,
                    new_state,
                    changed_at,
                    payload,
                    tools_observed_at,
                )
                if row is None:
                    return None
                await conn.execute(
                    """UPDATE adapters SET activated=$3,
                         updated_at=GREATEST(updated_at,$4::timestamptz)
                       WHERE tenant_id=$1 AND id=$2""",
                    tenant_id,
                    server_id,
                    new_state == "active",
                    changed_at,
                )
        return lifecycle(row)

    async def record_mcp_probe_receipt(
        self, probe, *, expected_config_revision, last_known_tools=None
    ):
        payload = validate_probe_snapshot(probe, last_known_tools)
        if (
            type(expected_config_revision) is not int
            or expected_config_revision < 1
        ):
            raise ValueError("expected MCP config revision is invalid")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, probe.tenant_id, pool=self._pool)
                await require_mcp_adapter(conn, probe.tenant_id, probe.server_id)
                lifecycle_row = await conn.fetchrow(
                    """SELECT config_revision FROM mcp_servers
                       WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    probe.tenant_id,
                    probe.server_id,
                )
                if lifecycle_row is None:
                    raise LookupError("MCP lifecycle not found")
                if lifecycle_row["config_revision"] != expected_config_revision:
                    return None
                row, inserted = await insert_probe(conn, probe)
                if not inserted:
                    return row
                await update_snapshot(conn, probe, payload)
                await update_health_and_prune(conn, probe)
        persisted = receipt(row)
        assert persisted is not None
        return persisted

    async def get_latest_mcp_probe_receipt(self, tenant_id, server_id):
        row = await self._pool.fetchrow(
            """SELECT r.* FROM mcp_probe_receipts r
               JOIN adapters a
                 ON a.tenant_id=r.tenant_id AND a.id=r.server_id
               WHERE r.tenant_id=$1 AND r.server_id=$2
                 AND a.module_ref=$3
               ORDER BY r.observed_at DESC,r.probe_id DESC LIMIT 1""",
            tenant_id,
            server_id,
            MCP_CONSUMER_MODULE,
        )
        return receipt(row)

    async def list_mcp_probe_receipts(self, tenant_id, server_id, limit=20):
        bounded = max(1, min(int(limit), MCP_MAX_RETURNED_PROBE_RECEIPTS))
        rows = await self._pool.fetch(
            """SELECT r.* FROM mcp_probe_receipts r
               JOIN adapters a
                 ON a.tenant_id=r.tenant_id AND a.id=r.server_id
               WHERE r.tenant_id=$1 AND r.server_id=$2
                 AND a.module_ref=$3
               ORDER BY r.observed_at DESC,r.probe_id DESC LIMIT $4""",
            tenant_id,
            server_id,
            MCP_CONSUMER_MODULE,
            bounded,
        )
        return [receipt(row) for row in rows]

    async def amend_mcp_server_registration(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_created_at,
        expected_updated_at,
        expected_spec_digest,
        expected_credential_config_digest,
        expected_config_revision,
        spec_ref,
        changed_at,
        credential_amendment,
    ):
        validate_mcp_registration_cas(
            expected_created_at=expected_created_at,
            expected_updated_at=expected_updated_at,
            expected_spec_digest=expected_spec_digest,
            expected_credential_config_digest=(
                expected_credential_config_digest
            ),
            expected_config_revision=expected_config_revision,
            changed_at=changed_at,
        )
        if expected_state != "inactive":
            raise ValueError("MCP amendment requires expected inactive state")
        if not isinstance(credential_amendment, McpCredentialAmendment):
            raise TypeError("credential_amendment must be McpCredentialAmendment")
        expected = RegistrationExpectation(
            expected_state,
            expected_created_at,
            expected_updated_at,
            expected_spec_digest,
            expected_credential_config_digest,
            expected_config_revision,
            changed_at,
        )
        return await amend_registration(
            self._pool,
            tenant_id,
            server_id,
            expected,
            spec_ref,
            credential_amendment,
        )

    async def delete_mcp_server_registration(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_created_at,
        expected_updated_at,
        expected_spec_digest,
        expected_credential_config_digest,
        expected_config_revision,
        changed_at,
    ):
        validate_mcp_registration_cas(
            expected_created_at=expected_created_at,
            expected_updated_at=expected_updated_at,
            expected_spec_digest=expected_spec_digest,
            expected_credential_config_digest=(
                expected_credential_config_digest
            ),
            expected_config_revision=expected_config_revision,
            changed_at=changed_at,
        )
        if expected_state not in {"inactive", "retired"}:
            raise ValueError("MCP deletion requires inactive or retired state")
        expected = RegistrationExpectation(
            expected_state,
            expected_created_at,
            expected_updated_at,
            expected_spec_digest,
            expected_credential_config_digest,
            expected_config_revision,
            changed_at,
        )
        return await delete_registration(
            self._pool,
            tenant_id,
            server_id,
            expected,
        )


__all__ = ["McpLifecycleStorePG"]
