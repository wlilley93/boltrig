"""Persistence mixins for canonical capability routing (SPEC §8).

Both backends return bindings and policies in ONE order - priority ascending,
then id - because the resolver picks a single execution plan from them and an
unstable order would make a route non-deterministic. The in-memory store is the
reference implementation; Postgres must match it row for row.
"""

from __future__ import annotations

from dataclasses import replace

from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    RoutingPolicy,
    SourceOperation,
)


def _connection(r):
    if r is None:
        return None
    return ProviderConnection(
        id=r["id"], tenant_id=r["tenant_id"], label=r["label"], provider=r["provider"],
        source_type=r["source_type"], adapter_id=r["adapter_id"],
        integration_connection_id=r["integration_connection_id"],
        workspace_id=r["workspace_id"], account_ref=r["account_ref"],
        credential_ref=r["credential_ref"], health=r["health"], status=r["status"],
        trust_level=r["trust_level"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _operation(r):
    if r is None:
        return None
    return SourceOperation(
        id=r["id"], tenant_id=r["tenant_id"], provider=r["provider"],
        source_type=r["source_type"], connection_id=r["connection_id"],
        title=r["title"], description=r["description"],
        input_schema=r["input_schema"] or {}, output_schema=r["output_schema"],
        annotations=r["annotations"] or {}, schema_digest=r["schema_digest"],
        catalogue_revision=r["catalogue_revision"],
        consequence_hint=r["consequence_hint"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _capability_binding(r):
    if r is None:
        return None
    return CapabilityBinding(
        binding_id=r["binding_id"], tenant_id=r["tenant_id"],
        capability_id=r["capability_id"], capability_version=r["capability_version"],
        source_operation_id=r["source_operation_id"], connection_id=r["connection_id"],
        status=r["status"], trust_level=r["trust_level"], priority=r["priority"],
        workspace_predicate=r["workspace_predicate"],
        input_transform_ref=r["input_transform_ref"],
        output_transform_ref=r["output_transform_ref"],
        source_schema_digest=r["source_schema_digest"],
        consequence_override=r["consequence_override"], health=r["health"],
        fallback_policy=r["fallback_policy"], created_from=r["created_from"],
        reviewed_by=r["reviewed_by"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _routing_policy(r):
    if r is None:
        return None
    return RoutingPolicy(
        id=r["id"], tenant_id=r["tenant_id"], capability_id=r["capability_id"],
        binding_id=r["binding_id"], operation_class=r["operation_class"],
        capability_version=r["capability_version"], scope=r["scope"],
        workspace_id=r["workspace_id"], precedence=r["precedence"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


class CapabilityRoutingStoreMem:
    def _init_capability_routing_state(self) -> None:
        self._provider_connections: dict[tuple[str, str], ProviderConnection] = {}
        self._source_operations: dict[tuple[str, str], SourceOperation] = {}
        self._capability_bindings: dict[tuple[str, str], CapabilityBinding] = {}
        self._routing_policies: dict[tuple[str, str], RoutingPolicy] = {}

    async def upsert_provider_connection(self, connection):
        self._provider_connections[(connection.tenant_id, connection.id)] = replace(connection)

    async def get_provider_connection(self, tenant_id, connection_id):
        found = self._provider_connections.get((tenant_id, connection_id))
        return replace(found) if found is not None else None

    async def list_provider_connections(self, tenant_id):
        return [
            replace(c)
            for (t, _), c in sorted(self._provider_connections.items())
            if t == tenant_id
        ]

    async def upsert_source_operation(self, operation):
        self._source_operations[(operation.tenant_id, operation.id)] = replace(operation)

    async def get_source_operation(self, tenant_id, operation_id):
        found = self._source_operations.get((tenant_id, operation_id))
        return replace(found) if found is not None else None

    async def list_source_operations(self, tenant_id, connection_id=None):
        return [
            replace(o)
            for (t, _), o in sorted(self._source_operations.items())
            if t == tenant_id and (connection_id is None or o.connection_id == connection_id)
        ]

    async def upsert_capability_binding(self, binding):
        # Keyed by binding_id, NOT by capability: a sibling binding for the same
        # capability coexists rather than replacing (SPEC §8, §11.1 site 2).
        self._capability_bindings[(binding.tenant_id, binding.binding_id)] = replace(binding)

    async def list_capability_bindings(
        self, tenant_id, capability_id=None, *, source_operation_id=None
    ):
        rows = [
            replace(b)
            for (t, _), b in self._capability_bindings.items()
            if t == tenant_id
            and (capability_id is None or b.capability_id == capability_id)
            and (source_operation_id is None or b.source_operation_id == source_operation_id)
        ]
        return sorted(rows, key=lambda b: (b.priority, b.binding_id))

    async def upsert_routing_policy(self, policy):
        self._routing_policies[(policy.tenant_id, policy.id)] = replace(policy)

    async def list_routing_policies(self, tenant_id, capability_id=None):
        rows = [
            replace(p)
            for (t, _), p in self._routing_policies.items()
            if t == tenant_id and (capability_id is None or p.capability_id == capability_id)
        ]
        return sorted(rows, key=lambda p: (p.precedence, p.id))


class CapabilityRoutingStorePG:
    async def upsert_provider_connection(self, connection):
        await self._pool.execute(
            """INSERT INTO provider_connections (
                 id, tenant_id, label, provider, source_type, adapter_id,
                 integration_connection_id, workspace_id, account_ref,
                 credential_ref, health, status, trust_level
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 label=EXCLUDED.label, provider=EXCLUDED.provider,
                 source_type=EXCLUDED.source_type, adapter_id=EXCLUDED.adapter_id,
                 integration_connection_id=EXCLUDED.integration_connection_id,
                 workspace_id=EXCLUDED.workspace_id,
                 account_ref=EXCLUDED.account_ref,
                 credential_ref=EXCLUDED.credential_ref,
                 health=EXCLUDED.health, status=EXCLUDED.status,
                 trust_level=EXCLUDED.trust_level, updated_at=now()""",
            connection.id, connection.tenant_id, connection.label, connection.provider,
            connection.source_type, connection.adapter_id,
            connection.integration_connection_id, connection.workspace_id,
            connection.account_ref, connection.credential_ref, connection.health,
            connection.status, connection.trust_level,
        )

    async def get_provider_connection(self, tenant_id, connection_id):
        return _connection(await self._pool.fetchrow(
            "SELECT * FROM provider_connections WHERE tenant_id=$1 AND id=$2",
            tenant_id, connection_id,
        ))

    async def list_provider_connections(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM provider_connections WHERE tenant_id=$1 ORDER BY id",
            tenant_id,
        )
        return [_connection(row) for row in rows]

    async def upsert_source_operation(self, operation):
        await self._pool.execute(
            """INSERT INTO source_operations (
                 id, tenant_id, provider, source_type, connection_id, title,
                 description, input_schema, output_schema, annotations,
                 schema_digest, catalogue_revision, consequence_hint
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 provider=EXCLUDED.provider, source_type=EXCLUDED.source_type,
                 connection_id=EXCLUDED.connection_id, title=EXCLUDED.title,
                 description=EXCLUDED.description,
                 input_schema=EXCLUDED.input_schema,
                 output_schema=EXCLUDED.output_schema,
                 annotations=EXCLUDED.annotations,
                 schema_digest=EXCLUDED.schema_digest,
                 catalogue_revision=EXCLUDED.catalogue_revision,
                 consequence_hint=EXCLUDED.consequence_hint, updated_at=now()""",
            operation.id, operation.tenant_id, operation.provider, operation.source_type,
            operation.connection_id, operation.title, operation.description,
            operation.input_schema, operation.output_schema, operation.annotations,
            operation.schema_digest, operation.catalogue_revision,
            operation.consequence_hint,
        )

    async def get_source_operation(self, tenant_id, operation_id):
        return _operation(await self._pool.fetchrow(
            "SELECT * FROM source_operations WHERE tenant_id=$1 AND id=$2",
            tenant_id, operation_id,
        ))

    async def list_source_operations(self, tenant_id, connection_id=None):
        rows = await self._pool.fetch(
            """SELECT * FROM source_operations
               WHERE tenant_id=$1 AND ($2::text IS NULL OR connection_id=$2)
               ORDER BY id""",
            tenant_id, connection_id,
        )
        return [_operation(row) for row in rows]

    async def upsert_capability_binding(self, binding):
        await self._pool.execute(
            """INSERT INTO capability_bindings (
                 binding_id, tenant_id, capability_id, capability_version,
                 source_operation_id, connection_id, status, trust_level, priority,
                 workspace_predicate, input_transform_ref, output_transform_ref,
                 source_schema_digest, consequence_override, health,
                 fallback_policy, created_from, reviewed_by
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
               ON CONFLICT (tenant_id, binding_id) DO UPDATE SET
                 capability_id=EXCLUDED.capability_id,
                 capability_version=EXCLUDED.capability_version,
                 source_operation_id=EXCLUDED.source_operation_id,
                 connection_id=EXCLUDED.connection_id, status=EXCLUDED.status,
                 trust_level=EXCLUDED.trust_level, priority=EXCLUDED.priority,
                 workspace_predicate=EXCLUDED.workspace_predicate,
                 input_transform_ref=EXCLUDED.input_transform_ref,
                 output_transform_ref=EXCLUDED.output_transform_ref,
                 source_schema_digest=EXCLUDED.source_schema_digest,
                 consequence_override=EXCLUDED.consequence_override,
                 health=EXCLUDED.health, fallback_policy=EXCLUDED.fallback_policy,
                 created_from=EXCLUDED.created_from, reviewed_by=EXCLUDED.reviewed_by,
                 updated_at=now()""",
            binding.binding_id, binding.tenant_id, binding.capability_id,
            binding.capability_version, binding.source_operation_id,
            binding.connection_id, binding.status, binding.trust_level,
            binding.priority, binding.workspace_predicate,
            binding.input_transform_ref, binding.output_transform_ref,
            binding.source_schema_digest, binding.consequence_override,
            binding.health, binding.fallback_policy, binding.created_from,
            binding.reviewed_by,
        )

    async def list_capability_bindings(
        self, tenant_id, capability_id=None, *, source_operation_id=None
    ):
        rows = await self._pool.fetch(
            """SELECT * FROM capability_bindings
               WHERE tenant_id=$1
                 AND ($2::text IS NULL OR capability_id=$2)
                 AND ($3::text IS NULL OR source_operation_id=$3)
               ORDER BY priority, binding_id""",
            tenant_id, capability_id, source_operation_id,
        )
        return [_capability_binding(row) for row in rows]

    async def upsert_routing_policy(self, policy):
        await self._pool.execute(
            """INSERT INTO routing_policies (
                 id, tenant_id, capability_id, binding_id, operation_class,
                 capability_version, scope, workspace_id, precedence
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 capability_id=EXCLUDED.capability_id,
                 binding_id=EXCLUDED.binding_id,
                 operation_class=EXCLUDED.operation_class,
                 capability_version=EXCLUDED.capability_version,
                 scope=EXCLUDED.scope, workspace_id=EXCLUDED.workspace_id,
                 precedence=EXCLUDED.precedence, updated_at=now()""",
            policy.id, policy.tenant_id, policy.capability_id, policy.binding_id,
            policy.operation_class, policy.capability_version, policy.scope,
            policy.workspace_id, policy.precedence,
        )

    async def list_routing_policies(self, tenant_id, capability_id=None):
        rows = await self._pool.fetch(
            """SELECT * FROM routing_policies
               WHERE tenant_id=$1 AND ($2::text IS NULL OR capability_id=$2)
               ORDER BY precedence, id""",
            tenant_id, capability_id,
        )
        return [_routing_policy(row) for row in rows]
