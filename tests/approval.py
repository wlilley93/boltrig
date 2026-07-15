"""Test helper for completing the governed HTTP approval handshake."""

from __future__ import annotations

import asyncio
from typing import Any


def approved_request(
    client: Any,
    kernel: Any,
    tenant_id: str,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    held: Any = None,
) -> Any:
    held = held or client.request(method, path, headers=headers, json=json)
    assert held.status_code == 202, held.text
    request_id = held.json()["hitl_request_id"]
    asyncio.run(kernel.hitl.answer(tenant_id, request_id, "approve", "test-reviewer"))
    return client.request(
        method,
        path,
        headers={**headers, "x-boltrig-approval-id": request_id},
        json=json,
    )
