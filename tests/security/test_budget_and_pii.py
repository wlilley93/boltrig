"""Budget hard-stop (FR-COST-02) and PII redaction (US-PRIV-02, SEC-13)."""

import pytest

from boltrig.kernel import pii
from boltrig.models import Budget, BudgetExceeded
from tests.conftest import TENANT


@pytest.mark.security
@pytest.mark.invariant("FR-COST-02")
async def test_budget_hard_stop_halts_before_exceeding(kernel):
    kernel.store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=True)
    )
    # first reservation fits
    await kernel.cost.reserve(TENANT, ["dept:eng"], tokens=0, micros=900)
    # second would exceed -> hard stop, nothing committed
    with pytest.raises(BudgetExceeded):
        await kernel.cost.reserve(TENANT, ["dept:eng"], tokens=0, micros=200)


@pytest.mark.security
@pytest.mark.invariant("FR-COST-02")
async def test_reserve_is_all_or_nothing_across_scopes(kernel):
    # tenant has headroom; the department is already at its hard-stop limit.
    kernel.store.set_budget(
        Budget(id="tenant", tenant_id=TENANT, scope_type="tenant",
               cost_limit_micros=10_000, hard_stop=True)
    )
    kernel.store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=100, spent_micros=100, hard_stop=True)
    )
    with pytest.raises(BudgetExceeded):
        await kernel.cost.reserve(TENANT, ["tenant", "dept:eng"], tokens=0, micros=50)
    # the tenant budget (processed first) must NOT have been debited - reserve on none.
    tb = await kernel.store.get_budget(TENANT, "tenant")
    assert tb.spent_micros == 0


@pytest.mark.security
@pytest.mark.invariant("FR-COST-02")
async def test_reserve_honors_consume_budget_refusal(kernel, monkeypatch):
    # H4: the fail-fast read (step 1) can see headroom, yet a concurrent reserve
    # may debit the scope before this reserve's atomic consume runs. consume_budget
    # then returns False (hard-stop, no debit). reserve MUST honour that refusal and
    # raise, not silently run unmetered past the cap.
    kernel.store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=True)
    )

    async def racing_consume(tenant_id, scope_id, tokens, micros):
        # stand in for a concurrent reserve that exhausted the hard stop between
        # our headroom read and this commit: refuse without debiting.
        return False

    monkeypatch.setattr(kernel.store, "consume_budget", racing_consume)
    with pytest.raises(BudgetExceeded):
        # step 1 sees full headroom (spent=0), so only step 3 can catch this.
        await kernel.cost.reserve(TENANT, ["dept:eng"], tokens=0, micros=100)
    # the over-cap reservation did not proceed to debit the real budget.
    b = await kernel.store.get_budget(TENANT, "dept:eng")
    assert b.spent_micros == 0


@pytest.mark.security
@pytest.mark.invariant("FR-COST-02")
async def test_soft_budget_does_not_halt(kernel):
    kernel.store.set_budget(
        Budget(id="t", tenant_id=TENANT, scope_type="tenant",
               cost_limit_micros=100, hard_stop=False)
    )
    # over the soft limit, but no exception
    await kernel.cost.reserve(TENANT, ["t"], tokens=0, micros=500)


@pytest.mark.security
@pytest.mark.invariant("SEC-13")
def test_pii_redaction():
    res = pii.redact("contact a@b.com or 555-12-3456 about it")
    assert res.has_pii
    assert "a@b.com" not in res.redacted
    assert "[REDACTED:email]" in res.redacted


@pytest.mark.security
def test_secret_scanner_flags_keys_and_identity():
    assert pii.contains_secret("token sk-abcdefghijklmnopqrstuvwx")
    assert pii.contains_secret("reach me at person@example.com")
    assert pii.contains_secret("nothing here") is None
