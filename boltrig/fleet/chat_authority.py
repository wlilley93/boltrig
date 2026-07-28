"""Say when a chat turn has no usable authority. Fail-closed is right; SILENT is the bug.

Its own module because ``fleet/chat.py`` sits at its structural ratchet, and because
this is one rule rather than a phrase re-derived at a call site.

Found on a live tenant, 2026-07-28: the client's own account was in neither
``org_members`` nor ``workspace_members``, so role resolution produced the empty
grant set (SEC-78), and its role was absent from ``chat.skills_by_role`` while
``default_skills`` was ``[]``, so it loaded no skills either. Every turn that user
took had zero tools - and nothing in the log or the ledger said so. The turn
completed, the agent apologised, and the record showed nothing wrong, which is the
worst way for a client to meet a defect.

``scripts/check_user_authority.py`` is the same rule applied ahead of time, per
tenant; this is the one that fires on a real turn.
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.addons import on_behalf_adapter_id

logger = logging.getLogger(__name__)


def warn_if_no_usable_authority(role: str, ceiling: Any, skills: list[str]) -> None:
    """Role name and counts only: no grant patterns, no user content (K-20)."""
    if ceiling.allow and skills:
        return
    logger.warning(
        "chat turn has no usable authority: role=%s grants=%d skills=%d "
        "(a caller in no org/workspace resolves to the empty set, and a role absent "
        "from chat.skills_by_role falls back to default_skills)",
        role,
        len(ceiling.allow),
        len(skills),
    )


async def seal_on_behalf_bearer(
    credentials: Any, tenant_id: str, run_id: str, bearer: str, user_id: str
) -> None:
    """Seal the caller's clamped external bearer for the adapter that claims it.

    Permission-parity passthrough: the bearer is sealed for the life of THIS run,
    BEFORE any verb dispatch, so dispatch re-mints it into the adapter credential
    and the downstream service enforces the CALLER's grants rather than the
    adapter's static service token.

    The adapter is resolved by ``on_behalf_adapter_id`` from whichever addon claims
    it, not from a hardcoded integration name. When nothing claims one the turn silently falls
    back to the static credential and the caller's own grants stop being enforced
    downstream - a deployment fault that is invisible in the record, because the
    turn succeeds. So it is named here, which is the same rule as the function
    above: fail-closed is right, fail-SILENT is the bug.
    """

    adapter_id = on_behalf_adapter_id()
    if not adapter_id:
        logger.warning(
            "on-behalf bearer present but NO adapter claims it: no active addon "
            "supplies an adapter id and BOLTRIG_OBO_ADAPTER_ID is unset; this turn "
            "falls back to the static adapter credential"
        )
        return
    await credentials.seal_run_scoped_adapter_bearer(
        tenant_id, run_id, adapter_id, bearer, user_id
    )


async def inherit_on_behalf_bearer(
    credentials: Any,
    tenant_id: str,
    *,
    parent_run_id: str,
    child_run_id: str,
    owner: str,
) -> None:
    """Carry the parent run's sealed bearer down to a delegated child run.

    The passthrough has to survive DELEGATION: a chat turn seals against the ROOT
    run id, but a chat turn never calls a verb itself - it spawns a worker, and
    dispatch happens under the CHILD's run id, which is what
    ``resolve_run_scoped_credential`` is keyed by. Without this the child misses
    the seal and every parity-dependent call is rejected downstream.

    Re-sealing is a PROPAGATION, not a widening: the same bearer, already clamped
    to min(agent,user), for the same adapter, for a run in the same turn on behalf
    of the same person. The child inherits only what the SAME owner sealed on the
    parent, so delegation carries a user's authority down their own run tree and
    never launders it into somebody else's. Each run holds its own ref, so the
    terminal sweep still clears it and a foreign run still resolves to None.

    Best-effort by construction: with no bearer sealed (every dev / non-passthrough
    tenant) it is a no-op and dispatch keeps the adapter's static credential, so it
    is execution-neutral for anyone not using the parity seam. A failure here must
    never take down a spawn that would otherwise succeed.
    """

    if not parent_run_id or not owner:
        return
    adapter_id = None
    try:
        # INSIDE the guard. This resolution reads configuration and can raise
        # (an unregistered BOLTRIG_ADDONS name is deliberately fatal), and this
        # function's contract is that it must NEVER take down a spawn that would
        # otherwise succeed - the worst case is the pre-existing fallback. Resolved
        # outside, a misconfiguration stopped being a degraded parity path and
        # became a failed spawn.
        adapter_id = on_behalf_adapter_id()
        if not adapter_id:  # nothing claims one: nothing was sealed to inherit
            return
        inherited = await credentials.resolve_run_scoped_credential(
            tenant_id, parent_run_id, adapter_id, owner
        )
        if inherited is None:
            return
        token = (inherited.material or {}).get("token")
        if not token:
            return
        await credentials.seal_run_scoped_adapter_bearer(
            tenant_id, child_run_id, adapter_id, token, owner
        )
    except Exception:  # noqa: BLE001 - never fail a spawn on the parity path
        logger.warning(
            "could not carry the run-scoped adapter bearer for '%s' to the child "
            "run; it will fall back to the adapter's static credential",
            adapter_id,
        )
