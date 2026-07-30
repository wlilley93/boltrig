"""Provider-spec resolution for the severed channel gateway."""

from __future__ import annotations

import hashlib
import json

from boltrig.models.channel_providers import provider_for


GATEWAY_OWNER_LEASE_SECONDS = 45
OBSERVED_STATES = frozenset(
    {
        "pending",
        "provisioning",
        "ready",
        "degraded",
        "needs_action",
        "stopping",
        "stopped",
    }
)


def channel_desired_revision(channel, credential_row: dict | None) -> str:
    """Return a secret-free desired-state digest for convergence evidence."""
    credential_shape: dict = {
        "credential_ref_id": channel.credential_ref,
        "keys": [],
        "legacy_inline": False,
    }
    if isinstance(credential_row, dict):
        credential_shape["keys"] = sorted(
            str(key)
            for key, value in dict(credential_row.get("refs") or {}).items()
            if isinstance(value, dict) and value.get("ref")
        )
        if not credential_shape["keys"] and credential_row.get("ref"):
            credential_shape["keys"] = ["signing"]
        elif not credential_shape["keys"] and credential_row.get("secret"):
            credential_shape["keys"] = ["signing"]
            credential_shape["legacy_inline"] = True
    canonical = json.dumps(
        {
            "id": channel.id,
            "platform": channel.platform,
            "enabled": channel.enabled,
            "config": channel.config,
            "credentials": credential_shape,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def resolved_gateway_spec(kernel, channel) -> dict:
    """Resolve one owner-only provider spec without persisting its material."""
    credential_row = (
        await kernel.store.get_credential_ref(
            channel.tenant_id, channel.credential_ref
        )
        if channel.credential_ref
        else None
    )
    revision = channel_desired_revision(channel, credential_row)
    refs: dict = {}
    legacy_secret = None
    if isinstance(credential_row, dict):
        refs = dict(credential_row.get("refs") or {})
        if credential_row.get("kind") != "channel_credentials_v1":
            if credential_row.get("ref"):
                refs = {"signing": credential_row}
            else:
                legacy_secret = credential_row.get("secret")
    values = await _resolve_credential_values(kernel, refs)
    if values is None:
        return _unresolved(channel, revision, "credential_reference_unresolved")
    if legacy_secret:
        values["signing"] = str(legacy_secret)
    try:
        provider = provider_for(channel.platform)
    except ValueError:
        return _unresolved(channel, revision, "provider_unsupported")
    if any(not values.get(key) for key in provider.credential_keys):
        return _unresolved(channel, revision, "credential_reference_incomplete")
    provider_config = dict((channel.config or {}).get("provider") or {})
    return {
        "channel_id": channel.id,
        "platform": channel.platform,
        "revision": revision,
        "state": "configured",
        "secret": values["signing"],
        "config": {
            **provider_config,
            **{key: value for key, value in values.items() if key != "signing"},
        },
        "activation": provider.activation,
    }


async def _resolve_credential_values(kernel, refs: dict) -> dict[str, str] | None:
    values: dict[str, str] = {}
    try:
        for key, ref in refs.items():
            if not isinstance(ref, dict) or not ref.get("ref"):
                return None
            material = await kernel.credentials.fetch_material(ref)
            value = (
                material.get(key)
                or material.get("secret")
                or material.get("token")
                or material.get("value")
            )
            if value is None:
                return None
            values[str(key)] = str(value)
    except Exception:
        return None
    return values


def _unresolved(channel, revision: str, reason_code: str) -> dict:
    return {
        "channel_id": channel.id,
        "platform": channel.platform,
        "revision": revision,
        "state": "needs_action",
        "reason_code": reason_code,
    }


__all__ = [
    "GATEWAY_OWNER_LEASE_SECONDS",
    "OBSERVED_STATES",
    "channel_desired_revision",
    "resolved_gateway_spec",
]
