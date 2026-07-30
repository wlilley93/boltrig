"""Adapter-scoped sealing and resolution for certified integration setup."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Credential
from boltrig.models import CredentialResolution


INTEGRATION_MANUAL_SECRET_KIND = "integration_manual_secret"


def integration_manual_secret_ref(
    integration_id: str,
    adapter_id: str,
    credential_kind: str,
    contract_version: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    """Build the kernel-only value that the store envelope-seals atomically."""
    if (
        not integration_id
        or not adapter_id
        or not contract_version
        or not fields
        or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in fields.items()
        )
    ):
        raise CredentialResolution("invalid integration credential contract")
    return {
        "kind": INTEGRATION_MANUAL_SECRET_KIND,
        "integration_id": integration_id,
        "adapter_id": adapter_id,
        "credential_kind": credential_kind,
        "contract_version": contract_version,
        "fields": dict(fields),
    }


def resolve_integration_credential(
    ref: dict[str, Any], credential_id: str, adapter_id: str
) -> Credential | None:
    if ref.get("kind") != INTEGRATION_MANUAL_SECRET_KIND:
        return None
    material = ref.get("fields")
    if (
        ref.get("adapter_id") != adapter_id
        or not isinstance(material, dict)
        or not material
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in material.items()
        )
    ):
        raise CredentialResolution("integration credential reference is scope-mismatched")
    return Credential(
        id=credential_id,
        kind=str(ref.get("credential_kind") or "api_key"),
        material=dict(material),
    )


__all__ = [
    "INTEGRATION_MANUAL_SECRET_KIND",
    "integration_manual_secret_ref",
    "resolve_integration_credential",
]
