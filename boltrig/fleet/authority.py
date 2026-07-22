"""Whose authority a delegated run carries (SEC-164, SEC-165).

A pump work item is EXECUTED by permanent agents (the Chief of Staff routes it, a
Department Head decomposes and fans it out), but the AUTHORITY for that execution
is never the agent's and never the tenant's: it is the REQUESTING PRINCIPAL's.
This module resolves the principal a work item names (``on_behalf_of`` /
``workspace_id``) into the grants that run may use, so the delegated lane caps its
children exactly the way every direct spawn caller already does (SEC-29 test-spawn,
SEC-78 chat, SEC-139 ``POST /v1/spawn``).

Fail-closed by construction (K-13, [2026] VJS-COUNTY 5): a work item that names no
principal, or names one the store cannot identify, carries NO authority. An
unidentified principal is not a tenant-wide principal, and authority is only ever
narrowed, never widened.

The tenant permission ceiling remains the separate, independently-enforced axis it
has always been (``GrantChecker``, US-IAM-04): a verb needs BOTH the caller's grants
and the tenant ceiling. This module decides only the first of those two.
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.identity.provisioning import effective_grants_for_request
from boltrig.models import EMPTY_GRANTS, GrantSet, InvocationContext, WorkItem

log = logging.getLogger("boltrig.fleet.authority")

# The ONE verb post-run reflection writes through (US-WFL-07). Reflection is the
# pump's OWN bookkeeping, not the requesting principal's act: it writes a bland,
# deterministic, templated lesson into the Chief of Staff's own memory scope
# (``user:chief-of-staff``), and the principal cannot steer it. It is the same class
# of system write as the cancel audit row, which likewise does not draw on a
# principal's grants. So it carries a system seat of EXACTLY this verb: never the
# principal's grants (a principal holding no memory verb must not stop the org
# learning from a run, and a system-originated item has no principal at all), and
# never the tenant ceiling (that is the escalation this module exists to close).
# One verb, no fan-out, no dispatch of anything else; the tenant ceiling still binds
# it at dispatch, as it binds every verb.
REFLECTION_GRANTS = GrantSet.of(["memory.remember"])


async def principal_grants_for_item(store: Any, item: WorkItem) -> GrantSet:
    """The grants of the principal ``item`` is executed on behalf of (SEC-164).

    Mirrors the request path's resolution exactly (``effective_grants_for_request``):
    the user's provisioned org/user scope, narrowed by their workspace role when the
    item carries a workspace.

    Returns ``EMPTY_GRANTS`` when the item names no principal (a system-originated
    item), when the store cannot identify anyone (a storeless stub), or when the
    named principal has no user record. No identified principal, no authority.
    """
    if not item.on_behalf_of:
        return EMPTY_GRANTS  # system-originated: no principal, so no authority
    get_user = getattr(store, "get_user", None)
    if get_user is None:  # a storeless / stub store can identify no one
        return EMPTY_GRANTS
    user = await get_user(item.tenant_id, item.on_behalf_of)
    if user is None:  # names a principal the store does not know
        return EMPTY_GRANTS
    return await effective_grants_for_request(store, user, item.workspace_id)


def _context(item: WorkItem, run_id: str, grants: GrantSet) -> InvocationContext:
    """The pump's invocation context shape, over an already-resolved authority."""
    return InvocationContext(
        tenant_id=item.tenant_id,
        run_id=run_id,
        grants=grants,
        actor="chief-of-staff",
        actor_tier="tier1",
        on_behalf_of=item.on_behalf_of,
        workspace_id=item.workspace_id,
        extra=(
            {"principal_scope": {"departments": [item.owner_member]}}
            if item.owner_member
            else {}
        ),
    )


async def context_for(store: Any, item: WorkItem, run_id: str) -> InvocationContext:
    """The item's EXECUTION context, capped to the requesting principal (SEC-164).

    The pump's agents are tier-1/tier-2 seats, not principals, so an item must not
    execute at the tenant ceiling merely because a Department Head is the thing
    running it. The context's grants are THE PRINCIPAL's, which is what
    ``Spawner.spawn`` then intersects a child's skill grants against - so a child can
    never hold a verb the requesting principal lacks, however broad the selected
    skill's declared ``tool_grants``.

    The TENANT ceiling is deliberately not folded in here. It is a separate axis that
    ``GrantChecker`` enforces independently on every dispatch (caller grants AND the
    tenant ceiling must both permit the verb, US-IAM-04), so folding it in would be
    redundant; and ``GrantSet.intersect`` is not a symmetric set intersection (it
    keeps SELF's patterns that OTHER fully permits), so a ``{all: true}`` principal
    under a narrow tenant ceiling would collapse to NO authority rather than to the
    ceiling. Keeping the axes separate keeps both exact.
    """
    return _context(item, run_id, await principal_grants_for_item(store, item))


def reflection_context(item: WorkItem, run_id: str) -> InvocationContext:
    """The narrow system context a post-run reflection write carries (US-WFL-07).

    See ``REFLECTION_GRANTS``: exactly ``memory.remember``, and nothing else.
    Deliberately NOT the execution context - reflection is the pump's own bookkeeping,
    so it rides neither the principal's authority nor the tenant's. The tenant ceiling
    still binds it, enforced independently at dispatch as for any other verb.
    """
    return _context(item, run_id, REFLECTION_GRANTS)


async def route_to_head(
    cos: Any, heads: dict[str, Any], store: Any, item: WorkItem, run_id: str,
    ctx: InvocationContext,
) -> Any | None:
    """Route ``item`` to its department head, or ``None`` if unroutable (SEC-165).

    Fail-closed on the routing decision: a department with no configured head parks
    the item rather than silently executing it under a DIFFERENT department's head.
    The routed head is what ``owner_member`` records, and ``owner_member`` is the
    ``principal_scope`` the run's context claims, so a mis-route would make the run's
    own scope claim untrue. Deterministic is not the same thing as correct.
    """
    await store.upsert_checkpoint(item.tenant_id, run_id, "route", "started")
    # Addressed routing (SEC-178): an explicit target from channel intake is routing
    # data, not authority — it names the department directly when it resolves to a
    # configured head ("cos" is the tier-1 default: route normally). Anything else
    # falls through to the CoS's inferred route; grants bind either way. A
    # "workflow:<wf_id>" target never reaches here - the pump honors it upstream
    # (pump._run_addressed_workflow) before any routing.
    explicit = getattr(item, "target", None)
    if explicit and explicit != "cos" and explicit in heads:
        department = explicit
    else:
        department = await cos.route(item, ctx)
    head = heads.get(department)
    if head is None:
        log.warning("item %s routed to department %r with no head", item.id, department)
        return None
    item.owner_member = head.name
    await store.update_work_item(item)
    await store.upsert_checkpoint(
        item.tenant_id, run_id, "route", "done", output={"department": department}
    )
    return head
