"""Atomic PostgreSQL amendment and deletion of external-MCP registrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from .mcp_lifecycle_codec import lifecycle
from .mcp_lifecycle_contract import (
    McpCredentialAmendment,
    McpRegistrationAmendResult,
    McpRegistrationDeleteResult,
    mcp_credential_config_digest,
    mcp_registration_spec_digest,
)
from .mcp_lifecycle_postgres_rows import require_mcp_adapter
from .rows import _adapter
from .sealing import seal_ref, unseal_ref


@dataclass(frozen=True)
class RegistrationExpectation:
    state: str
    created_at: datetime
    updated_at: datetime
    spec_digest: str
    credential_config_digest: str | None
    config_revision: int
    changed_at: datetime


def _stored_credential_id(spec_ref: str | None) -> str | None:
    if not spec_ref:
        return None
    try:
        value = json.loads(spec_ref)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    credential_id = value.get("credential_id")
    return credential_id if isinstance(credential_id, str) and credential_id else None


def _replacement_credential_id(spec_ref: str) -> str | None:
    try:
        value = json.loads(spec_ref)
    except (TypeError, ValueError) as exc:
        raise ValueError("replacement MCP spec must be a JSON object") from exc
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("url"), str)
        or not value["url"].strip()
        or type(value.get("allow_internal")) is not bool
    ):
        raise ValueError("replacement MCP spec must contain url and allow_internal")
    credential_id = value.get("credential_id")
    if credential_id is not None and (
        not isinstance(credential_id, str) or not credential_id
    ):
        raise ValueError("replacement MCP spec credential id is invalid")
    return credential_id


async def _effective_credential_id(
    conn, tenant_id: str, server_id: str, spec_ref: str | None
) -> str | None:
    explicit = _stored_credential_id(spec_ref)
    if explicit is not None:
        return explicit
    derived = f"{server_id}-mcp-token"
    exists = await conn.fetchval(
        """SELECT 1 FROM credential_refs
           WHERE tenant_id=$1 AND id=$2""",
        tenant_id,
        derived,
    )
    return derived if exists is not None else None


def _credential_metadata(row) -> dict | None:
    if row is None:
        return None
    if row["data"] is not None:
        return unseal_ref(row["data"])
    return {"store": row["store"], "ref": row["ref"]}


def _current_credential_id(
    previous_credential_id: str | None,
    replacement_spec_ref: str,
    amendment: McpCredentialAmendment,
) -> str | None:
    replacement_id = _replacement_credential_id(replacement_spec_ref)
    if amendment.mode == "preserve":
        if replacement_id != previous_credential_id:
            raise ValueError("preserved MCP credential id differs from the registration")
        return previous_credential_id
    if amendment.mode == "remove":
        if replacement_id is not None:
            raise ValueError("removed MCP credential remains in replacement spec")
        return None
    if replacement_id != amendment.credential_id:
        raise ValueError("replacement MCP credential id differs from replacement spec")
    return amendment.credential_id


async def _locked_registration(conn, tenant_id, server_id, expected):
    adapter_row = await require_mcp_adapter(conn, tenant_id, server_id)
    lifecycle_row = await conn.fetchrow(
        """SELECT * FROM mcp_servers
           WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
        tenant_id,
        server_id,
    )
    if lifecycle_row is None:
        raise LookupError("MCP lifecycle not found")
    matches = (
        lifecycle_row["status"] == expected.state
        and lifecycle_row["created_at"] == expected.created_at
        and lifecycle_row["updated_at"] == expected.updated_at
        and lifecycle_row["config_revision"] == expected.config_revision
        and mcp_registration_spec_digest(adapter_row["spec_ref"])
        == expected.spec_digest
    )
    return (adapter_row, lifecycle_row) if matches else None


