"""Persistence mixins for reviewed integration metadata and connections."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models.integrations import (
    IntegrationCatalogueRecord,
    IntegrationConnection,
)
from boltrig.models.integration_auth import (
    secret_contract_from_dict,
    secret_contract_to_dict,
)
from boltrig.models.base import utcnow
from .integration_atomic import (
    active_mem,
    active_pg,
    applicable_mem,
    applicable_pg,
    create_mem,
    create_pg,
    revoke_mem,
    revoke_pg,
)


def _copy_catalogue(item):
    contract = (
        secret_contract_from_dict(secret_contract_to_dict(item.secret_contract))
        if item.secret_contract is not None
        else None
    )
    return replace(item, auth=list(item.auth), secret_contract=contract)


def _copy_connection(connection):
    accounts = [
        dict(account) if isinstance(account, dict) else account for account in connection.accounts
    ]
    return replace(connection, accounts=accounts)


def _catalogue(row):
    if row is None:
        return None
    return IntegrationCatalogueRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        label=row["label"],
        category=row["category"],
        transport=row["transport"],
        description=row["description"],
        certification=row["certification"],
        auth=list(row["auth"] or []),
        adapter_id=row["adapter_id"],
        secret_contract=secret_contract_from_dict(row["secret_contract"]),
        setup_copy=row["setup_copy"],
        access_copy=row["access_copy"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _connection(row):
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


class IntegrationStorePG:
    async def upsert_integration_catalogue(self, item):
        await self._pool.execute(
            """INSERT INTO integration_catalogue
                 (id, tenant_id, label, category, transport, auth, description,
                  certification, adapter_id, secret_contract, setup_copy,
                  access_copy, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 label=EXCLUDED.label, category=EXCLUDED.category,
                 transport=EXCLUDED.transport, auth=EXCLUDED.auth,
                 description=EXCLUDED.description,
                 certification=EXCLUDED.certification,
                 adapter_id=EXCLUDED.adapter_id,
                 secret_contract=EXCLUDED.secret_contract,
                 setup_copy=EXCLUDED.setup_copy, access_copy=EXCLUDED.access_copy,
                 updated_at=EXCLUDED.updated_at""",
            item.id,
            item.tenant_id,
            item.label,
            item.category,
            item.transport,
            item.auth,
            item.description,
            item.certification,
            item.adapter_id,
            (
                secret_contract_to_dict(item.secret_contract)
                if item.secret_contract is not None
                else None
            ),
            item.setup_copy,
            item.access_copy,
            item.created_at,
            item.updated_at,
        )

    async def get_integration_catalogue(self, tenant_id, integration_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM integration_catalogue
                WHERE tenant_id=$1 AND id=$2""",
            tenant_id,
            integration_id,
        )
        return _catalogue(row)

    async def list_integration_catalogue(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM integration_catalogue
                WHERE tenant_id=$1 ORDER BY label, id""",
            tenant_id,
        )
        return [_catalogue(row) for row in rows]

    async def upsert_integration_connection(self, connection):
        await self._pool.execute(
            """INSERT INTO integration_connections
                 (id, tenant_id, integration_id, adapter_id, label, health,
                  credential_ref, credential_owned, accounts, last_checked_at,
                  revoked_at, created_at, updated_at, level, scope_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 integration_id=EXCLUDED.integration_id,
                 adapter_id=EXCLUDED.adapter_id, label=EXCLUDED.label,
                 health=EXCLUDED.health, credential_ref=EXCLUDED.credential_ref,
                 credential_owned=EXCLUDED.credential_owned,
                 accounts=EXCLUDED.accounts,
                 last_checked_at=EXCLUDED.last_checked_at,
                 revoked_at=EXCLUDED.revoked_at,
                 updated_at=EXCLUDED.updated_at""",
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

    async def update_integration_connection_health_if_active(
        self, tenant_id, connection_id, health, checked_at
    ):
        row = await self._pool.fetchrow(
            """UPDATE integration_connections
                  SET health=$3, last_checked_at=$4, updated_at=$4
                WHERE tenant_id=$1 AND id=$2 AND health<>'revoked'
                RETURNING *""",
            tenant_id,
            connection_id,
            health,
            checked_at,
        )
        return _connection(row)

    async def create_integration_connection(self, connection):
        row = await self._pool.fetchrow(
            """INSERT INTO integration_connections
                 (id, tenant_id, integration_id, adapter_id, label, health,
                  credential_ref, credential_owned, accounts, last_checked_at,
                  revoked_at, created_at, updated_at, level, scope_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
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
        return row is not None

    async def create_integration_connection_with_credential(self, connection, credential):
        return await create_pg(self._pool, connection, credential)

    async def get_integration_connection(self, tenant_id, connection_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM integration_connections
                WHERE tenant_id=$1 AND id=$2""",
            tenant_id,
            connection_id,
        )
        return _connection(row)

    async def get_active_integration_connection_for_adapter(self, tenant_id, adapter_id):
        return await active_pg(self._pool, tenant_id, adapter_id)

    async def list_applicable_integration_connections_for_adapter(
        self, tenant_id, adapter_id, owner
    ):
        return await applicable_pg(self._pool, tenant_id, adapter_id, owner)

    async def list_integration_connections(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM integration_connections
                WHERE tenant_id=$1 ORDER BY created_at, id""",
            tenant_id,
        )
        return [_connection(row) for row in rows]

    async def revoke_integration_connection(self, tenant_id, connection_id):
        row = await self._pool.fetchrow(
            """UPDATE integration_connections
                  SET health='revoked', credential_ref=NULL,
                      credential_owned=false, revoked_at=now(), updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND health<>'revoked'
                RETURNING *""",
            tenant_id,
            connection_id,
        )
        return _connection(row)

    async def revoke_integration_connection_with_credential(self, tenant_id, connection_id):
        return await revoke_pg(self._pool, tenant_id, connection_id)


class IntegrationStoreMem:
    async def upsert_integration_catalogue(self, item):
        catalogue, _ = _memory_tables(self)
        catalogue[(item.tenant_id, item.id)] = _copy_catalogue(item)

    async def get_integration_catalogue(self, tenant_id, integration_id):
        catalogue, _ = _memory_tables(self)
        item = catalogue.get((tenant_id, integration_id))
        return _copy_catalogue(item) if item is not None else None

    async def list_integration_catalogue(self, tenant_id):
        catalogue, _ = _memory_tables(self)
        rows = [row for (tenant, _), row in catalogue.items() if tenant == tenant_id]
        return [_copy_catalogue(row) for row in sorted(rows, key=lambda row: (row.label, row.id))]

    async def upsert_integration_connection(self, connection):
        _, connections = _memory_tables(self)
        connections[(connection.tenant_id, connection.id)] = _copy_connection(connection)

    async def update_integration_connection_health_if_active(
        self, tenant_id, connection_id, health, checked_at
    ):
        _, connections = _memory_tables(self)
        key = (tenant_id, connection_id)
        connection = connections.get(key)
        if connection is None or connection.health == "revoked":
            return None
        updated = replace(
            connection,
            health=health,
            last_checked_at=checked_at,
            updated_at=checked_at,
        )
        connections[key] = updated
        return _copy_connection(updated)

    async def create_integration_connection(self, connection):
        _, connections = _memory_tables(self)
        if any(
            row.tenant_id == connection.tenant_id
            and row.adapter_id == connection.adapter_id
            and row.level == connection.level
            and row.scope_id == connection.scope_id
            and row.health != "revoked"
            for row in connections.values()
        ):
            return False
        key = (connection.tenant_id, connection.id)
        if key in connections:
            return False
        connections[key] = _copy_connection(connection)
        return True

    async def create_integration_connection_with_credential(self, connection, credential):
        _, connections = _memory_tables(self)
        return create_mem(connections, self._creds, connection, credential)

    async def get_integration_connection(self, tenant_id, connection_id):
        _, connections = _memory_tables(self)
        connection = connections.get((tenant_id, connection_id))
        return _copy_connection(connection) if connection is not None else None

    async def get_active_integration_connection_for_adapter(self, tenant_id, adapter_id):
        _, connections = _memory_tables(self)
        return active_mem(connections, tenant_id, adapter_id)

    async def list_applicable_integration_connections_for_adapter(
        self, tenant_id, adapter_id, owner
    ):
        _, connections = _memory_tables(self)
        return applicable_mem(connections, tenant_id, adapter_id, owner)

    async def list_integration_connections(self, tenant_id):
        _, connections = _memory_tables(self)
        rows = [row for (tenant, _), row in connections.items() if tenant == tenant_id]
        return [
            _copy_connection(row) for row in sorted(rows, key=lambda row: (row.created_at, row.id))
        ]

    async def revoke_integration_connection(self, tenant_id, connection_id):
        _, connections = _memory_tables(self)
        key = (tenant_id, connection_id)
        connection = connections.get(key)
        if connection is None or connection.health == "revoked":
            return None
        now = utcnow()
        revoked = replace(
            connection,
            health="revoked",
            credential_ref=None,
            credential_owned=False,
            revoked_at=now,
            updated_at=now,
        )
        connections[key] = revoked
        return _copy_connection(revoked)

    async def revoke_integration_connection_with_credential(self, tenant_id, connection_id):
        _, connections = _memory_tables(self)
        return revoke_mem(connections, self._creds, tenant_id, connection_id)


def _memory_tables(store):
    catalogue = getattr(store, "_integration_catalogue", None)
    connections = getattr(store, "_integration_connections", None)
    if catalogue is None:
        catalogue = {}
        store._integration_catalogue = catalogue
    if connections is None:
        connections = {}
        store._integration_connections = connections
    return catalogue, connections
