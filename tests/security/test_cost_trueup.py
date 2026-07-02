"""Cost true-up + real price table (FR-COST-03 / FR-COST-04, audit finding M14).

M14: budget was reserved once per spawn against a char-count ESTIMATE and never
reconciled against the model's actual returned token usage, so the ledger drifted
every run; and cost was tokens x static tier micros, not a real per-model price.
These tests pin the post-run true-up (the ledger equals ACTUAL, not the estimate,
in both the over- and under-estimate cases and the degraded refund case) and the
policy-as-data price table (a configured per-model price wins; an unpriced model
falls back to the tier default, preserving the historical behaviour).
"""

import pytest

from boltrig.config.manifest import load_manifest
from boltrig.fleet import build_spawner
from boltrig.fleet.result import AgentResult
from boltrig.kernel import Kernel
from boltrig.kernel.cost import CostAccountant, price_micros
from boltrig.models import (
    AgentCapability,
    Budget,
    GrantSet,
    InvocationContext,
    Skill,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel_with_caps() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    # a single cheap capable runtime (tier rate = 1 micro/token)
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 2, True, "cheap")
    )
    await store.upsert_skill(
        Skill(
            id="analysis/decompose",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Decompose the task.",
            tool_grants=["ticket.read"],
            context_requirements={
                "type": "object",
                "required": ["epic_id"],
                "properties": {"epic_id": {"type": "string"}},
            },
        )
    )
    return Kernel(store)


def _ctx() -> InvocationContext:
    return InvocationContext(
        tenant_id=T, grants=GrantSet.of(["*"]), actor="head", depth=0,
        extra={"epic_id": "ENG-441"},
    )


class _FakeRuntime:
    """A runtime that reports a fixed, chosen token usage (the 'actual')."""

    runtime = "fake"

    def __init__(self, tokens: int, cost_micros: int, cost_tier: str = "cheap") -> None:
        self._tokens = tokens
        self._cost = cost_micros
        self.cost_tier = cost_tier

    async def run(self, prompt, context, *, tools):
        return AgentResult.succeeded(
            output={"ok": True}, summary="ran",
            tokens_used=self._tokens, cost_micros=self._cost,
        )


@pytest.mark.security
@pytest.mark.invariant("FR-COST-03")
async def test_budget_trued_up_to_actual_after_run(monkeypatch):
    # tier 'cheap' prices at 1 micro/token, so micros == tokens and the ledger is
    # easy to read: after the run it must equal the ACTUAL usage, not the estimate.
    kernel = await _kernel_with_caps()
    kernel.store.set_budget(
        Budget(id="tenant", tenant_id=T, scope_type="tenant",
               cost_limit_micros=10_000_000, hard_stop=True)
    )
    spawner = build_spawner(kernel)

    # --- actual came in HIGHER than the estimate --------------------------------
    async def high_runtime_for(tenant_id, capability, context=None):
        return _FakeRuntime(tokens=9000, cost_micros=123)  # cost ignored; priced by table

    monkeypatch.setattr(spawner, "_runtime_for", high_runtime_for)
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, _ctx())
    assert res["tokens_used"] == 9000
    b = await kernel.store.get_budget(T, "tenant")
    # ledger == ACTUAL (9000 tokens x 1 micro), not the tiny char-count estimate.
    assert b.spent_tokens == 9000
    assert b.spent_micros == 9000

    # --- a second run whose actual is LOWER than the estimate -------------------
    # inflate the estimate with a long task, then report a tiny actual usage.
    async def low_runtime_for(tenant_id, capability, context=None):
        return _FakeRuntime(tokens=5, cost_micros=999)

    monkeypatch.setattr(spawner, "_runtime_for", low_runtime_for)
    long_task = "x" * 4000  # estimate ~ 1000 tokens, far above the 5-token actual
    res2 = await spawner.spawn(T, long_task, ["analysis/decompose"], {}, _ctx())
    assert res2["tokens_used"] == 5
    b2 = await kernel.store.get_budget(T, "tenant")
    # the second run added exactly its ACTUAL 5 tokens/micros on top of the first
    # run's trued 9000 - the inflated estimate was refunded down to the actual.
    assert b2.spent_tokens == 9005
    assert b2.spent_micros == 9005


@pytest.mark.security
@pytest.mark.invariant("FR-COST-03")
async def test_degraded_run_refunds_the_estimate(monkeypatch):
    # a degraded / zero-usage run reserved an estimate but did no real work; the
    # true-up must refund the whole estimate so the ledger returns to zero.
    kernel = await _kernel_with_caps()
    kernel.store.set_budget(
        Budget(id="tenant", tenant_id=T, scope_type="tenant",
               cost_limit_micros=10_000, hard_stop=True)
    )
    spawner = build_spawner(kernel)

    class _DegradedRuntime:
        runtime = "hermes"
        cost_tier = "cheap"

        async def run(self, prompt, context, *, tools):
            # the P9 degrade shape: ok=True, degraded=True, tokens_used == 0
            return AgentResult.degrade(runtime="hermes", reason="no_api_key")

    async def degraded_runtime_for(tenant_id, capability, context=None):
        return _DegradedRuntime()

    monkeypatch.setattr(spawner, "_runtime_for", degraded_runtime_for)
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, _ctx())
    assert res["degraded"] is True
    assert res["tokens_used"] == 0
    b = await kernel.store.get_budget(T, "tenant")
    # the reserved estimate was fully refunded - a no-op run costs nothing.
    assert b.spent_tokens == 0
    assert b.spent_micros == 0


@pytest.mark.security
@pytest.mark.invariant("FR-COST-04")
async def test_model_price_from_config_overrides_tier_default(tmp_path):
    prices = {"gpt-5-turbo": 3}

    # a model WITH an explicit price computes cost from it (3 micros/token),
    # ignoring the cost tier entirely.
    assert price_micros(100, "cheap", model="gpt-5-turbo", prices=prices) == 300
    assert price_micros(100, "expensive", model="gpt-5-turbo", prices=prices) == 300

    # a model WITHOUT an explicit price falls back to the tier default (unchanged
    # historical behaviour: cheap=1, standard=5, expensive=25).
    assert price_micros(100, "cheap", model="other-model", prices=prices) == 100
    assert price_micros(100, "standard", model="other-model", prices=prices) == 500
    assert price_micros(100, "expensive", model=None, prices=prices) == 2500

    # the CostAccountant carries the same table: model price wins over the tier.
    acct = CostAccountant(InMemoryStore(), prices=prices)
    assert acct.has_prices is True
    assert acct.price(100, "standard", model="gpt-5-turbo") == 300  # not 500
    assert acct.price(100, "standard", model="unpriced") == 500  # tier fallback

    # an accountant with no price table is pure tier fallback (existing behaviour).
    bare = CostAccountant(InMemoryStore())
    assert bare.has_prices is False
    assert bare.price(100, "standard", model="gpt-5-turbo") == 500

    # the price table is policy-as-data: it loads from the manifest (models.prices).
    manifest_yaml = (
        "organisation: Acme\n"
        "tenant_id: acme\n"
        "models:\n"
        "  endpoints:\n"
        "    - id: standard\n"
        "      kind: openai\n"
        "      model: gpt-5-turbo\n"
        "  prices:\n"
        "    gpt-5-turbo: 3\n"
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(manifest_yaml, encoding="utf-8")
    m = load_manifest(str(path))
    assert m.models.prices == {"gpt-5-turbo": 3}