async def _credential_state(conn, tenant_id, server_id, spec_ref, expected_digest):
    await conn.execute("LOCK TABLE credential_refs IN SHARE ROW EXCLUSIVE MODE")
    credential_id = await _effective_credential_id(
        conn, tenant_id, server_id, spec_ref
    )
    row = (
        None
        if credential_id is None
        else await conn.fetchrow(
            """SELECT store,ref,data FROM credential_refs
               WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
            tenant_id,
            credential_id,
        )
    )
    matches = mcp_credential_config_digest(_credential_metadata(row)) == expected_digest
    return matches, credential_id


async def _replace_credential(
    conn,
    tenant_id: str,
    credential_id: str,
    amendment: McpCredentialAmendment,
    changed_at: datetime,
) -> None:
    assert amendment.credential_metadata is not None
    row = await conn.fetchrow(
        """SELECT store,ref,data FROM credential_refs
           WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
        tenant_id,
        credential_id,
    )
    metadata = dict(amendment.credential_metadata)
    if row is not None and _credential_metadata(row) != metadata:
        raise ValueError("existing MCP credential reference metadata is immutable")
    await conn.execute(
        """INSERT INTO credential_refs
             (id,tenant_id,store,ref,data,expires_at,created_at,updated_at)
           VALUES ($1,$2,$3,$4,$5,NULL,$6,$6)
           ON CONFLICT (tenant_id,id) DO UPDATE SET
             store=EXCLUDED.store,
             ref=EXCLUDED.ref,
             data=EXCLUDED.data,
             expires_at=NULL,
             updated_at=EXCLUDED.updated_at""",
        credential_id,
        tenant_id,
        metadata["store"],
        metadata["ref"],
        seal_ref(metadata),
        changed_at,
    )


async def _write_amendment(conn, tenant_id, server_id, spec_ref, changed_at):
    adapter_row = await conn.fetchrow(
        """UPDATE adapters SET
             spec_ref=$3,health='unknown',activated=false,updated_at=$4
           WHERE tenant_id=$1 AND id=$2
           RETURNING *""",
        tenant_id,
        server_id,
        spec_ref,
        changed_at,
    )
    lifecycle_row = await conn.fetchrow(
        """UPDATE mcp_servers SET
             config_revision=config_revision+1,
             last_known_tools='[]'::jsonb,
             tools_observed_at=NULL,
             updated_at=$3
           WHERE tenant_id=$1 AND id=$2
           RETURNING *""",
        tenant_id,
        server_id,
        changed_at,
    )
    await conn.execute(
        """DELETE FROM mcp_probe_receipts
           WHERE tenant_id=$1 AND server_id=$2""",
        tenant_id,
        server_id,
    )
    return adapter_row, lifecycle_row


async def amend_registration(
    pool,
    tenant_id: str,
    server_id: str,
    expected: RegistrationExpectation,
    spec_ref: str,
    amendment: McpCredentialAmendment,
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", tenant_id
            )
            rows = await _locked_registration(conn, tenant_id, server_id, expected)
            if rows is None:
                return None
            adapter_row, _ = rows
            matches, previous_id = await _credential_state(
                conn,
                tenant_id,
                server_id,
                adapter_row["spec_ref"],
                expected.credential_config_digest,
            )
            if not matches:
                return None
            current_id = _current_credential_id(previous_id, spec_ref, amendment)
            if amendment.mode == "replace":
                assert current_id is not None
                await _replace_credential(
                    conn, tenant_id, current_id, amendment, expected.changed_at
                )
            updated_rows = await _write_amendment(
                conn, tenant_id, server_id, spec_ref, expected.changed_at
            )
    adapter = _adapter(updated_rows[0])
    current_lifecycle = lifecycle(updated_rows[1])
    assert adapter is not None and current_lifecycle is not None
    return McpRegistrationAmendResult(adapter, current_lifecycle, current_id)


async def delete_registration(
    pool,
    tenant_id: str,
    server_id: str,
    expected: RegistrationExpectation,
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", tenant_id
            )
            rows = await _locked_registration(conn, tenant_id, server_id, expected)
            if rows is None:
                return None
            adapter_row, lifecycle_row = rows
            matches, _ = await _credential_state(
                conn,
                tenant_id,
                server_id,
                adapter_row["spec_ref"],
                expected.credential_config_digest,
            )
            if not matches:
                return None
            await conn.execute(
                """DELETE FROM adapters
                   WHERE tenant_id=$1 AND id=$2""",
                tenant_id,
                server_id,
            )
    return McpRegistrationDeleteResult(
        server_id,
        lifecycle_row["status"],
        lifecycle_row["config_revision"],
        expected.changed_at,
    )


__all__ = [
    "RegistrationExpectation",
    "amend_registration",
    "delete_registration",
]
