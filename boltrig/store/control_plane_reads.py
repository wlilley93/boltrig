"""Cross-tenant control-plane reads, deliberately outside the RLS fence.

THE DEFECT THIS MODULE EXISTS FOR, measured on the beelink 2026-07-31.

Enabling ``BOLTRIG_RLS=1`` silently stopped two janitors. Both
:func:`boltrig.fleet.anchor.run_anchor_sweep_detailed` and
:func:`boltrig.kernel.hitl_expiry.run_hitl_expiry_sweep` begin by enumerating
tenants with ``store.list_orgs()``. That read is exempt from tenant binding - it
has no tenant to bind, being the query that DISCOVERS the tenants - so it ran on
an unbound connection, where the ``organisations`` policy

    tenant_isolation USING (id = current_setting('app.tenant_id', true))

matches nothing. Measured at the database: the owner saw 1 row, ``boltrig_app``
bound to ``default`` saw 1, and ``boltrig_app`` UNBOUND saw **0**.

So each sweep iterated an empty list, did nothing, wrote no receipt, logged
nothing, and returned 0. Overdue HITL approvals stopped timing out (SEC-14) and
audit-chain anchoring stopped (COUNTY 9 D4), for nine hours, while both loops
presented as idle. Nothing raised, because nothing in that failure could raise.

**The same fact was reported that morning as proof the fence worked.** "Unbound
sees 0 rows" is simultaneously the fence working and this outage. A fail-closed
default is only safe where every reader has something to fail closed ON; a
discovery query has nothing, so for it the fence is not a fence but a blindfold.

WHY THE EXEMPTION IS SAFE, AND WHAT KEEPS IT SO. Being cross-tenant is the
POINT of a control-plane enumeration, so this is an exemption rather than a bug
to fix. It is safe only because of properties that are not self-evident and can
be broken by a later edit:

* It takes NO caller input, so there is no parameter to confuse.
* It returns org metadata, never tenant content.
* Its ONLY callers are the two fleet janitors. It is unreachable from any
  request-scoped surface, so no client can reach a cross-tenant read.

``tests/security/test_rls_exemptions.py`` pins that caller set. Wiring one of
these reads into an HTTP path fails the build instead of leaking every tenant,
which is the difference between a documented exemption and a hole with a comment
next to it.

ANYTHING ADDED HERE MUST EARN IT. This is not the place to put a method that is
awkward to bind; it is for reads that are cross-tenant BY DEFINITION. A method
that has a tenant and merely forgot to bind belongs in the fence.
"""

from __future__ import annotations

from typing import Any

from .rows import _org


class ControlPlaneReadsPG:
    """Reads that must see every tenant, on an unfenced connection.

    Mixed into :class:`~boltrig.store.postgres.PostgresStore`. Each method uses
    ``self._pool.acquire()`` rather than the ``_RlsPool`` convenience calls,
    because ``acquire()`` passes through WITHOUT the ``SET LOCAL ROLE
    boltrig_app`` switch - and a superuser bypasses RLS even under FORCE, so the
    policies do not apply to the resulting connection.
    """

    _pool: Any

    async def list_orgs(self) -> list[Any]:
        """Every tenant, newest first. Cross-tenant by definition (see module doc).

        An org's id IS its tenant_id, which is why the janitors can sweep straight
        off this list.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM organisations ORDER BY created_at DESC"
            )
        return [_org(r) for r in rows]


__all__ = ["ControlPlaneReadsPG"]
