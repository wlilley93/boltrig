"""Bounded, filter-before-page reads for user activity and audit browsing.

These are view contracts only. Integrity verification deliberately continues
to use ``audit_scan`` / ``security_scan`` over each complete hash chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models import AuditEvent, SecurityEvent

MAX_ACCOUNT_ACTIVITY_PAGE = 50
DEFAULT_ACCOUNT_ACTIVITY_PAGE = 8
MAX_AUDIT_SEARCH_PAGE = 500
DEFAULT_AUDIT_SEARCH_PAGE = 100
MAX_AUDIT_SEARCH_OFFSET = 10_000


def bounded_page(limit: int, maximum: int) -> int:
    return max(1, min(int(limit), maximum))


def bounded_offset(offset: int) -> int:
    return max(0, min(int(offset), MAX_AUDIT_SEARCH_OFFSET))


class AuditReadContract(Protocol):
    async def account_activity_page(
        self, tenant_id: str, subject: str, *, limit: int, offset: int = 0
    ) -> tuple[list[AuditEvent], int | None]: ...

    async def audit_search_page(
        self, tenant_id: str, *, departments: list[str] | None = None,
        workspace_id: str | None = None, run_id: str | None = None,
        query: str | None = None,
        actor: str | None = None, verb: str | None = None,
        status: str | None = None, resource: str | None = None,
        since: datetime | None = None, until: datetime | None = None,
        limit: int = DEFAULT_AUDIT_SEARCH_PAGE, offset: int = 0,
    ) -> tuple[list[AuditEvent], int | None]: ...

    async def security_search_page(
        self, tenant_id: str, *, workspace_id: str | None = None,
        event_type: str | None = None, actor: str | None = None,
        resource: str | None = None, since: datetime | None = None,
        until: datetime | None = None, limit: int = DEFAULT_AUDIT_SEARCH_PAGE,
        offset: int = 0,
    ) -> tuple[list[SecurityEvent], int | None]: ...
