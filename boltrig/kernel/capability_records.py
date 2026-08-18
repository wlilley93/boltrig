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

async def record_source_operation(
store: Store, tenant_id: str, connection: ProviderConnection, spec: Any
) -> str:
    """Record WHAT A PROVIDER EXPOSES, whether or not it claims a capability.

    Split out of :func:`declare_capability`, and the split is the point. The
    two records answer different questions - "what does this provider have"
    and "what canonical capability does this operation implement" - and fusing
    them meant the first could only ever be answered for operations that had
    already answered the second. A provider's operation was invisible to the
    capability layer until someone had already mapped it, so the layer whose
    job is to GET things mapped could not see the things needing mapping.

    Measured: the Opbox door publishes 633 verbs and none of them declares
    ``implements``, so before this split it contributed exactly zero source
    operations and no compiler, review queue or mapping pack had anything to
    work on (SPEC §10 step 4).

    Returns the schema digest, so the caller can bind against the same value
    rather than recomputing it.
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
    return digest


async def declare_capability(
store: Store, tenant_id: str, connection: ProviderConnection, spec: Any
) -> None:
    """Record one declared implementation claim, and the operation behind it.

    A FIRST-PARTY adapter's claim binds approved: it ships inside the image
    and its registration is already the governed act. Anything generated,
    consumed or hand-authored lands ``proposed`` - a declaration is evidence,
    never the authority to publish itself (SPEC §5, approval policy). An
    unapproved binding is not eligible for any route.
    """
    digest = await record_source_operation(store, tenant_id, connection, spec)
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


async def apply_mapping_pack(
store: Store, tenant_id: str, connection: ProviderConnection, specs, pack
) -> int:
    """Bind a curated pack's mappings to this connection's operations (SPEC §5 level 2).

    Returns how many bindings were written.

    ALWAYS ``proposed``, whatever the connection's trust. A first-party
    connection's own ``implements`` is the provider speaking about itself and is
    already a governed act; a pack is a curator's opinion about somebody else's
    API, shipped as data. Approving that automatically would publish a
    model-callable verb on the strength of a file nobody reviewed.

    Applied BEFORE the declared claims, and sharing their ``binding_id``, so a
    level-1 declaration overwrites the level-2 guess for the same operation.
    That is the doctrine's precedence expressed as write order rather than as a
    comparison nobody would run.

    An operation the pack names but the provider does not expose is skipped in
    silence: a pack outlives the catalogue it maps, and a stale entry should
    map nothing rather than mint a binding onto an operation that is not there.
    """
    available = {spec.verb_id for spec in specs}
    written = 0
    for mapping in pack.mappings:
        if mapping.operation_id not in available:
            continue
        await store.upsert_capability_binding(
            CapabilityBinding(
                binding_id=f"cb:{connection.id}:{mapping.operation_id}",
                tenant_id=tenant_id,
                capability_id=mapping.capability_id,
                capability_version=mapping.capability_version,
                source_operation_id=mapping.operation_id,
                connection_id=connection.id,
                status="proposed",
                trust_level=connection.trust_level,
                created_from="mapping_pack",
            )
        )
        written += 1
    return written
