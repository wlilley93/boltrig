"""Opaque record references and their provenance (SPEC §3, §7.D, doctrine step 3).

A fan-out read merges records from several connections into one answer. The
model must then be able to say "update THAT one" without ever having seen a
HubSpot id, a Pipedrive id or a provider prefix. That is what a ``brref`` is:

    brref_contact_k3mq7ayt2xr

kernel-issued, opaque, and resolving internally to the connection, provider,
remote object type, remote record id, binding, capability version and tenant
or workspace scope the record came from.

WHY THE REF IS MINTED RANDOM AND STORED, NOT DERIVED
----------------------------------------------------
The obvious design is a digest over ``(tenant, connection, remote_id)``, which
gets determinism for free. It also builds a confirmation oracle: anyone holding
a ref who can guess the tuple can verify the guess offline, so a ref leaked
into a log stops being opaque. A keyed digest closes that and buys a key to
manage, and ``boltrig/kernel/audit.py`` records what that costs in practice -
its key shipped as a public constant in ``.env.example`` and a live tenant ran
on it, so the chain was forgeable by anyone with the repo.

There is no need for either here. Determinism is a property of the STORE, not
of the derivation: the identity tuple carries a unique index, so re-observing a
record returns the ref already minted for it. That gives a stable ref across
turns, no key, and nothing to confirm offline.

The security boundary is likewise not the ref's shape. Resolution is always
scoped ``WHERE tenant_id = $1 AND ref = $2``, so a forged or cross-tenant ref
resolves to nothing rather than to someone else's record. The randomness only
stops the reference space from being enumerable.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from .base import TenantId, utcnow

REF_PREFIX = "brref"

# 56 bits of randomness, base32 without padding. The doctrine's worked example
# shows a five-character tail; five characters is illustrative rather than
# sufficient, because refs are minted per record per tenant and a birthday
# collision inside one tenant's contact book is a record pointing at the wrong
# remote object. The unique index below makes a collision an error rather than
# a silent mis-resolution, but the width is what keeps it from being routine.
_RANDOM_BYTES = 7

# The entity type travels in the ref because it is CANONICAL vocabulary
# (contact, company, deal), not provider vocabulary. It tells a reader what
# kind of thing the ref denotes without disclosing where it lives.
_ENTITY_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_REF = re.compile(rf"^{REF_PREFIX}_([a-z][a-z0-9_]{{0,39}})_([a-z2-7]{{8,}})$")


def _b32(raw: bytes) -> str:
    import base64

    return base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def mint_ref(entity_type: str) -> str:
    """Mint an unused opaque reference for a canonical entity type.

    Callers persist the result through :class:`EntityProvenance`; a ref that
    was never stored resolves to nothing, which is the intended behaviour for
    a fabricated one.
    """
    if not _ENTITY_TYPE.match(entity_type or ""):
        raise ValueError(f"entity type is not canonical vocabulary: {entity_type!r}")
    return f"{REF_PREFIX}_{entity_type}_{_b32(secrets.token_bytes(_RANDOM_BYTES))}"


def is_ref(value: object) -> bool:
    """Whether a value LOOKS like a kernel-issued reference.

    Shape only, and the distinction is load-bearing: this says nothing about
    whether the ref exists, belongs to this tenant, or points anywhere.
    ``ProvenanceStoreContract.resolve_entity_ref`` is the only thing that
    answers those, and it is what a caller must reach for. A True here is never
    authorisation to skip that lookup.
    """
    return isinstance(value, str) and _REF.match(value) is not None


def ref_entity_type(value: str) -> str | None:
    """The canonical entity type carried by a well-formed ref, else None."""
    match = _REF.match(value or "")
    return match.group(1) if match else None


@dataclass(frozen=True)
class EntityObservation:
    """A record a read just returned, BEFORE it has a name.

    Separate from :class:`EntityProvenance` so a caller cannot hold a ref the
    store did not issue. The store mints on insert and returns the effective
    row, so where a record was seen before the caller gets the ref already in
    play rather than a fresh one it proposed and the store discarded.
    """

    entity_type: str
    connection_id: str
    provider: str
    remote_object_type: str
    remote_record_id: str
    capability_id: str
    capability_version: int = 1
    binding_id: str | None = None
    workspace_id: str | None = None

    def issue(self, tenant_id: str) -> "EntityProvenance":
        """Mint this observation a ref. Called by the store, not by callers."""
        return EntityProvenance(
            ref=mint_ref(self.entity_type),
            tenant_id=tenant_id,
            entity_type=self.entity_type,
            connection_id=self.connection_id,
            provider=self.provider,
            remote_object_type=self.remote_object_type,
            remote_record_id=self.remote_record_id,
            capability_id=self.capability_id,
            capability_version=self.capability_version,
            binding_id=self.binding_id,
            workspace_id=self.workspace_id,
        )


@dataclass
class EntityProvenance:
    """Where one record came from, and how to reach it again (SPEC §3).

    ``capability_version`` is the doctrine's "binding version": the contract
    the record was READ under. An update that follows this provenance is
    therefore routed back not merely to the same connection but to the same
    capability contract, which is what stops a follow-up write being shaped by
    a contract the record never passed through.
    """

    ref: str
    tenant_id: TenantId
    entity_type: str
    connection_id: str
    provider: str
    remote_object_type: str
    remote_record_id: str
    capability_id: str
    capability_version: int = 1
    binding_id: str | None = None
    workspace_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    last_seen_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not is_ref(self.ref):
            raise ValueError(f"malformed record reference: {self.ref!r}")
        if ref_entity_type(self.ref) != self.entity_type:
            # A ref whose embedded type disagrees with its row is a ref that
            # would describe itself one way and resolve another.
            raise ValueError("record reference entity type disagrees with its provenance")
        if not self.remote_record_id:
            raise ValueError("provenance needs a remote record id to be reachable")

    def origin(self, connection_label: str) -> dict[str, str]:
        """The origin as the model is allowed to see it (SPEC §3).

        Label only. The connection id, provider, remote object type and remote
        record id stay kernel-side: naming the provider in the tool surface is
        exactly what the doctrine removes, and the label is the part a human
        recognises in a confirmation prompt.

        The label is PASSED IN rather than stored on the row. It belongs to the
        connection and a user can rename one, so a copy here would be a second
        version of the truth that goes stale silently. Callers merging a
        fan-out already hold the connection map the resolver loaded.
        """
        return {"connection_label": connection_label or self.connection_id}
