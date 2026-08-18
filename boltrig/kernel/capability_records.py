"""Writing the capability doctrine's routing records at registration.

Split out of kernel/registry.py, which crossed the 400-line ceiling when these
came in with the merge. A real seam rather than a line drawn to satisfy a limit:
registry.py's job is publishing nouns, verbs and bindings, and this file's is
recording what an adapter CLAIMS to implement. The registry calls in here;
nothing in here calls back.

Module functions over an explicit ``store`` rather than methods, so the record
writing can be read and tested without constructing a registry.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from boltrig.adapters.base import Adapter
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    SourceOperation,
)
from boltrig.store import Store


def schema_digest(spec: Any) -> str:
    """A stable fingerprint of the operation's contract.

    Recorded on both the source operation and the binding that claims it, so a
    provider changing a schema under a published capability is detectable rather
    than silent - the failure mode the doctrine's catalogue revisions exist for.
    """
    payload = json.dumps(
        [spec.input_schema, spec.output_schema], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def capability_connection(
store: Store, tenant_id: str, adapter: Adapter
) -> ProviderConnection:
    """The routing identity for this adapter's operations.

    Its LABEL is the authoritative one from the catalogue connection when the
    tenant has configured one, because that is the name a confirmation prompt
    has to be able to say out loud ("Archive Alice Morgan in HubSpot - UK
    Sales?"). Absent a catalogue row the adapter id is the honest fallback.
    """
    label = adapter.id
    integration_connection_id = None
    for row in await store.list_integration_connections(tenant_id):
        if row.adapter_id == adapter.id and row.health != "revoked":
            label, integration_connection_id = row.label, row.id
            break
    connection = ProviderConnection(
        id=f"pconn:{adapter.id}",
        tenant_id=tenant_id,
        label=label,
        provider=adapter.id,
        source_type=getattr(adapter, "source_type", "native"),
        adapter_id=adapter.id,
        integration_connection_id=integration_connection_id,
        # An adapter that SHIPS INSIDE THE IMAGE is first-party; anything
        # generated, consumed or hand-authored is merely reviewed, and its
        # declared claims stay proposed until someone approves them.
        trust_level=(
            "first_party"
            if getattr(adapter, "source", "builtin") == "builtin"
            else "reviewed"
        ),
    )
    await store.upsert_provider_connection(connection)
    return connection

async def declare_capability(
store: Store, tenant_id: str, connection: ProviderConnection, spec: Any
) -> None:
    """Record one declared implementation claim.

    A FIRST-PARTY adapter's claim binds approved: it ships inside the image
    and its registration is already the governed act. Anything generated,
    consumed or hand-authored lands ``proposed`` - a declaration is evidence,
    never the authority to publish itself (SPEC §5, approval policy). An
    unapproved binding is not eligible for any route.
    """
    digest = schema_digest(spec)
    await store.upsert_source_operation(
        SourceOperation(
            id=spec.verb_id,
            tenant_id=tenant_id,
            provider=connection.provider,
            source_type=connection.source_type,
            connection_id=connection.id,
            title=spec.verb_id,
            description=spec.description,
            input_schema=spec.input_schema,
            output_schema=spec.output_schema,
            schema_digest=digest,
            consequence_hint=spec.consequence,
        )
    )
    first_party = connection.trust_level == "first_party"
    await store.upsert_capability_binding(
        CapabilityBinding(
            binding_id=f"cb:{connection.id}:{spec.verb_id}",
            tenant_id=tenant_id,
            capability_id=spec.implements,
            capability_version=spec.capability_version,
            source_operation_id=spec.verb_id,
            connection_id=connection.id,
            status="approved" if first_party else "proposed",
            trust_level=connection.trust_level,
            source_schema_digest=digest,
            created_from="declared",
        )
    )
