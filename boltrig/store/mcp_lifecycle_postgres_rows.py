"""PostgreSQL row operations for external-MCP lifecycle and probe evidence."""

from __future__ import annotations

from boltrig.models import MCP_PROBE_RECEIPTS_PER_SERVER

from .mcp_lifecycle_codec import (
    MCP_CONSUMER_MODULE,
    receipt,
    validate_transition,
)


async def require_mcp_adapter(conn, tenant_id: str, server_id: str):
    row = await conn.fetchrow(
        """SELECT * FROM adapters
           WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
        tenant_id,
        server_id,
    )
    if row is None:
        raise LookupError("MCP adapter not found")
    if row["module_ref"] != MCP_CONSUMER_MODULE:
        raise ValueError("adapter is not an external MCP consumer")
    return row


async def upsert_lifecycle_row(
    conn,
    tenant_id,
    server_id,
    expected_state,
    expected_config_revision,
    new_state,
    changed_at,
    payload,
    tools_observed_at,
):
    row = await conn.fetchrow(
        """SELECT * FROM mcp_servers
           WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
        tenant_id,
        server_id,
    )
    if (row is None and expected_config_revision is not None) or (
        row is not None and row["config_revision"] != expected_config_revision
    ):
        return None
    if not validate_transition(
        existing_state=None if row is None else row["status"],
        expected_state=expected_state,
        new_state=new_state,
    ):
        return None
    if row is None:
        return await conn.fetchrow(
            """INSERT INTO mcp_servers
                 (id,tenant_id,status,config_revision,last_known_tools,
                  tools_observed_at,retired_at,created_at,updated_at)
               VALUES ($1,$2,$3,1,$4,$5,NULL,$6,$6)
               RETURNING *""",
            server_id,
            tenant_id,
            new_state,
            payload or [],
            tools_observed_at,
            changed_at,
        )
    return await conn.fetchrow(
        """UPDATE mcp_servers SET
             status=$3,
             last_known_tools=CASE
               WHEN $4::jsonb IS NOT NULL
                AND (tools_observed_at IS NULL
                     OR tools_observed_at < $5::timestamptz)
               THEN $4::jsonb ELSE last_known_tools END,
             tools_observed_at=CASE
               WHEN $4::jsonb IS NOT NULL
                AND (tools_observed_at IS NULL
                     OR tools_observed_at < $5::timestamptz)
               THEN $5::timestamptz ELSE tools_observed_at END,
             retired_at=CASE WHEN $3='retired'
               THEN $6::timestamptz ELSE NULL END,
             updated_at=GREATEST(updated_at,$6::timestamptz)
           WHERE tenant_id=$1 AND id=$2
           RETURNING *""",
        tenant_id,
        server_id,
        new_state,
        payload,
        tools_observed_at,
        changed_at,
    )


async def insert_probe(conn, probe):
    row = await conn.fetchrow(
        """INSERT INTO mcp_probe_receipts
             (tenant_id,server_id,probe_id,outcome,failure_code,
              observed_at,tool_count)
           VALUES ($1,$2,$3,$4,$5,$6,$7)
           ON CONFLICT DO NOTHING
           RETURNING *""",
        probe.tenant_id,
        probe.server_id,
        probe.probe_id,
        probe.outcome,
        probe.failure_code,
        probe.observed_at,
        probe.tool_count,
    )
    if row is not None:
        return row, True
    existing = receipt(
        await conn.fetchrow(
            """SELECT * FROM mcp_probe_receipts
               WHERE tenant_id=$1 AND server_id=$2 AND probe_id=$3""",
            probe.tenant_id,
            probe.server_id,
            probe.probe_id,
        )
    )
    if existing != probe:
        raise ValueError("MCP probe id already records a different attempt")
    return existing, False


async def update_snapshot(conn, probe, payload) -> None:
    if payload is None:
        return
    await conn.execute(
        """UPDATE mcp_servers SET
             last_known_tools=CASE
               WHEN tools_observed_at IS NULL
                 OR tools_observed_at < $3::timestamptz
               THEN $4::jsonb ELSE last_known_tools END,
             tools_observed_at=CASE
               WHEN tools_observed_at IS NULL
                 OR tools_observed_at < $3::timestamptz
               THEN $3::timestamptz ELSE tools_observed_at END,
             updated_at=CASE
               WHEN tools_observed_at IS NULL
                 OR tools_observed_at < $3::timestamptz
               THEN GREATEST(updated_at,$3::timestamptz)
               ELSE updated_at END
           WHERE tenant_id=$1 AND id=$2""",
        probe.tenant_id,
        probe.server_id,
        probe.observed_at,
        payload,
    )


async def update_health_and_prune(conn, probe) -> None:
    latest_id = await conn.fetchval(
        """SELECT probe_id FROM mcp_probe_receipts
           WHERE tenant_id=$1 AND server_id=$2
           ORDER BY observed_at DESC,probe_id DESC LIMIT 1""",
        probe.tenant_id,
        probe.server_id,
    )
    if latest_id == probe.probe_id:
        await conn.execute(
            """UPDATE adapters SET health=$3,
                 updated_at=GREATEST(updated_at,$4::timestamptz)
               WHERE tenant_id=$1 AND id=$2""",
            probe.tenant_id,
            probe.server_id,
            "ok" if probe.outcome == "succeeded" else "down",
            probe.observed_at,
        )
    await conn.execute(
        """DELETE FROM mcp_probe_receipts
           WHERE tenant_id=$1 AND server_id=$2 AND probe_id IN (
             SELECT probe_id FROM mcp_probe_receipts
             WHERE tenant_id=$1 AND server_id=$2
             ORDER BY observed_at DESC,probe_id DESC OFFSET $3
           )""",
        probe.tenant_id,
        probe.server_id,
        MCP_PROBE_RECEIPTS_PER_SERVER,
    )


__all__ = [
    "insert_probe",
    "require_mcp_adapter",
    "update_health_and_prune",
    "update_snapshot",
    "upsert_lifecycle_row",
]
