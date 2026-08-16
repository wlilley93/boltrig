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
behaviour exactly. A per-model rate is EITHER one number for every token or the
published rate card's ``{input, output}`` pair, because those two prices are not
the same number (see ``_rate_pair``). After a run the ledger is trued-up against ACTUAL usage
(FR-COST-03, audit M14): ``reserve`` debits a pre-run estimate, then ``reconcile``
applies the signed (actual - estimate) delta so the budget reflects real spend
rather than the guess.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from boltrig.models import (
    BudgetExceeded,
    BudgetWindowRef,
    BudgetWindowUnavailable,
    utcnow,
)
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

# One configured per-model rate: EITHER a single number applied to every token
# (the historical shape - one blended rate) OR the published rate card's
# ``{"input": x, "output": y}`` pair. Both are pure data; no provider name, and no
# behaviour, ever appears in this table.
Rate = float | Mapping[str, float]
PriceTable = Mapping[str, Rate]


@dataclass(frozen=True)
class BudgetReservation:
    """Exact usage buckets selected atomically for one estimated model call."""

    tenant_id: str
    run_id: str | None
    reserved_at: datetime
    windows: tuple[BudgetWindowRef, ...]


def _as_rate(value: object) -> float | None:
    """One rate as a float, or ``None`` when it is absent or not a number.

    THE UNIT, stated where it is used: a rate is MICROS PER TOKEN, and that is
    NUMERICALLY THE SAME NUMBER as the published USD-per-1,000,000-tokens figure.
    A micro is $0.000001, so $0.35 per 1M tokens = 0.35e-6 USD/token = 0.35
    micro-USD/token. A rate card number is therefore usable AS WRITTEN - there is
    no conversion step to get wrong, and none should ever be added here.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rate_pair(rate: object) -> tuple[float, float] | None:
    """Normalise a configured rate to ``(input_rate, output_rate)`` micros/token.

    WHY THE SPLIT EXISTS: input and output are not the same price. On the rate
    cards the fleet bills from they differ by MORE THAN 2x (the tenant chat model
    is $0.35 in / $0.75 out per 1M tokens), and an agent turn is heavily
    INPUT-weighted - a long composed prompt, a short answer - so charging a whole
    turn at the output rate over-bills it substantially and trips a hard-stop
    budget early. Nothing errors; it only shows up on the invoice.

    A SCALAR is the historical shape: the same rate on both legs, which makes the
    split arithmetic collapse back to ``tokens x rate`` exactly, so a deployment
    that configures one number per model keeps working unchanged. In a MAPPING, a
    leg that is missing or unparseable falls back to the OTHER leg rather than to
    zero - a silently free leg is exactly the bug this path exists to prevent.
    ``None`` means 'no usable rate here' and the caller falls back to the tier.
    """
    if isinstance(rate, Mapping):
        input_rate = _as_rate(rate.get("input"))
        output_rate = _as_rate(rate.get("output"))
        if input_rate is None and output_rate is None:
            return None
        if input_rate is None:
            input_rate = output_rate
        elif output_rate is None:
            output_rate = input_rate
        return (float(input_rate), float(output_rate))
    value = _as_rate(rate)
    return None if value is None else (value, value)


def _priced_micros(
    rates: tuple[float, float], tokens: int, input_tokens: int, output_tokens: int
) -> int:
    """Apply ``(input_rate, output_rate)`` to one run's reported usage.

    Every token is billed EXACTLY ONCE. Each leg the runtime reported is billed at
    its own rate, and whatever the split does not account for is billed at the
    higher leg. That remainder is normally zero - and it is the WHOLE total when
    the runtime reported no split at all, which is what makes an unknown split
    fall back to single-rate pricing on the total instead of billing the run as
    FREE. A silent zero is worse than an imprecise charge: it also bypasses the
    budget gate, because a cost of zero always passes a ceiling check.

    Tokens are floored at 0 (a negative usage report is never a credit) and the
    product is ROUNDED, not truncated: micros stay the integer STORAGE unit, only
    the rate is fractional, and always flooring would under-bill every run by up
    to a micro.
    """
    input_rate, output_rate = rates
    billed_input = max(0, int(input_tokens or 0))
    billed_output = max(0, int(output_tokens or 0))
    unattributed = max(0, max(0, int(tokens or 0)) - billed_input - billed_output)
    # Unattributed tokens are billed at the INPUT rate, not the higher leg.
    #
    # This was `max(input_rate, output_rate)` and adversarial review killed it. Only the Codex
    # runtime reports a split today; every other producer sets a bare total, so `unattributed`
    # is the WHOLE run there and the premium leg priced all of it. On Anthropic's rate card
    # ($3 in / $15 out per 1M) that is a 3.84x OVER-bill - worse than the tier fallback this
    # function exists to replace. Provider-native runtimes have since been removed;
    # the conservative unattributed-token rule remains part of the generic ledger
    # contract for any future producer that reports only a total.
    #
    # The input rate is the honest estimator when the split is unknown: an agent turn is heavily
    # input-weighted (a long composed prompt plus tool schemas, a short answer), so it is the
    # closer of the two. It also errs toward UNDER-billing, which is the right direction to be
    # wrong with a client - an over-charge you have to refund costs more than trust.
    return max(0, round(
        billed_input * input_rate
        + billed_output * output_rate
        + unattributed * input_rate
    ))


def price_micros(
    tokens: int,
    cost_tier: str,
    *,
    model: str | None = None,
    prices: PriceTable | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> int:
    """Cost in micros for a run of ``tokens`` tokens (FR-COST-04, audit M14).

    A per-model rate from the configured ``prices`` table wins; absent an explicit
    price for ``model`` we fall back to the ``cost_tier`` default, so behaviour is
    unchanged when no prices are configured. Pure data lookup - no provider name
    ever appears in the logic. Tokens are floored at 0 (a negative usage report is
    never a credit).

    ``input_tokens`` / ``output_tokens`` are the runtime's split of ``tokens``
    when it reports one (Codex does, on ``thread/tokenUsage/updated``). They are
    OPTIONAL and additive: 0/0 with a total present prices exactly as before, at a
    single rate on the total.

    THE RATE MAY BE FRACTIONAL. It used to be coerced with ``int(rate)``, so the
    finest price expressible was 1 micro/token = $1.00 per million - and every real
    model we route to is cheaper than that. Configuring an honest rate therefore
    made billing WORSE, not better: 0.35 truncated to 0 and the model priced as
    FREE, which is why the tier fallback had never been replaced. Micros stay the
    integer STORAGE unit; only the rate gained precision."""
    rates: tuple[float, float] | None = None
    if prices is not None and model is not None:
        rates = _rate_pair(prices.get(model))
    if rates is None:
        tier = float(_TIER_MICROS_PER_TOKEN.get(cost_tier, 5))
        rates = (tier, tier)
    return _priced_micros(rates, tokens, input_tokens, output_tokens)


class CostAccountant:
    def __init__(
        self,
        store: Store,
        alert: AlertFn | None = None,
        *,
        prices: PriceTable | None = None,
    ) -> None:
        self._store = store
        self._alert = alert
        # per-model price table (model name -> micros per token, or the rate
        # card's {input, output} pair of them), policy-as-data from the manifest
        # (FR-COST-04). Empty => every model falls back to its cost-tier default,
        # i.e. the historical static-tier behaviour.
        self._prices: dict[str, Rate] = dict(prices or {})

    # --- pricing (policy-as-data, FR-COST-04) ---------------------------------
    def set_prices(self, prices: PriceTable) -> None:
        """Install the per-model price table (manifest seeding, apply_manifest)."""
        self._prices = dict(prices or {})

    def set_price(self, model: str, rate: Rate) -> None:
        """Set ONE model's rate without replacing the table (DIS-8: a promoted
        distill adapter is priced in the same act as its promotion; the manifest
        re-seeds the full table on the next apply)."""
        self._prices[model] = rate

    @property
    def has_prices(self) -> bool:
        """True when a per-model price table is configured (else pure tier fallback)."""
        return bool(self._prices)

    def price(
        self,
        tokens: int,
        cost_tier: str,
        *,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> int:
        """Cost in micros for ``tokens`` at this tenant's configured prices
        (FR-COST-04). Per-model rate wins; falls back to the ``cost_tier`` default.
        Each leg of a reported input/output split is priced at its own rate; a
        runtime that reports no split (0/0) is priced on the total as before."""
        return price_micros(
            tokens,
            cost_tier,
            model=model,
            prices=self._prices,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def reserve(
        self,
        tenant_id: str,
        scope_ids: list[str],
        tokens: int,
        micros: int,
        *,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> BudgetReservation:
        """Reserve every relevant scope or raise without charging any.

        The store's locked multi-scope operation is authoritative; the preceding
        reads provide precise early errors and soft alerts only (FR-COST-05).
        """
        reserved_at = at or utcnow()
        budgets = {}
        for scope_id in scope_ids:
            b = await self._store.get_budget(
                tenant_id, scope_id, run_id=run_id, at=reserved_at
            )
            if b is not None:
                if b.usage_state != "current":
                    raise BudgetWindowUnavailable(
                        f"run-window budget '{scope_id}' requires an exact run id"
                    )
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

        # 3. commit all, transactionally (audit H4, Phase 6, FR-COST-05). One
        # transaction locks every scope FOR UPDATE, re-checks each hard stop, and
        # debits EVERY scope or NONE. This is the authoritative all-or-nothing: even
        # when step 1's unlocked read saw headroom, a concurrent reserve may have
        # consumed it between that read and this commit - the atomic reserve then
        # returns None without debiting ANY scope, closing the partial-debit window
        # the old per-scope loop left open (scope A debited, scope B refused, A stays
        # charged for a call that never ran).
        windows = await self._store.reserve_budgets_atomic(
            tenant_id,
            [(scope_id, tokens, micros) for scope_id in scope_ids],
            run_id=run_id,
            at=reserved_at,
        )
        if windows is None:
            raise BudgetExceeded(
                f"budget hard-stop reached for tenant '{tenant_id}' "
                "under a concurrent reservation"
            )
        return BudgetReservation(tenant_id, run_id, reserved_at, windows)

    async def reconcile(
        self,
        reservation: BudgetReservation,
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
        for window in reservation.windows:
            await self._store.reconcile_budget(
                reservation.tenant_id,
                window,
                delta_tokens,
                delta_micros,
            )
