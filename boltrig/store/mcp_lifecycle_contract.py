"""Store protocol for durable external-MCP lifecycle evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal, Mapping, Protocol

from boltrig.models import (
    AdapterRecord,
    McpProbeReceipt,
    McpServerLifecycle,
    McpToolSnapshot,
)

McpCredentialMode = Literal["preserve", "replace", "remove"]
_SPEC_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_CREDENTIAL_KEYS = frozenset({"store", "ref", "kind"})


def mcp_registration_spec_digest(spec_ref: str | None) -> str:
    """Digest the exact private reconstruction spec used by registration CAS."""
    return hashlib.sha256((spec_ref or "").encode("utf-8")).hexdigest()


def mcp_credential_config_digest(
    metadata: Mapping[str, object] | None,
) -> str | None:
    """Digest the exact unsealed credential-reference configuration."""
    if metadata is None:
        return None
    encoded = json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class McpCredentialAmendment:
    """Secret-free credential-reference intent for one full MCP amendment."""

    mode: McpCredentialMode
    credential_id: str | None = None
    credential_metadata: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"preserve", "replace", "remove"}:
            raise ValueError("invalid MCP credential amendment mode")
        if self.mode != "replace":
            if self.credential_id is not None or self.credential_metadata is not None:
                raise ValueError(
                    "preserve/remove MCP credential amendments reject credential fields"
                )
            return
        if (
            not isinstance(self.credential_id, str)
            or not 1 <= len(self.credential_id) <= 256
        ):
            raise ValueError("replacement MCP credential id is invalid")
        metadata = dict(self.credential_metadata or {})
        if frozenset(metadata) != _CREDENTIAL_KEYS:
            raise ValueError(
                "replacement MCP credential metadata must contain store, ref and kind"
            )
        bounds = {"store": 128, "ref": 2048, "kind": 128}
        for key, limit in bounds.items():
            value = metadata.get(key)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError(f"replacement MCP credential {key} is invalid")
            metadata[key] = value.strip()
        object.__setattr__(
            self, "credential_metadata", MappingProxyType(metadata)
        )


@dataclass(frozen=True)
class McpRegistrationAmendResult:
    adapter: AdapterRecord
    lifecycle: McpServerLifecycle
    current_credential_id: str | None


@dataclass(frozen=True)
class McpRegistrationDeleteResult:
    server_id: str
    previous_state: str
    previous_config_revision: int
    deleted_at: datetime


def validate_mcp_registration_cas(
    *,
    expected_created_at: datetime,
    expected_updated_at: datetime,
    expected_spec_digest: str,
    expected_credential_config_digest: str | None,
    expected_config_revision: int,
    changed_at: datetime,
) -> None:
    for value, name in (
        (expected_created_at, "expected_created_at"),
        (expected_updated_at, "expected_updated_at"),
        (changed_at, "changed_at"),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
    if changed_at <= expected_updated_at:
        raise ValueError("changed_at must advance the MCP lifecycle timestamp")
    if not isinstance(expected_spec_digest, str) or not _SPEC_DIGEST.fullmatch(
        expected_spec_digest
    ):
        raise ValueError("expected MCP spec digest is invalid")
    if expected_credential_config_digest is not None and (
        not isinstance(expected_credential_config_digest, str)
        or not _SPEC_DIGEST.fullmatch(expected_credential_config_digest)
    ):
        raise ValueError("expected MCP credential config digest is invalid")
    if (
        type(expected_config_revision) is not int
        or expected_config_revision < 1
    ):
        raise ValueError("expected MCP config revision is invalid")


class McpLifecycleStoreContract(Protocol):
    async def get_mcp_server_lifecycle(
        self, tenant_id: str, server_id: str
    ) -> McpServerLifecycle | None: ...

    async def list_mcp_server_lifecycles(
        self, tenant_id: str
    ) -> list[McpServerLifecycle]: ...

    async def set_mcp_server_lifecycle(
        self,
        tenant_id: str,
        server_id: str,
        *,
        expected_state: str | None,
        expected_config_revision: int | None,
        new_state: str,
        changed_at: datetime,
        last_known_tools: tuple[McpToolSnapshot, ...] | None = None,
        tools_observed_at: datetime | None = None,
    ) -> McpServerLifecycle | None: ...

    async def record_mcp_probe_receipt(
        self,
        receipt: McpProbeReceipt,
        *,
        expected_config_revision: int,
        last_known_tools: tuple[McpToolSnapshot, ...] | None = None,
    ) -> McpProbeReceipt | None: ...

    async def get_latest_mcp_probe_receipt(
        self, tenant_id: str, server_id: str
    ) -> McpProbeReceipt | None: ...

    async def list_mcp_probe_receipts(
        self, tenant_id: str, server_id: str, limit: int = 20
    ) -> list[McpProbeReceipt]: ...

    async def amend_mcp_server_registration(
        self,
        tenant_id: str,
        server_id: str,
        *,
        expected_state: str,
        expected_created_at: datetime,
        expected_updated_at: datetime,
        expected_spec_digest: str,
        expected_credential_config_digest: str | None,
        expected_config_revision: int,
        spec_ref: str,
        changed_at: datetime,
        credential_amendment: McpCredentialAmendment,
    ) -> McpRegistrationAmendResult | None: ...

    async def delete_mcp_server_registration(
        self,
        tenant_id: str,
        server_id: str,
        *,
        expected_state: str,
        expected_created_at: datetime,
        expected_updated_at: datetime,
        expected_spec_digest: str,
        expected_credential_config_digest: str | None,
        expected_config_revision: int,
        changed_at: datetime,
    ) -> McpRegistrationDeleteResult | None: ...


__all__ = [
    "McpCredentialAmendment",
    "McpCredentialMode",
    "McpLifecycleStoreContract",
    "McpRegistrationAmendResult",
    "McpRegistrationDeleteResult",
    "mcp_credential_config_digest",
    "mcp_registration_spec_digest",
    "validate_mcp_registration_cas",
]
