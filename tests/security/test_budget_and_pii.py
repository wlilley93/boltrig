"""Budget hard-stop (FR-COST-02) and PII redaction (US-PRIV-02, SEC-13)."""

import pytest

from boltrig.kernel import pii
from boltrig.kernel.cost import CostAccountant
from boltrig.models import Budget, BudgetExceeded
from boltrig.store import InMemoryStore
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
        Budget(id=TENANT, tenant_id=TENANT, scope_type="tenant",
               cost_limit_micros=10_000, hard_stop=True)
    )
    kernel.store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=100, spent_micros=100, hard_stop=True)
    )
    with pytest.raises(BudgetExceeded):
        await kernel.cost.reserve(TENANT, [TENANT, "dept:eng"], tokens=0, micros=50)
    # the tenant budget (processed first) must NOT have been debited - reserve on none.
    tb = await kernel.store.get_budget(TENANT, TENANT)
    assert tb.spent_micros == 0


@pytest.mark.security
@pytest.mark.invariant("FR-COST-02")
async def test_reserve_honors_atomic_store_refusal(kernel, monkeypatch):
    # H4 / Phase 6: the fail-fast read (step 1) can see headroom, yet a concurrent
    # reserve may consume the scope's headroom before this reserve's transactional
    # commit runs. The atomic multi-scope reserve (step 3) then re-checks the hard
    # stop under the row lock and returns False WITHOUT debiting. reserve MUST honour
    # that refusal and raise, not silently run unmetered past the cap.
    kernel.store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=True)
    )

    async def racing_reserve(tenant_id, reservations):
        # stand in for a concurrent reserve that exhausted the hard stop between
        # our headroom read and this commit: refuse without debiting any scope.
        return False

    monkeypatch.setattr(kernel.store, "reserve_budgets_atomic", racing_reserve)
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
@pytest.mark.invariant("US-COST-02")
async def test_soft_budget_fires_preemptive_alert_when_crossing_the_threshold():
    alerts: list[tuple[str, str, float]] = []

    async def recorder(tenant_id: str, scope_id: str, used: float) -> None:
        alerts.append((tenant_id, scope_id, used))

    # crossing 0.8 of a soft budget fires exactly one pre-emptive alert
    store = InMemoryStore()
    store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=False)
    )
    acct = CostAccountant(store, alert=recorder)
    await acct.reserve(TENANT, ["dept:eng"], tokens=0, micros=800)
    assert len(alerts) == 1
    tenant_id, scope_id, used = alerts[0]
    assert tenant_id == TENANT and scope_id == "dept:eng"
    assert used >= 0.8

    # staying below 0.8 fires nothing (fresh scope so the reserve above is isolated)
    alerts.clear()
    store2 = InMemoryStore()
    store2.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=False)
    )
    acct2 = CostAccountant(store2, alert=recorder)
    await acct2.reserve(TENANT, ["dept:eng"], tokens=0, micros=700)
    assert alerts == []


@pytest.mark.invariant("US-COST-02")
async def test_alert_callback_exception_does_not_fail_reservation():
    # The pre-emptive alert is an observability side-channel: a raising callback
    # must never abort a metered reservation (P9), matching every other kernel
    # side-channel. The budget must still debit and no exception may propagate.
    fired: list[tuple[str, str, float]] = []

    async def raising(tenant_id: str, scope_id: str, used: float) -> None:
        fired.append((tenant_id, scope_id, used))
        raise RuntimeError("alert sink is down")

    store = InMemoryStore()
    store.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=False)
    )
    acct = CostAccountant(store, alert=raising)

    # crosses the alert threshold; the raising callback must be swallowed
    await acct.reserve(TENANT, ["dept:eng"], tokens=0, micros=800)

    # the callback did fire (crossed 0.8) but its exception was swallowed
    assert len(fired) == 1
    # and the reservation completed: the budget was debited past the alert line
    b = await store.get_budget(TENANT, "dept:eng")
    assert b is not None and b.spent_micros == 800

    # a normal (non-raising) alert still fires afterwards
    ok: list[tuple[str, str, float]] = []

    async def recorder(tenant_id: str, scope_id: str, used: float) -> None:
        ok.append((tenant_id, scope_id, used))

    store2 = InMemoryStore()
    store2.set_budget(
        Budget(id="dept:eng", tenant_id=TENANT, scope_type="department",
               cost_limit_micros=1000, hard_stop=False)
    )
    acct2 = CostAccountant(store2, alert=recorder)
    await acct2.reserve(TENANT, ["dept:eng"], tokens=0, micros=800)
    assert len(ok) == 1 and ok[0][2] >= 0.8


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


# --- M12 / SEC-42: broadened secret detection --------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-42")
def test_contains_secret_detects_pem_google_slack_stripe_anthropic_and_high_entropy():
    # each secret shape returns a truthy, precise kind (M12). The scanner backs
    # BOTH the audit scrub (K-20) and the memory-ingest guard, so any shape it
    # misses would persist verbatim.
    pem_rsa = "-----BEGIN RSA PRIVATE KEY-----\nMIIExxx\n-----END RSA PRIVATE KEY-----"
    pem_openssh = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA\n-----END"
    pem_bare = "-----BEGIN PRIVATE KEY-----\nMIIBVg\n-----END PRIVATE KEY-----"
    google = "key AIzaSyA1234567890abcdefghijklmnopqrstuvw here"
    slack = "xoxb-123456789012-abcdefGHIJKL notify"
    stripe_live = "sk_live_51H8xAbCdEfGhIjKlMnOpQrSt"
    stripe_restricted = "rk_live_51H8xAbCdEfGhIjKlMnOpQrSt"
    anthropic = "sk-ant-api03-AbCdEf012345_ghIJKlmnop-qrstUV"
    for text in (pem_rsa, pem_openssh, pem_bare, google, slack, stripe_live,
                 stripe_restricted, anthropic):
        assert pii.contains_secret(text), f"not detected as a secret: {text!r}"

    # precise reported kinds where the shape names the provider
    assert pii.contains_secret(pem_rsa) == "pem_private_key"
    assert pii.contains_secret(google) == "google_api_key"
    assert pii.contains_secret(slack) == "slack_token"
    assert pii.contains_secret(stripe_live) == "stripe_key"
    assert pii.contains_secret(anthropic) == "anthropic_key"

    # the high-entropy fallback catches an opaque token of no enumerated shape
    high_entropy = "config blob kP3xQ9zR2mN7bV4cX1wL8sT6yU0aE5dF9gH2jK4lM6n end"
    assert pii.contains_secret(high_entropy) == "high_entropy"


@pytest.mark.security
@pytest.mark.invariant("SEC-42")
def test_contains_secret_does_not_trip_on_prose_uuid_or_git_sha():
    # regression guard for the entropy fallback (M12): ordinary content that
    # legitimately appears in audit rows / memory must NOT be flagged. Hex SHAs
    # and UUIDs are non-diverse (no uppercase) and low-entropy (~3.2-3.8), prose
    # has short whitespace-separated tokens - none may reach the fallback.
    benign = [
        "the client prefers email updates on fridays and dislikes phone calls",
        "commit 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b fixed the flaky test",
        "request id 550e8400-e29b-41d4-a716-446655440000 completed successfully",
        "checksum 550e8400e29b41d4a716446655440000 matched the manifest",
        "meeting notes: quarterly roadmap, hiring plan, budget review, offsite",
    ]
    for text in benign:
        assert pii.contains_secret(text) is None, f"false positive on: {text!r}"
