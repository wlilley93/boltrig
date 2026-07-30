"""Secret-free birth-profile identities and desired/observed projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from boltrig.models import (
    BIRTH_PROFILE_MAX_TTL_SECONDS,
    BirthProfileReceipt,
    utcnow,
)

from .birth_profile_projection import birth_profile_view

DEFAULT_BIRTH_PROFILE_TTL_SECONDS = 300
MIN_BIRTH_PROFILE_TTL_SECONDS = 30
_BOOT_PID = os.getpid()
_BOOT_TOKEN = secrets.token_hex(32)


def _canonical(value: Any) -> Any:
    """Convert typed composition data to stable JSON solely for hashing.

    The canonical tree is never persisted, logged or returned.  Consequently
    manifest URLs, paths, role mappings and credential references influence the
    opaque generation without entering a receipt or becoming API data.
    """

    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def _digest(prefix: str, value: Any) -> str:
    canonical = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return prefix + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def manifest_generation(manifest: Any) -> str:
    """Opaque generation of the effective typed manifest or default posture."""

    return _digest("mf_", {"schema": "birth-manifest-v1", "manifest": manifest})


def addon_set_identity(addons: Sequence[Any]) -> str:
    """Digest only stable add-on names and versions, never harness/config data."""

    identities = sorted((str(addon.name), str(addon.version)) for addon in addons)
    return _digest("as_", {"schema": "addon-set-v1", "addons": identities})


def codex_provider_identity(
    codex_config: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Return the safe configured/off provider identity."""

    if codex_config is None:
        return "cp_off_v1", "off"
    identity = codex_config.get("receipt_identity")
    if isinstance(identity, str) and identity.startswith("cp_"):
        return identity, "configured"
    provider = codex_config.get("provider")
    return (
        _digest(
            "cp_",
            {
                "schema": "trusted-codex-fallback-v1",
                "trusted": bool(codex_config.get("trusted")),
                "provider_type": (
                    None
                    if provider is None
                    else f"{type(provider).__module__}.{type(provider).__qualname__}"
                ),
            },
        ),
        "configured",
    )


def sensitive_role_identity(
    sensitive_endpoint_id: str | None,
) -> tuple[str, str]:
    """Digest the selected endpoint id without returning the id itself."""

    if sensitive_endpoint_id is None:
        return "sr_absent_v1", "absent"
    return (
        _digest(
            "sr_",
            {
                "schema": "sensitive-role-v1",
                "endpoint_id": sensitive_endpoint_id,
            },
        ),
        "configured",
    )


def instance_identity(process_kind: str, boot_identity_token: str | None = None) -> str:
    """Return an opaque per-boot identity without hashing host metadata."""

    global _BOOT_PID, _BOOT_TOKEN
    process_id = os.getpid()
    if process_id != _BOOT_PID:
        # A pre-fork server inherits module state.  Rotate in the child so two
        # workers cannot publish the same boot identity.
        _BOOT_PID = process_id
        _BOOT_TOKEN = secrets.token_hex(32)
    token = boot_identity_token or _BOOT_TOKEN
    return _digest(
        "bi_",
        {
            "schema": "birth-instance-v2",
            "process_kind": process_kind,
            "boot_token": token,
        },
    )


def birth_profile_ttl_seconds(raw: str | None = None) -> int:
    """Bound startup evidence freshness; expiry never becomes a heartbeat."""

    value = raw
    if value is None:
        value = os.environ.get("BOLTRIG_BIRTH_PROFILE_TTL_SECONDS")
    try:
        parsed = int(value) if value is not None else DEFAULT_BIRTH_PROFILE_TTL_SECONDS
    except (TypeError, ValueError):
        parsed = DEFAULT_BIRTH_PROFILE_TTL_SECONDS
    return max(
        MIN_BIRTH_PROFILE_TTL_SECONDS,
        min(parsed, BIRTH_PROFILE_MAX_TTL_SECONDS),
    )


def make_birth_profile_receipt(
    *,
    tenant_id: str,
    process_kind: str,
    manifest: Any,
    addons: Sequence[Any],
    codex_config: Mapping[str, Any] | None,
    sensitive_endpoint_id: str | None,
    boot_identity_token: str | None = None,
    observed_at: datetime | None = None,
    ttl_seconds: int | None = None,
) -> BirthProfileReceipt:
    """Construct one bounded receipt containing opaque identities only."""

    observed = observed_at or utcnow()
    ttl = birth_profile_ttl_seconds(None if ttl_seconds is None else str(ttl_seconds))
    codex_identity, codex_state = codex_provider_identity(codex_config)
    sensitive_identity, sensitive_state = sensitive_role_identity(sensitive_endpoint_id)
    return BirthProfileReceipt(
        tenant_id=tenant_id,
        process_kind=process_kind,
        instance_identity=instance_identity(process_kind, boot_identity_token),
        manifest_generation=manifest_generation(manifest),
        addon_set_identity=addon_set_identity(addons),
        codex_provider_identity=codex_identity,
        codex_provider_state=codex_state,
        sensitive_role_identity=sensitive_identity,
        sensitive_role_state=sensitive_state,
        observed_at=observed,
        expires_at=observed + timedelta(seconds=ttl),
    )


async def record_birth_profile_startup(
    store: Any,
    **kwargs: Any,
) -> BirthProfileReceipt:
    """Persist one process-kind startup snapshot; callers own failure policy."""

    receipt = make_birth_profile_receipt(**kwargs)
    await store.upsert_birth_profile_receipt(receipt)
    return receipt


__all__ = [
    "DEFAULT_BIRTH_PROFILE_TTL_SECONDS",
    "MIN_BIRTH_PROFILE_TTL_SECONDS",
    "addon_set_identity",
    "birth_profile_ttl_seconds",
    "birth_profile_view",
    "codex_provider_identity",
    "instance_identity",
    "make_birth_profile_receipt",
    "manifest_generation",
    "record_birth_profile_startup",
    "sensitive_role_identity",
]
