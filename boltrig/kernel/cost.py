"""Cost accounting and budget enforcement (US-COST-01/02, FR-COST-02).

Cost is attributed per call (tenant / department / workflow / agent type) into
the audit row. Budgets enforce token and cost ceilings; a hard-stop budget
refuses to commit a call that would exceed it, yielding a partial result rather
than a surprise bill. A soft (non-hard-stop) budget records overage and fires a
pre-emptive alert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from boltrig.models import BudgetExceeded
from boltrig.store import Store

# alert callback: (tenant_id, scope_id, fraction_used) -> None
AlertFn = Callable[[str, str, float], Awaitable[None]]

_ALERT_FRACTION = 0.8  # pre-emptive alert threshold (US-COST-02)


class CostAccountant:
    def __init__(self, store: Store, alert: AlertFn | None = None) -> None:
        self._store = store
        self._alert = alert

    async def reserve(
        self, tenant_id: str, scope_ids: list[str], tokens: int, micros: int
    ) -> None:
        """Reserve budget across every relevant scope (tenant, department,
        workflow). Raises ``BudgetExceeded`` if any hard-stop scope would be
        exceeded - and reserves on NONE of them in that case.

        All-or-nothing: read every scope, fail-fast if any hard-stop has no
        headroom, and only then commit. The old loop committed scopes one at a
        time and raised on the first breach, leaving earlier scopes debited for a
        call that never ran (a budget double-charge on every retry)."""
        budgets = {}
        for scope_id in scope_ids:
            b = await self._store.get_budget(tenant_id, scope_id)
            if b is not None:
                budgets[scope_id] = b

        # 1. fail-fast: if ANY hard-stop scope lacks headroom, reserve on none.
        for scope_id, b in budgets.items():
            over_tokens = b.token_limit is not None and (
                b.spent_tokens + max(0, tokens)
            ) > b.token_limit
            over_micros = b.cost_limit_micros is not None and (
                b.spent_micros + max(0, micros)
            ) > b.cost_limit_micros
            if b.hard_stop and (over_tokens or over_micros):
                raise BudgetExceeded(
                    f"budget '{scope_id}' hard-stop reached for tenant '{tenant_id}'"
                )

        # 2. pre-emptive alerts (soft signal, US-COST-02).
        if self._alert is not None:
            for scope_id, b in budgets.items():
                if b.cost_limit_micros:
                    used = (b.spent_micros + micros) / b.cost_limit_micros
                    if used >= _ALERT_FRACTION:
                        await self._alert(tenant_id, scope_id, used)

        # 3. commit all. Step 1's fail-fast guarantees headroom under single-threaded
        # use, but consume_budget re-checks the hard stop atomically (FOR UPDATE) and
        # returns False WITHOUT debiting when a concurrent reserve has consumed the
        # headroom between our read and this commit. Honour that refusal (H4): raise
        # rather than run unmetered past a hard stop.
        #
        # Compensation limitation: the Store exposes no refund verb, so scopes already
        # debited earlier in this loop stay charged for a call that will not run. That
        # is a bounded over-count on the losing side of a race, never an under-count -
        # the hard stop always holds. The single-transaction FOR UPDATE fix is a
        # store-level day-2 item (audit H4).
        for scope_id in scope_ids:
            committed = await self._store.consume_budget(tenant_id, scope_id, tokens, micros)
            if not committed:
                raise BudgetExceeded(
                    f"budget '{scope_id}' hard-stop reached for tenant '{tenant_id}' "
                    "under a concurrent reservation"
                )
