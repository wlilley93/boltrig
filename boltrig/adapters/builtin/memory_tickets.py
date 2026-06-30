"""A self-contained in-memory ticketing adapter (source = 'builtin').

Implements the ``ticket`` noun with create/read verbs against an in-process
dict. It needs no credentials and no network, so it works air-gapped and is the
reference an integration test exercises end-to-end through the kernel. Real
ticketing (Jira/Linear/Monday) lives in the generated/manual adapter library.
"""

from __future__ import annotations

import uuid
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.models import InvocationContext

_TICKET_OUT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "string"},
    },
    "required": ["id"],
}


class MemoryTicketAdapter:
    id = "memory-tickets"
    version = "1.0.0"
    runtime = "script"

    def __init__(self) -> None:
        self._tickets: dict[str, dict[str, Any]] = {}
        self._fail = False  # flip to simulate a backend outage (degraded mode tests)

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="ticket.create",
                noun_id="ticket",
                input_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
                output_schema=_TICKET_OUT,
                consequence="low",
                description="Create a ticket",
                rate_limit={"per": "minute", "max": 120, "scope": "tenant"},
                degraded_mode={"strategy": "queue_for_sync", "output": {"id": "deferred"}},
            ),
            VerbSpec(
                verb_id="ticket.read",
                noun_id="ticket",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                output_schema=_TICKET_OUT,
                consequence="low",
                description="Read a ticket",
            ),
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if self._fail:
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "backend down", retryable=True)
            )
        if verb == "ticket.create":
            tid = uuid.uuid4().hex[:8]
            rec = {"id": tid, "title": params["title"], "status": "open"}
            self._tickets[tid] = rec
            return Result.success(rec)
        if verb == "ticket.read":
            rec = self._tickets.get(params["id"])
            if rec is None:
                return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "no such ticket"))
            return Result.success(rec)
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return "down" if self._fail else "ok"


def build() -> MemoryTicketAdapter:
    return MemoryTicketAdapter()
