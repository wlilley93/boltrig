"""The ``tools/list`` handler: what a run is offered, ranked and paged.

Extracted from ``mcp.py``, which sits at its size floor. The extraction is not
only bookkeeping: the handler now owns a REFUSAL as well as a result, and that
refusal is the interesting part.

An unusable cursor cannot be answered with an empty page. To a client, zero
tools and no error is indistinguishable from "this server offers you nothing" -
an agent then plans a turn with no capabilities and reports no fault, which is
the same silent-truncation shape as a consumer that never followed nextCursor.
MCP specifies -32602 for exactly this, so the handler returns a whole JSON-RPC
frame rather than a result the caller must interpret.

An EMPTY cursor is not unusable: a client that initialises the field rather than
omitting it is asking for the first page, and it gets one.
"""

from __future__ import annotations

from typing import Any

from . import tool_disclosure
from .mcp_errors import err, ok

# JSON-RPC 2.0 §5.1. Named because a bare -32602 at the call site reads as a
# magic number in a file whose whole subject is protocol conformance.
INVALID_PARAMS = -32602


async def list_tools(kernel: Any, rt: Any, rid: Any, cursor: Any = None) -> dict:
    """Granted-only, RANKED and PAGED: tenant ceiling ∩ run grants (SEC-23,
    FR-MCP-02).

    The candidate set is narrowed to the tenant ceiling here and to the run's
    own grants inside the offer, so the two authorities intersect rather than
    either one standing alone.
    """
    perms = await kernel.store.get_tenant_permissions(rt.tenant_id)
    verbs = await kernel.store.list_verbs(rt.tenant_id)
    try:
        page = tool_disclosure.offer_page(
            [verb for verb in verbs if perms.grants.permits(verb.id)],
            rt.grants,
            rt.skills,
            cursor,
        )
    except tool_disclosure.ToolDisclosureError:
        return err(rid, INVALID_PARAMS, "invalid cursor")
    return ok(rid, page)
