"""Shared authentication, projections and audit for desktop device routes."""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta

from fastapi import Request

from boltrig.models import ActionType, AuditEvent, utcnow
from boltrig.store.postgres import set_current_tenant

from .device_crypto import (
    DeviceLeaseSigner,
    mint_scoped_token,
    parse_scoped_token,
    token_digest,
)

ENROLLMENT_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=24)
CLAIM_TTL = timedelta(minutes=5)


def signer_for(request: Request) -> DeviceLeaseSigner | None:
    return getattr(request.app.state, "device_lease_signer", None) or (
        DeviceLeaseSigner.from_environment()
    )


def bearer(request: Request) -> str | None:
    raw = request.headers.get("authorization", "")
    scheme, _, token = raw.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def authenticate_device(request: Request, kernel, device_id: str):
    token = bearer(request)
    if token is None:
        return None
    try:
        tenant_id, token_device_id = parse_scoped_token(token, "device_session")
    except ValueError:
        return None
    if token_device_id != device_id:
        return None
    set_current_tenant(tenant_id)
    try:
        device = await kernel.store.authenticate_device_session(
            tenant_id, device_id, token_digest(token)
        )
    finally:
        set_current_tenant(None)
    return device


def device_view(device, roots: list) -> dict:
    return {
        "id": device.id,
        "label": device.label,
        "public_key_fingerprint": device.public_key_fingerprint,
        "presence": device.presence,
        "availability_mode": device.availability_mode,
        "roots": [
            {
                "id": root.id,
                "label": root.label,
                "scope": root.scope,
                "command_enabled": root.command_enabled,
                "git_enabled": root.git_enabled,
            }
            for root in roots
        ],
        "last_seen_at": (
            device.last_seen_at.isoformat() if device.last_seen_at else None
        ),
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
    }


def lease_view(lease) -> dict:
    return {
        **lease.canonical_payload(),
        "signature": lease.signature,
        "status": lease.status,
    }


_RECEIPT_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def owner_lease_view(lease) -> dict:
    """Project bounded, non-authority lease state to its owning human."""
    now = utcnow()
    status = (
        "expired"
        if (
            (lease.status == "issued" and lease.expires_at < now)
            or (
                lease.status == "claimed"
                and lease.claim_expires_at is not None
                and lease.claim_expires_at < now
            )
        )
        else lease.status
    )
    return {
        "id": lease.id,
        "device_id": lease.device_id,
        "root_id": lease.root_id,
        "verb": lease.verb,
        "status": status,
        "issued_at": lease.issued_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
        "settled_at": (
            lease.settled_at.isoformat() if lease.settled_at else None
        ),
        "receipt": _owner_receipt_summary(
            lease.verb, lease.status, lease.action, lease.receipt
        ),
    }


def _owner_receipt_summary(
    verb: str, status: str, action: dict, receipt: dict | None
) -> dict | None:
    if status not in {"completed", "failed"} or not isinstance(receipt, dict):
        return None
    if status == "failed":
        code = receipt.get("code")
        return {
            "code": (
                code if isinstance(code, str) and _RECEIPT_CODE.fullmatch(code)
                else "device_reported_failure"
            )
        }
    digest = receipt.get("content_digest")
    byte_size = receipt.get("byte_size")
    if verb in {"device.file.read", "device.file.write"}:
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or not 0 <= byte_size <= 104_857_600
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            return None
        summary: dict = {
            "byte_size": byte_size,
            "content_digest": digest,
        }
        if verb == "device.file.read":
            summary["reported_local_result_available"] = (
                receipt.get("local_result_available") is True
            )
        elif isinstance(receipt.get("overwrite"), bool):
            summary["overwrite"] = receipt["overwrite"]
        return summary
    if verb == "device.file.list":
        relative_path = _safe_relative_path(
            action.get("relative_path"), optional=True
        )
        max_entries = action.get("max_entries")
        entries = _file_list_entries(
            receipt.get("entries"), relative_path, max_entries
        )
        if (
            entries is None
            or relative_path is _INVALID
            or not isinstance(receipt.get("truncated"), bool)
        ):
            return None
        return {
            "relative_path": relative_path,
            "entries": entries,
            "truncated": receipt["truncated"],
        }
    if verb == "device.command.run":
        duration = receipt.get("duration_ms")
        exit_code = receipt.get("exit_code")
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not 0 <= duration <= 300_000
            or (
                exit_code is not None
                and (
                    not isinstance(exit_code, int)
                    or isinstance(exit_code, bool)
                    or not -2_147_483_648 <= exit_code <= 2_147_483_647
                )
            )
        ):
            return None
        return {
            "duration_ms": duration,
            "exit_code": exit_code,
            "output_captured": False,
        }
    return None


_INVALID = object()


def _safe_relative_path(value: object, *, optional: bool = False):
    if value is None and optional:
        return None
    if (
        not isinstance(value, str)
        or not value
        or not _bounded_utf8(value, 1024)
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        return _INVALID
    return value


def _bounded_utf8(value: str, limit: int) -> bool:
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeEncodeError:
        return False


def _file_list_entries(
    value: object, relative_path: object, max_entries: object
) -> list[dict] | None:
    if (
        relative_path is _INVALID
        or not isinstance(max_entries, int)
        or isinstance(max_entries, bool)
        or not 1 <= max_entries <= 100
        or not isinstance(value, list)
        or len(value) > max_entries
    ):
        return None
    entries: list[dict] = []
    for raw in value:
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        path = _safe_relative_path(raw.get("path"))
        kind = raw.get("kind")
        byte_size = raw.get("byte_size")
        if (
            not isinstance(name, str)
            or not name
            or not _bounded_utf8(name, 255)
            or "/" in name
            or "\\" in name
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
            or path is _INVALID
            or kind not in {"file", "directory", "symlink"}
            or (
                byte_size is not None
                and (
                    not isinstance(byte_size, int)
                    or isinstance(byte_size, bool)
                    or not 0 <= byte_size <= 9_007_199_254_740_991
                )
            )
            or (kind == "file" and byte_size is None)
            or (kind != "file" and byte_size is not None)
            or path != (
                f"{relative_path}/{name}" if relative_path is not None else name
            )
        ):
            return None
        entries.append(
            {"name": name, "path": path, "kind": kind, "byte_size": byte_size}
        )
    return entries


async def audit_device(kernel, tenant_id: str, actor: str, verb: str, device_id: str, detail: dict):
    await kernel.audit.write(
        AuditEvent(
            tenant_id=tenant_id,
            ts=utcnow(),
            actor=actor,
            actor_tier="human" if not actor.startswith("device:") else "ephemeral",
            action_type=ActionType.TOOL_CALL,
            noun="device",
            verb=verb,
            status="ok",
            resource="device",
            resource_id=device_id,
            detail=detail,
        )
    )


def public_key_fingerprint(encoded: str) -> str:
    from .device_crypto import b64url_decode

    raw = b64url_decode(encoded)
    if len(raw) != 32:
        raise ValueError("invalid_device_public_key")
    return hashlib.sha256(raw).hexdigest()


def mint_device_session(tenant_id: str, device_id: str) -> tuple[str, str]:
    token = mint_scoped_token("device_session", tenant_id, device_id)
    return token, token_digest(token)
