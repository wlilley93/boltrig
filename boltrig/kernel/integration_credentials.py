"""Adapter-scoped sealing and resolution for certified integration setup."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Credential
from boltrig.models import CredentialResolution
from boltrig.models.integrations import INTEGRATION_SCOPE_LEVELS


INTEGRATION_MANUAL_SECRET_KIND = "integration_manual_secret"


def integration_manual_secret_ref(
    integration_id: str,
    adapter_id: str,
    credential_kind: str,
    contract_version: str,
    fields: dict[str, str],
    *,
    level: str,
    scope_id: str,
) -> dict[str, Any]:
    """Build the kernel-only value that the store envelope-seals atomically.

    ``level``/``scope_id`` are KEYWORD-ONLY so the existing five-positional call
    sites keep working, the same reason the model appended them rather than
    slotting them in. ``scope_id`` is not derived here -- this function has no
    tenant_id, so the caller hands it the connection's already-derived value and
    the pair cannot drift.
    """
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
    if level not in INTEGRATION_SCOPE_LEVELS or not scope_id:
        raise CredentialResolution("invalid integration credential contract")
    return {
        "kind": INTEGRATION_MANUAL_SECRET_KIND,
        "level": level,
        "scope_id": scope_id,
        "integration_id": integration_id,
        "adapter_id": adapter_id,
        "credential_kind": credential_kind,
        "contract_version": contract_version,
        "fields": dict(fields),
    }


def _scope_matches(ref: dict[str, Any], level: str, scope_id: str) -> bool:
    """Does this sealed reference belong to the scope asking for it?

    A ref with no ``level`` predates scoping and was necessarily minted by the
    org-only setup path, so it answers for the org and for nobody else. See this
    module's docstring for why absence is tolerated rather than refused.
    """
    sealed_level = ref.get("level")
    if sealed_level is None:
        return level == "org"
    return sealed_level == level and ref.get("scope_id") == scope_id


def resolve_integration_credential(
    ref: dict[str, Any],
    credential_id: str,
    adapter_id: str,
    level: str = "org",
    scope_id: str = "",
) -> Credential | None:
    if ref.get("kind") != INTEGRATION_MANUAL_SECRET_KIND:
        return None
    if ref.get("adapter_id") != adapter_id:
        raise CredentialResolution("integration credential reference is adapter-mismatched")
    if not _scope_matches(ref, level, scope_id):
        # SEPARATE from the material-shape chain on purpose: folded together, a
        # cross-scope read and a corrupt fields dict produce the same log line
        # and neither can be pinned by its own test.
        raise CredentialResolution("integration credential reference belongs to another scope")
    material = ref.get("fields")
    if (
        not isinstance(material, dict)
        or not material
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in material.items()
        )
    ):
        raise CredentialResolution("integration credential reference is malformed")
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
