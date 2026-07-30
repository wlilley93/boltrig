"""Redacted process birth-profile startup evidence.

These rows compare composition inputs across the API, standalone fleet worker
and Hatchet worker.  They are startup snapshots with a bounded expiry, never
process-heartbeat or liveness evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from .base import TenantId

BIRTH_PROFILE_PROCESS_KINDS = ("api", "fleet", "hatchet")
BIRTH_PROFILE_MAX_TTL_SECONDS = 3600
BIRTH_PROFILE_RECEIPTS_PER_PROCESS = 32
BIRTH_PROFILE_MAX_RETURNED_RECEIPTS = (
    len(BIRTH_PROFILE_PROCESS_KINDS) * BIRTH_PROFILE_RECEIPTS_PER_PROCESS
)

_INSTANCE = re.compile(r"^bi_[a-f0-9]{24}$")
_MANIFEST = re.compile(r"^mf_[a-f0-9]{24}$")
_ADDONS = re.compile(r"^as_[a-f0-9]{24}$")
_CODEX = re.compile(r"^(?:cp_off_v1|cp_[a-f0-9]{24})$")
_SENSITIVE = re.compile(r"^(?:sr_absent_v1|sr_[a-f0-9]{24})$")


@dataclass(frozen=True)
class BirthProfileReceipt:
    """One secret-free, expiring process-composition snapshot."""

    tenant_id: TenantId
    process_kind: str
    instance_identity: str
    manifest_generation: str
    addon_set_identity: str
    codex_provider_identity: str
    codex_provider_state: str
    sensitive_role_identity: str
    sensitive_role_state: str
    observed_at: datetime
    expires_at: datetime
    receipt_kind: str = "startup_snapshot"

    def __post_init__(self) -> None:
        if not str(self.tenant_id).strip():
            raise ValueError("tenant_id is required")
        if self.process_kind not in BIRTH_PROFILE_PROCESS_KINDS:
            raise ValueError("birth-profile process kind is invalid")
        if not _INSTANCE.fullmatch(self.instance_identity):
            raise ValueError("birth-profile instance identity is invalid")
        if not _MANIFEST.fullmatch(self.manifest_generation):
            raise ValueError("birth-profile manifest generation is invalid")
        if not _ADDONS.fullmatch(self.addon_set_identity):
            raise ValueError("birth-profile add-on identity is invalid")
        if not _CODEX.fullmatch(self.codex_provider_identity):
            raise ValueError("birth-profile Codex identity is invalid")
        if self.codex_provider_state not in {"off", "configured"}:
            raise ValueError("birth-profile Codex state is invalid")
        if (self.codex_provider_state == "off") != (self.codex_provider_identity == "cp_off_v1"):
            raise ValueError("birth-profile Codex identity/state disagree")
        if not _SENSITIVE.fullmatch(self.sensitive_role_identity):
            raise ValueError("birth-profile sensitive-role identity is invalid")
        if self.sensitive_role_state not in {"absent", "configured"}:
            raise ValueError("birth-profile sensitive-role state is invalid")
        if (self.sensitive_role_state == "absent") != (
            self.sensitive_role_identity == "sr_absent_v1"
        ):
            raise ValueError("birth-profile sensitive-role identity/state disagree")
        if self.receipt_kind != "startup_snapshot":
            raise ValueError("birth-profile receipt kind is invalid")
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("birth-profile timestamps must be timezone-aware")
        ttl = self.expires_at - self.observed_at
        if not timedelta(0) < ttl <= timedelta(seconds=BIRTH_PROFILE_MAX_TTL_SECONDS):
            raise ValueError("birth-profile expiry is outside the bounded window")


__all__ = [
    "BIRTH_PROFILE_MAX_TTL_SECONDS",
    "BIRTH_PROFILE_MAX_RETURNED_RECEIPTS",
    "BIRTH_PROFILE_PROCESS_KINDS",
    "BIRTH_PROFILE_RECEIPTS_PER_PROCESS",
    "BirthProfileReceipt",
]
