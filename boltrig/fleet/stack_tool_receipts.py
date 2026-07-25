"""Authenticated, expiring Redis receipts for fleet-owned tool health.

Receipts contain only coarse component states.  Their Redis keys are scoped by
a secret deployment namespace, and their canonical payload binds the tenant and
is HMAC-authenticated with a purpose-derived deployment key.  Consequently a
service with ordinary Redis access cannot forge or copy healthy evidence across
deployments or tenants.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import time
from collections.abc import Mapping

_RECEIPT_SCHEMA = 1
_RECEIPT_PREFIX = "boltrig:readiness:stack-tools:v1"
_FLEET_TOOL_IDS = frozenset({"browser-cli"})
_MAX_RECEIPT_BYTES = 4096
_CLOCK_SKEW_SECONDS = 5.0


def receipt_signing_key(env: Mapping[str, str]) -> bytes | None:
    """Derive a purpose-separated receipt key from the deployment audit key."""
    # [2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001 O3. Blank was the only
    # rejected value, so a PLACEHOLDER key (the string .env.example ships) yielded
    # a perfectly well-formed signing key and readiness receipts were signed with
    # a public constant - a receipt anyone with this repository could forge, which
    # is indistinguishable from no receipt at all. Reject every placeholder, not
    # just the empty string.
    from boltrig.config.weak_secrets import is_placeholder_secret

    raw = str(env.get("BOLTRIG_AUDIT_HMAC_KEY") or "").strip()
    if is_placeholder_secret(raw):
        return None
    return hmac.new(
        raw.encode("utf-8"),
        b"boltrig/stack-tool-readiness/signing/v1",
        hashlib.sha256,
    ).digest()


def _receipt_key(tenant_id: str, signing_key: bytes) -> str:
    """Build a secret deployment namespace and opaque tenant-specific key."""
    namespace = hmac.new(
        signing_key,
        b"boltrig/stack-tool-readiness/namespace/v1",
        hashlib.sha256,
    ).hexdigest()[:32]
    tenant_hash = hmac.new(
        signing_key,
        b"tenant\x00" + tenant_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{_RECEIPT_PREFIX}:{namespace}:{tenant_hash}"


def _canonical_receipt(body: Mapping[str, object]) -> bytes:
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _receipt_context(tenant_id: str, signing_key: bytes) -> str:
    """Opaque tenant binding so signed evidence cannot cross tenant keys."""
    return hmac.new(
        signing_key,
        b"boltrig/stack-tool-readiness/context/v1\x00" + tenant_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _receipt_payload(
    statuses: Mapping[str, bool],
    signing_key: bytes,
    tenant_id: str,
    now: float | None = None,
) -> str:
    body: dict[str, object] = {
        "schema": _RECEIPT_SCHEMA,
        "context": _receipt_context(tenant_id, signing_key),
        "checked_at": time.time() if now is None else now,
        "components": {
            tool_id: "ok" if statuses.get(tool_id) else "failed"
            for tool_id in sorted(_FLEET_TOOL_IDS)
        },
    }
    mac = hmac.new(
        signing_key,
        b"boltrig/stack-tool-readiness/receipt/v1\x00" + _canonical_receipt(body),
        hashlib.sha256,
    ).hexdigest()
    return json.dumps({**body, "mac": mac}, separators=(",", ":"), sort_keys=True)


def _parse_receipt(raw: bytes | str | None) -> Mapping[str, object] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        if len(raw) > _MAX_RECEIPT_BYTES:
            return {}
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    elif len(raw.encode("utf-8")) > _MAX_RECEIPT_BYTES:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _authenticated_body(
    payload: Mapping[str, object], signing_key: bytes, tenant_id: str
) -> Mapping[str, object] | None:
    if set(payload) != {"schema", "context", "checked_at", "components", "mac"}:
        return None
    mac = payload.get("mac")
    if not isinstance(mac, str):
        return None
    body = {
        "schema": payload.get("schema"),
        "context": payload.get("context"),
        "checked_at": payload.get("checked_at"),
        "components": payload.get("components"),
    }
    expected_mac = hmac.new(
        signing_key,
        b"boltrig/stack-tool-readiness/receipt/v1\x00" + _canonical_receipt(body),
        hashlib.sha256,
    ).hexdigest()
    context = payload.get("context")
    if not hmac.compare_digest(mac, expected_mac):
        return None
    if not isinstance(context, str) or not hmac.compare_digest(
        context, _receipt_context(tenant_id, signing_key)
    ):
        return None
    return body


def validate_fleet_tool_receipt(
    raw: bytes | str | None,
    *,
    max_age_s: float,
    signing_key: bytes,
    tenant_id: str,
    now: float | None = None,
) -> tuple[bool, str]:
    """Validate authentication, context, schema, freshness, and tool results."""
    payload = _parse_receipt(raw)
    if payload is None:
        return False, "missing"
    if not payload:
        return False, "malformed"
    body = _authenticated_body(payload, signing_key, tenant_id)
    if body is None:
        return False, "unauthenticated"
    if body.get("schema") != _RECEIPT_SCHEMA:
        return False, "malformed"
    checked_at = body.get("checked_at")
    if not isinstance(checked_at, (int, float)) or not math.isfinite(checked_at):
        return False, "malformed"
    current = time.time() if now is None else now
    age = current - float(checked_at)
    if age < -_CLOCK_SKEW_SECONDS:
        return False, "future"
    if age > max_age_s:
        return False, "stale"
    components = body.get("components")
    if not isinstance(components, Mapping):
        return False, "malformed"
    if not _FLEET_TOOL_IDS <= components.keys():
        return False, "malformed"
    if any(components[tool_id] != "ok" for tool_id in _FLEET_TOOL_IDS):
        return False, "degraded"
    return True, "ok"


async def publish_fleet_tool_receipt(
    redis_url: str,
    tenant_id: str,
    statuses: Mapping[str, bool],
    *,
    ttl_s: float,
    timeout_s: float,
    signing_key: bytes,
) -> None:
    """Publish one expiring receipt; Redis connection details stay internal."""
    from redis.asyncio import Redis

    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=timeout_s,
        socket_timeout=timeout_s,
    )
    try:
        await asyncio.wait_for(
            client.set(
                _receipt_key(tenant_id, signing_key),
                _receipt_payload(statuses, signing_key, tenant_id),
                ex=max(1, math.ceil(ttl_s)),
            ),
            timeout=timeout_s,
        )
    finally:
        await client.aclose()


async def read_fleet_tool_receipt(
    redis_url: str,
    tenant_id: str,
    timeout_s: float,
    max_age_s: float,
    signing_key: bytes,
) -> tuple[bool, str]:
    """Read and validate the latest fleet-owned receipt."""
    from redis.asyncio import Redis

    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=timeout_s,
        socket_timeout=timeout_s,
    )
    try:
        raw = await asyncio.wait_for(
            client.get(_receipt_key(tenant_id, signing_key)), timeout=timeout_s
        )
    except Exception:
        return False, "unavailable"
    finally:
        await client.aclose()
    return validate_fleet_tool_receipt(
        raw,
        max_age_s=max_age_s,
        signing_key=signing_key,
        tenant_id=tenant_id,
    )
