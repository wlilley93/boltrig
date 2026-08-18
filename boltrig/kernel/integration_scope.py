"""Which integration connection serves this caller.

Precedence is the caller's OWN connection, then the org's -- the same shape
``resolve_ai_key`` uses for AI provider keys, and gated the same way: an org that
has not set ``allow_own_integration_credentials`` has its members' personal
connections skipped ENTIRELY rather than quietly honoured. That matters for
revocation: turning the policy off is sufficient on its own, with no need to hunt
down and delete rows.

Kept out of ``credentials.py`` for two reasons. That file sits at 343 lines
against the 400-line structural cap and this would eat half its remaining
headroom; and "whose credential is this" is a genuinely separate question from
"how is the material fetched", which is what the rest of that file answers.
"""

from __future__ import annotations

from typing import Any

from boltrig.models.integrations import IntegrationConnection


async def pick_connection(
    store: Any, tenant_id: str, adapter_id: str, owner: str | None
) -> IntegrationConnection | None:
    """The active connection that applies to ``owner``, or ``None`` if there is none."""
    applicable = await store.list_applicable_integration_connections_for_adapter(
        tenant_id, adapter_id, owner
    )
    org_row = next((row for row in applicable if row.level == "org"), None)
    own_row = next((row for row in applicable if row.level == "user"), None)
    if own_row is None:
        return org_row
    # The policy read costs a second query, so it happens ONLY once a personal
    # connection actually exists. A tenant that does not use them therefore pays
    # exactly what it paid before scoping: one query per dispatch, which matters
    # because this runs on every adapter call rather than once per turn the way
    # AI-key resolution does.
    org = await store.get_org(tenant_id)
    if org is not None and org.allow_own_integration_credentials:
        return own_row
    return org_row


def scope_of(connection: IntegrationConnection | None, tenant_id: str) -> tuple[str, str]:
    """The scope a credential read should be fenced against.

    ``None`` means the id came from the env/manifest binding rather than a
    connection row, and that binding is org-wide by construction -- so it answers
    for the org, whose scope_id is the tenant id.
    """
    if connection is None:
        return "org", tenant_id
    return connection.level, connection.scope_id


def acting_owner(context: Any) -> str:
    """Who this call is really being made by.

    ``on_behalf_of`` names the human an AGENT is acting for and is None when a
    person is acting for themselves, so reading it alone would attribute every
    console click to nobody. ``actor`` carries the user id in that case.

    THIS MUST MATCH what dispatch hands to ``resolve_for_adapter`` as ``owner``
    (boltrig/kernel/dispatch.py, in ``_execute_adapter``). If setup seals a
    credential under one identity and dispatch looks it up under another, the
    connection simply never resolves and the org credential serves instead --
    silently. ``tests/security/test_integration_scope.py`` pins the two together
    so the pair cannot drift.
    """
    return str(context.on_behalf_of or context.actor or "")
