"""Atomic credential-plus-connection persistence for dynamic integrations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import CredentialResolution
from boltrig.models.base import utcnow
from boltrig.models.integrations import IntegrationConnection

from .sealing import seal_ref


class _CreateConflict(Exception):
    """Internal signal whose only purpose is rolling back the PG transaction."""


def _connection(row: Any) -> IntegrationConnection | None:
    if row is None:
        return None
    return IntegrationConnection(
        id=row["id"],
        tenant_id=row["tenant_id"],
        integration_id=row["integration_id"],
        adapter_id=row["adapter_id"],
        label=row["label"],
        health=row["health"],
        credential_ref=row["credential_ref"],
        credential_owned=bool(row["credential_owned"]),
        accounts=list(row["accounts"] or []),
        last_checked_at=row["last_checked_at"],
        revoked_at=row["revoked_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate(connection: IntegrationConnection, credential: object) -> None:
    if (
        not connection.credential_owned
        or not connection.credential_ref
        or not isinstance(credential, dict)
        or not credential
    ):
        raise ValueError("atomic integration setup requires one owned credential reference")


async def create_pg(pool: Any, connection: IntegrationConnection, credential: dict) -> bool:
    _validate(connection, credential)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    connection.tenant_id,
                )
                credential_row = await conn.fetchrow(
                    """INSERT INTO credential_refs
                         (id,tenant_id,store,ref,data,expires_at)
                       VALUES ($1,$2,$3,$4,$5,$6)
                       ON CONFLICT DO NOTHING
                       RETURNING id""",
                    connection.credential_ref,
                    connection.tenant_id,
                    credential.get("store", "env"),
                    credential.get("ref", ""),
                    seal_ref(credential),
                    credential.get("expires_at"),
                )
                if credential_row is None:
                    raise _CreateConflict
                row = await conn.fetchrow(
                    """INSERT INTO integration_connections
                         (id,tenant_id,integration_id,adapter_id,label,health,
                          credential_ref,credential_owned,accounts,
                          last_checked_at,revoked_at,created_at,updated_at)
                       VALUES
                         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                       ON CONFLICT DO NOTHING
                       RETURNING id""",
                    connection.id,
                    connection.tenant_id,
                    connection.integration_id,
                    connection.adapter_id,
                    connection.label,
                    connection.health,
                    connection.credential_ref,
                    connection.credential_owned,
                    connection.accounts,
                    connection.last_checked_at,
                    connection.revoked_at,
                    connection.created_at,
                    connection.updated_at,
                )
                if row is None:
                    raise _CreateConflict
    except _CreateConflict:
        return False
    return True


async def active_pg(pool: Any, tenant_id: str, adapter_id: str):
    rows = await pool.fetch(
        """SELECT * FROM integration_connections
            WHERE tenant_id=$1 AND adapter_id=$2 AND health<>'revoked'
            LIMIT 2""",
        tenant_id,
        adapter_id,
    )
    if len(rows) > 1:
        raise CredentialResolution(
            f"adapter '{adapter_id}' has multiple active integration connections"
        )
    return _connection(rows[0]) if rows else None


async def revoke_pg(pool: Any, tenant_id: str, connection_id: str):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            previous_row = await conn.fetchrow(
                """SELECT * FROM integration_connections
                    WHERE tenant_id=$1 AND id=$2
                    FOR UPDATE""",
                tenant_id,
                connection_id,
            )
            previous = _connection(previous_row)
            if previous is None or previous.health == "revoked":
                return previous, None, False
            revoked_row = await conn.fetchrow(
                """UPDATE integration_connections
                      SET health='revoked',credential_ref=NULL,
                          credential_owned=false,revoked_at=now(),updated_at=now()
                    WHERE tenant_id=$1 AND id=$2
                    RETURNING *""",
                tenant_id,
                connection_id,
            )
            deleted = False
            if previous.credential_owned and previous.credential_ref:
                result = await conn.execute(
                    "DELETE FROM credential_refs WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    previous.credential_ref,
                )
                deleted = result == "DELETE 1"
            return _connection(revoked_row), previous.credential_ref, deleted


def create_mem(
    connections: dict,
    credentials: dict,
    connection: IntegrationConnection,
    credential: dict,
) -> bool:
    _validate(connection, credential)
    sealed = seal_ref(credential)
    credential_key = (connection.tenant_id, connection.credential_ref)
    connection_key = (connection.tenant_id, connection.id)
    conflict = credential_key in credentials or connection_key in connections
    conflict = conflict or any(
        row.tenant_id == connection.tenant_id
        and row.adapter_id == connection.adapter_id
        and row.health != "revoked"
        for row in connections.values()
    )
    if conflict:
        return False
    # No await or fallible work occurs between these assignments.
    credentials[credential_key] = sealed
    connections[connection_key] = replace(
        connection,
        accounts=[dict(account) for account in connection.accounts],
    )
    return True


def active_mem(connections: dict, tenant_id: str, adapter_id: str):
    matches = [
        row
        for row in connections.values()
        if row.tenant_id == tenant_id and row.adapter_id == adapter_id and row.health != "revoked"
    ]
    if len(matches) > 1:
        raise CredentialResolution(
            f"adapter '{adapter_id}' has multiple active integration connections"
        )
    if not matches:
        return None
    return replace(matches[0], accounts=[dict(item) for item in matches[0].accounts])


def revoke_mem(connections: dict, credentials: dict, tenant_id: str, connection_id: str):
    key = (tenant_id, connection_id)
    previous = connections.get(key)
    if previous is None or previous.health == "revoked":
        return (
            replace(previous) if previous is not None else None,
            None,
            False,
        )
    credential_ref = previous.credential_ref
    now = utcnow()
    revoked = replace(
        previous,
        health="revoked",
        credential_ref=None,
        credential_owned=False,
        revoked_at=now,
        updated_at=now,
    )
    deleted = bool(
        previous.credential_owned and credential_ref and (tenant_id, credential_ref) in credentials
    )
    connections[key] = revoked
    if previous.credential_owned and credential_ref:
        credentials.pop((tenant_id, credential_ref), None)
    return replace(revoked), credential_ref, deleted
