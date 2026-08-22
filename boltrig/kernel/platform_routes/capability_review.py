"""The capability review queue, the catalogue it feeds, and the routes it selects.

Doctrine step 6, the read half. ``control.capability_binding.approve`` and
``.reject`` landed with nothing to list, so an operator could act on a binding
only if they already knew its id: a review gate with no inbox. These are the
three reads a Capabilities / Rules / Review console needs.

WHY NOT UNDER ``/v1/capabilities``. That path is taken, and it means something
else: ``Registry.discover``'s catalogue of verbs, nouns, workflows and AGENT
capability profiles. Two different senses of the word already collide in this
codebase, and hanging the doctrine's surface off the other one's path as a
sub-resource would make the collision structural instead of merely unfortunate.

BOTH FENCES FROM THE CONNECTIONS ROUTE APPLY, and for the same reasons. A
binding names a connection, so listing bindings unfenced would disclose the
tenant's wiring, and a provider connection can descend from a member's PERSONAL
integration connection, whose ``accounts[].id`` is routinely an email address.
``visible_to`` is the ownership half, ``may_see`` the capability half, and they
are imported from ``integrations`` rather than restated: a second copy of a
disclosure fence is a copy that stops matching.

The catalogue is DERIVED, not stored. There is no capability table: a capability
exists because bindings claim it, so the list is a rollup over bindings and the
number of ways one is implemented is a count, never a column.
"""

from __future__ import annotations

from typing import Any

from boltrig.models.capability_routing import BINDING_STATUS

from ._shared import require_author
from .integrations import may_see, permitted_tools, visible_to

# The model's own vocabulary, not a restatement of it. A second list here would
# drift the moment a status is added, and the failure would be a filter that
# silently rejects a real status.
BINDING_STATUS_FILTERS = BINDING_STATUS


def _binding_view(binding, operation, connection) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "capability": binding.ref,
        "capability_id": binding.capability_id,
        "capability_version": binding.capability_version,
        "status": binding.status,
        "trust_level": binding.trust_level,
        "priority": binding.priority,
        "created_from": binding.created_from,
        "reviewed_by": binding.reviewed_by,
        "workspace_predicate": binding.workspace_predicate,
        "source_operation_id": binding.source_operation_id,
        # A reviewer is deciding whether an operation really implements a
        # canonical name, so the operation's own words are the evidence. They
        # are provider-authored text: a console renders them as data.
        "source_operation": (
            None
            if operation is None
            else {
                "id": operation.id,
                "provider": operation.provider,
                "title": operation.title,
                "description": operation.description,
                "consequence_hint": operation.consequence_hint,
            }
        ),
        # Schema drift withdraws an approval (step 4), so a reviewer needs to
        # see WHETHER the binding is pinned to the schema they are looking at.
        # Reporting the booleans rather than the digests keeps a fingerprint
        # nobody needs out of an authenticated response.
        "schema_pinned": binding.source_schema_digest is not None,
        "schema_current": (
            operation is not None
            and binding.source_schema_digest == operation.schema_digest
        ),
        "connection": (
            None
            if connection is None
            else {
                "id": connection.id,
                "label": connection.label,
                "provider": connection.provider,
                "status": connection.status,
                "health": connection.health,
                "eligible": connection.eligible,
            }
        ),
    }


async def _integration_owner_fence(kernel, tenant_id: str, viewer: str):
    """Which provider connections this caller may be told about.

    A provider connection that descends from a member's personal integration
    connection inherits that row's ownership. One with no integration row
    behind it (a native first-party door) is tenant-level and visible.
    """
    integrations = {
        row.id: row
        for row in await kernel.store.list_integration_connections(tenant_id)
    }

    def permitted(connection) -> bool:
        parent = integrations.get(connection.integration_connection_id or "")
        return parent is None or visible_to(parent, viewer)

    return permitted


