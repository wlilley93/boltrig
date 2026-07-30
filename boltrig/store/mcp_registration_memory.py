"""Atomic in-memory amendment of an external-MCP registration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from boltrig.models import AdapterHealth

from .mcp_lifecycle_codec import copy_lifecycle
from .mcp_lifecycle_contract import (
    McpCredentialAmendment,
    McpRegistrationAmendResult,
    mcp_credential_config_digest,
    mcp_registration_spec_digest,
)
from .sealing import seal_ref, unseal_ref


@dataclass(frozen=True)
class MemoryRegistrationExpectation:
    state: str
    created_at: datetime
    updated_at: datetime
    spec_digest: str
    credential_config_digest: str | None
    config_revision: int
    changed_at: datetime


def _registration_matches(previous, adapter, expected) -> bool:
    return (
        previous.state == expected.state
        and previous.created_at == expected.created_at
        and previous.updated_at == expected.updated_at
        and previous.config_revision == expected.config_revision
        and mcp_registration_spec_digest(adapter.spec_ref) == expected.spec_digest
    )


def _credential_digest(store, tenant_id, credential_id) -> str | None:
    row = (
        None
        if credential_id is None
        else store._creds.get((tenant_id, credential_id))
    )
    metadata = None if row is None else unseal_ref(row)
    return mcp_credential_config_digest(metadata)


async def amend_registration(
    store,
    tenant_id: str,
    server_id: str,
    expected: MemoryRegistrationExpectation,
    spec_ref: str,
    amendment: McpCredentialAmendment,
):
    adapter = store._require_mcp_adapter(tenant_id, server_id)
    key = (tenant_id, server_id)
    previous = store._mcp_lifecycles.get(key)
    if previous is None:
        raise LookupError("MCP lifecycle not found")
    if not _registration_matches(previous, adapter, expected):
        return None
    previous_id = store._effective_mcp_credential_id(
        tenant_id, server_id, adapter.spec_ref
    )
    if (
        _credential_digest(store, tenant_id, previous_id)
        != expected.credential_config_digest
    ):
        return None
    current_id = store._validate_credential_amendment(
        tenant_id,
        previous_credential_id=previous_id,
        replacement_spec_ref=spec_ref,
        amendment=amendment,
    )
    if amendment.mode == "replace":
        assert current_id is not None
        assert amendment.credential_metadata is not None
        store._creds[(tenant_id, current_id)] = seal_ref(
            dict(amendment.credential_metadata)
        )
    updated_adapter = replace(
        adapter,
        spec_ref=spec_ref,
        health=AdapterHealth.UNKNOWN,
        activated=False,
    )
    updated_lifecycle = replace(
        previous,
        config_revision=previous.config_revision + 1,
        last_known_tools=(),
        tools_observed_at=None,
        updated_at=expected.changed_at,
    )
    store._adapters[key] = updated_adapter
    store._mcp_lifecycles[key] = updated_lifecycle
    for probe_key in tuple(store._mcp_probe_receipts):
        if probe_key[:2] == key:
            del store._mcp_probe_receipts[probe_key]
    return McpRegistrationAmendResult(
        replace(updated_adapter),
        copy_lifecycle(updated_lifecycle),
        current_id,
    )


__all__ = ["MemoryRegistrationExpectation", "amend_registration"]
