"""Typed atomic idempotency contract shared by both store implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class IdempotencyClaimStatus(str, Enum):
    ACQUIRED = "acquired"
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    MISMATCH = "mismatch"
    UNCERTAIN = "uncertain"
    UNCACHEABLE = "uncacheable"


@dataclass(frozen=True)
class IdempotencyClaim:
    status: IdempotencyClaimStatus
    result: dict[str, Any] | None = None


class IdempotencyStoreContract(Protocol):
    async def idempotency_claim(
        self,
        tenant_id: str,
        key: str,
        *,
        actor: str,
        on_behalf_of: str | None,
        workspace_id: str | None,
        noun: str,
        verb: str,
        request_hash: str,
        owner_token: str,
        lease_seconds: int,
    ) -> IdempotencyClaim: ...

    async def idempotency_start(
        self, tenant_id: str, key: str, owner_token: str, lease_seconds: int
    ) -> bool: ...

    async def idempotency_release(self, tenant_id: str, key: str, owner_token: str) -> bool: ...

    async def idempotency_complete(
        self, tenant_id: str, key: str, owner_token: str, result: dict[str, Any]
    ) -> bool: ...

    async def idempotency_uncacheable(self, tenant_id: str, key: str, owner_token: str) -> bool: ...
