"""Canonical enrolled-device, root and exact-action lease records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, utcnow

DEVICE_PRESENCE = ("offline", "online", "locked", "revoked")
DEVICE_ROOT_SCOPES = ("read", "read_write")
DEVICE_LEASE_STATUSES = ("issued", "claimed", "completed", "failed", "expired")
DEVICE_LEASE_VERBS = ("device.file.read", "device.file.write", "device.command.run")


@dataclass
class DeviceEnrollment:
    id: str
    tenant_id: TenantId
    owner_id: UserId
    label: str
    authorization_code_hash: str
    expires_at: datetime
    created_at: datetime = field(default_factory=utcnow)
    consumed_at: datetime | None = None


@dataclass
class EnrolledDevice:
    id: str
    tenant_id: TenantId
    owner_id: UserId
    label: str
    public_key: str
    public_key_fingerprint: str
    lease_verify_key_id: str
    availability_mode: str = "unlocked_session"
    presence: str = "offline"
    session_token_hash: str | None = None
    session_expires_at: datetime | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class DeviceRoot:
    id: str
    tenant_id: TenantId
    device_id: str
    label: str
    scope: str
    command_enabled: bool = False
    git_enabled: bool = False
    created_at: datetime = field(default_factory=utcnow)
    revoked_at: datetime | None = None


@dataclass
class DeviceLease:
    id: str
    tenant_id: TenantId
    device_id: str
    root_id: str
    owner_id: UserId
    verb: str
    action: dict[str, Any]
    action_digest: str
    approval_id: str
    issued_at: datetime
    expires_at: datetime
    signature: str = ""
    signing_key_id: str = ""
    status: str = "issued"
    claim_token_hash: str | None = None
    claim_expires_at: datetime | None = None
    claimed_at: datetime | None = None
    settled_at: datetime | None = None
    receipt: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        """The exact JSON object signed by the kernel and verified by a device."""
        return {
            "version": 1,
            "id": self.id,
            "tenant_id": self.tenant_id,
            "device_id": self.device_id,
            "root_id": self.root_id,
            "owner_id": self.owner_id,
            "verb": self.verb,
            "action": self.action,
            "action_digest": self.action_digest,
            "approval_id": self.approval_id,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "signing_key_id": self.signing_key_id,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
