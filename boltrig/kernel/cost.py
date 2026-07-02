"""Cost accounting and budget enforcement (US-COST-01/02, FR-COST-02/03/04).

Cost is attributed per call (tenant / department / workflow / agent type) into
the audit row. Budgets enforce token and cost ceilings; a hard-stop budget
refuses to commit a call that would exceed it, yielding a partial result rather
than a surprise bill. A soft (non-hard-stop) budget records overage and fires a
pre-emptive alert.

Cost is priced as tokens x micros-per-token. The price is policy-as-data
(FR-COST-04, audit M14): a per-model rate from the manifest ``models.prices``
table wins, and a model with no explicit price falls back to the cost-tier
default, so a deployment that configures no prices keeps the historical
behaviour exactly. After a run the ledger is trued-up against ACTUAL usage
(FR-COST-03, audit M14): ``reserve`` debits a pre-run estimate, then ``reconcile``
applies the signed (actual - estimate) delta so the budget reflects real spend
rather than the guess.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

from boltrig.models import BudgetExceeded
from boltrig.store import Store

log = logging.getLogger("boltrig.kernel.cost")

# alert callback: (tenant_id, scope_id, fraction_used) -> None
AlertFn = Callable[[str, str, float], Awaitable[None]]

_ALERT_FRACTION = 0.8  # pre-emptive alert threshold (US-COST-02)

# Cost-tier fallback prices (micros per token). The historical default used when
# a model carries no explicit per-model price. This is the FALLBACK for the
# policy-as-data price table (FR-COST-04) - a configured price always wins - and
# preserves the old static-tier accounting when a deployment sets no prices.
_TIER_MICROS_PER_TOKEN: dict[str, int] = {"cheap": 1, "standard": 5, "expensive": 25}


def price_micros(
    tokens: int,
    cost_tier: str,
    *,
    model: str | None = None,
    prices: Mapping[str, int] | None = None,
) -> int:
    """Cost in micros for a run of ``tokens`` tokens (FR-COST-04, audit M14).

    A per-model rate from the configured ``prices`` table wins; absent an explicit
    price for ``model`` we fall back to the ``cost_tier`` default, so behaviour is
    unchanged when no prices are configured. Pure data lookup - no provider name
    ever appears in the logic. Tokens are floored at 0 (a negative usage report is
    never a credit)."""
    rate: int | None = None
    if prices is not None and model is not None:
        rate = prices.get(model)
    if rate is None:
        rate = _TIER_MICROS_PER_TOKEN.get(cost_tier, 5)
    return max(0, int(tokens)) * int(rate)


class CostAccountant:
    def __init__(
        self,
        store: Store,
        alert: AlertFn | None = None,
        *,
        prices: Mapping[str, int] | None = None,
    ) -> None:
        self._store = store
        self._alert = alert
        # per-model price table (model name -> micros per token), policy-as-data
        # from the manifest (FR-COST-04). Empty => every model falls back to its
        # cost-tier default, i.e. the historical static-tier behaviour.
        self._prices: dict[str, int] = dict(prices or {})

    # --- pricing (policy-as-data, FR-COST-04) ---------------------------------
    def set_prices(self, prices: Mapping[str, int]) -> None:
        """Install the per-model price table (manifest seeding, apply_manifest)."""
        self._prices = dict(prices or {})

    @property
    def has_prices(self) -> bool:
        """True when a per-model price table is configured (else pure tier fallback)."""
        return bool(self._prices)

    def price(self, tokens: int, cost_tier: str, *, model: str | None = None) -> int:
        """Cost in micros for ``tokens`` at this tenant's configured prices
        (FR-COST-04). Per-model rate wins; falls back to the ``cost_tier`` default."""
        return price_micros(tokens, cost_tier, model=model, prices=self._prices)

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

        # 2. pre-emptive alerts (soft signal, US-COST-02). The alert is an
        # observability side-channel, so its invocation is fail-safe (P9): a
        # raising callback must never abort a metered reservation, matching every
        # other side-channel in the kernel (dispatch._emit, hitl._fire_resume,
        # spawn.events.publish, pi_runtime sink/revoke).
        if self._alert is not None:
            for scope_id, b in budgets.items():
                if b.cost_limit_micros:
                    used = (b.spent_micros + micros) / b.cost_limit_micros
                    if used >= _ALERT_FRACTION:
                        try:
                            await self._alert(tenant_id, scope_id, used)
                        except Exception:  # alert side-channel must never break reserve (P9)
                            log.debug(
                                "budget alert callback failed for tenant '%s' scope '%s'",
                                tenant_id, scope_id, exc_info=True,
                            )

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

    async def reconcile(
        self,
        tenant_id: str,
        scope_ids: list[str],
        delta_tokens: int,
        delta_micros: int,
    ) -> None:
        """Post-run cost true-up across every reserved scope (FR-COST-03, audit M14).

        ``reserve`` debited a pre-run ESTIMATE. Once the run reports real usage the
        caller passes the signed delta (actual - estimate) and we apply it to every
        scope, so the ledger reflects real spend rather than the guess. A scope with
        no budget is a no-op in the store (matching ``reserve`` skipping it), so
        passing every candidate scope is safe - a scope that was never reserved is
        never touched. The store floors each accumulator at 0, so a full refund
        (degraded / zero-usage run: delta = -estimate) can never drive the ledger
        negative. Unlike ``reserve`` this never re-checks the hard stop or alerts:
        it corrects the record of a call that already ran, it does not gate a new
        one."""
        if delta_tokens == 0 and delta_micros == 0:
            return  # the estimate was exact - nothing to true up
        for scope_id in scope_ids:
            await self._store.reconcile_budget(
                tenant_id, scope_id, delta_tokens, delta_micros
            )