async def joined_bindings(k, p, status: str | None) -> list[dict[str, Any]]:
    """Every binding this caller may see, joined to its operation and connection.

    All three reads go through here so that one fence decides visibility once.
    A catalogue or a policy list computed from an unfenced read would name a
    capability the binding list just hid, which is the same disclosure arriving
    by a side door.
    """
    viewer = str(getattr(p, "subject", "") or "")
    owned = await _integration_owner_fence(k, p.tenant_id, viewer)
    connections = {
        row.id: row
        for row in await k.store.list_provider_connections(p.tenant_id)
        if owned(row)
    }
    operations = {
        row.id: row for row in await k.store.list_source_operations(p.tenant_id)
    }
    rows = []
    for binding in await k.store.list_capability_bindings(p.tenant_id):
        if status is not None and binding.status != status:
            continue
        connection = connections.get(binding.connection_id)
        if connection is None:
            # The ownership fence refused the connection, so the binding
            # through it is not this caller's to see either.
            continue
        # The capability half, exactly the pair routing.grant_verbs demands
        # and offer_candidates filters on, so the queue cannot advertise a
        # route the dispatcher would refuse to run.
        names = permitted_tools(
            p, [binding.capability_id, binding.source_operation_id]
        )
        if not may_see(p, names):
            continue
        rows.append(_binding_view(binding, operations.get(binding.source_operation_id), connection))
    return sorted(rows, key=lambda row: (row["capability_id"], row["binding_id"]))



def register(app, P, K) -> None:
    @app.get("/v1/capability-bindings")
    async def list_capability_bindings(status: str | None = None, k=K, p=P) -> dict[str, Any]:
        require_author(p)
        if status is not None and status not in BINDING_STATUS_FILTERS:
            return {"bindings": [], "status": status, "reason": "unknown_status"}
        rows = await joined_bindings(k, p, status)
        return {
            "status": status,
            "bindings": rows,
            "needs_review": sum(1 for row in rows if row["status"] == "proposed"),
        }

    @app.get("/v1/capability-catalogue")
    async def capability_catalogue(k=K, p=P) -> dict[str, Any]:
        require_author(p)
        rows = await joined_bindings(k, p, None)
        policies = await k.store.list_routing_policies(p.tenant_id)
        by_capability: dict[str, dict[str, Any]] = {}
        for row in rows:
            entry = by_capability.setdefault(
                row["capability_id"],
                {
                    "capability_id": row["capability_id"],
                    "implementations": 0,
                    "approved": 0,
                    "needs_review": 0,
                    "providers": set(),
                    "routing_policies": 0,
                },
            )
            entry["implementations"] += 1
            if row["status"] == "approved":
                entry["approved"] += 1
            if row["status"] == "proposed":
                entry["needs_review"] += 1
            if row["connection"] is not None:
                entry["providers"].add(row["connection"]["provider"])
        for policy in policies:
            entry = by_capability.get(policy.capability_id)
            if entry is not None:
                entry["routing_policies"] += 1
        return {
            "capabilities": [
                {**entry, "providers": sorted(entry["providers"])}
                for entry in sorted(
                    by_capability.values(), key=lambda item: item["capability_id"]
                )
            ]
        }

    @app.get("/v1/routing-policies")
    async def list_routing_policies(
        capability_id: str | None = None, k=K, p=P
    ) -> dict[str, Any]:
        require_author(p)
        # Scoped to the capabilities this caller may see, through the same join
        # the other two reads use: a policy names a binding, and a policy row
        # would otherwise name a capability the binding fence just hid.
        visible = {row["capability_id"] for row in await joined_bindings(k, p, None)}
        policies = await k.store.list_routing_policies(p.tenant_id, capability_id)
        return {
            "routing_policies": [
                {
                    "id": policy.id,
                    "capability_id": policy.capability_id,
                    "binding_id": policy.binding_id,
                    "operation_class": policy.operation_class,
                    "capability_version": policy.capability_version,
                    "scope": policy.scope,
                    "workspace_id": policy.workspace_id,
                    "precedence": policy.precedence,
                }
                for policy in policies
                if policy.capability_id in visible
            ]
        }


__all__ = ["register"]
