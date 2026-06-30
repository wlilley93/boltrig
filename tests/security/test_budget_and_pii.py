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
