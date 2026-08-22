"""Atomic credential-plus-connection persistence for dynamic integrations."""

from __future__ import annotations

from .tenant_scope import bind_conn_to_tenant

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
        level=row["level"],
        scope_id=row["scope_id"],
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
                await bind_conn_to_tenant(
                    conn, connection.tenant_id, pool=pool
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
                          last_checked_at,revoked_at,created_at,updated_at,
                          level,scope_id)
                       VALUES
                         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
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
                    connection.level,
                    connection.scope_id,
                )
                if row is None:
                    raise _CreateConflict
    except _CreateConflict:
        return False
    return True


def _one_per_scope(connections: list, adapter_id: str) -> list:
    """``_one_per_scope`` still fails closed on ambiguity, but PER SCOPE.

    Two active rows at the same (level, scope_id) is the corruption the old
    adapter-wide check was really guarding against, and the partial unique index
    makes it unreachable on Postgres. An org row and a user row together is the
    intended state, not a conflict.
    """
    seen: set[tuple[str, str]] = set()
    for connection in connections:
        key = (connection.level, connection.scope_id)
        if key in seen:
            raise CredentialResolution(
                f"adapter '{adapter_id}' has multiple active integration "
                f"connections at scope {connection.level}"
            )
        seen.add(key)
    return connections


async def active_pg(pool: Any, tenant_id: str, adapter_id: str):
    """The ORG connection for an adapter. Unchanged meaning: before scoping
    existed every connection was org-wide, so this is what callers already had.
    """
    rows = await pool.fetch(
        """SELECT * FROM integration_connections
            WHERE tenant_id=$1 AND adapter_id=$2 AND health<>'revoked'
              AND level='org'
            LIMIT 2""",
        tenant_id,
        adapter_id,
    )
    found = _one_per_scope([_connection(row) for row in rows], adapter_id)
    return found[0] if found else None


async def applicable_pg(pool: Any, tenant_id: str, adapter_id: str, owner: str | None):
    """Every active connection that could serve ``owner``: theirs and the org's.

    ONE query, deliberately. At most two rows can apply, so fetching both costs
    what fetching the org row alone used to -- and this runs on every adapter
    dispatch, where a second round trip per call would be a real cost. The
    caller picks between them because the precedence needs the org policy flag,
    which is not the store's business.
    """
    rows = await pool.fetch(
        """SELECT * FROM integration_connections
            WHERE tenant_id=$1 AND adapter_id=$2 AND health<>'revoked'
              AND (level='org' OR (level='user' AND scope_id=$3))
            LIMIT 4""",
        tenant_id,
        adapter_id,
        owner or "",
    )
    return _one_per_scope([_connection(row) for row in rows], adapter_id)


async def revoke_pg(pool: Any, tenant_id: str, connection_id: str):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await bind_conn_to_tenant(conn, tenant_id, pool=pool)
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
        and row.level == connection.level
        and row.scope_id == connection.scope_id
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


def _active_mem_rows(connections: dict, tenant_id: str, adapter_id: str):
    return [
        row
        for row in connections.values()
        if row.tenant_id == tenant_id and row.adapter_id == adapter_id and row.health != "revoked"
    ]


def _copied(row):
    return replace(row, accounts=[dict(item) for item in row.accounts])


def active_mem(connections: dict, tenant_id: str, adapter_id: str):
    """The ORG connection, matching active_pg."""
    matches = [
        row for row in _active_mem_rows(connections, tenant_id, adapter_id) if row.level == "org"
    ]
    found = _one_per_scope(matches, adapter_id)
    return _copied(found[0]) if found else None


def applicable_mem(connections: dict, tenant_id: str, adapter_id: str, owner: str | None):
    """The memory twin of applicable_pg: the caller's own row and the org's."""
    matches = [
        row
        for row in _active_mem_rows(connections, tenant_id, adapter_id)
        if row.level == "org" or (row.level == "user" and row.scope_id == (owner or ""))
    ]
    return [_copied(row) for row in _one_per_scope(matches, adapter_id)]


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
