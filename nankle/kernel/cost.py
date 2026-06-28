"""Cost accounting and budget enforcement (US-COST-01/02, FR-COST-02).

Cost is attributed per call (tenant / department / workflow / agent type) into
the audit row. Budgets enforce token and cost ceilings; a hard-stop budget
refuses to commit a call that would exceed it, yielding a partial result rather
than a surprise bill. A soft (non-hard-stop) budget records overage and fires a
pre-emptive alert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nankle.models import BudgetExceeded
from nankle.store import Store

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
        exceeded - and reserves on none of them in that case."""
        # Pre-check pre-emptive alerts before committing.
        for scope_id in scope_ids:
            budget = await self._store.get_budget(tenant_id, scope_id)
            if budget is None:
                continue
            if budget.cost_limit_micros:
                used = (budget.spent_micros + micros) / budget.cost_limit_micros
                if used >= _ALERT_FRACTION and self._alert is not None:
                    await self._alert(tenant_id, scope_id, used)
        # Commit. consume_budget is atomic per scope and returns False on a
        # hard-stop breach.
        for scope_id in scope_ids:
            ok = await self._store.consume_budget(tenant_id, scope_id, tokens, micros)
            if not ok:
                raise BudgetExceeded(
                    f"budget '{scope_id}' hard-stop reached for tenant '{tenant_id}'"
                )
