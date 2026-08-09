"""The distill adapter and promotion gates (decision 0023) - DIS-4..8.

The adapter talks to a local trainer sidecar; every test pins the OUTBOUND
contract with an ``httpx.MockTransport``, so what is asserted is what the
sidecar would actually receive.
"""

from __future__ import annotations

import json

import httpx
import pytest

from boltrig.distill.adapter import DistillAdapter
from boltrig.distill.gate import CaseScore, craft_verdict, register_verdict
from boltrig.kernel import Kernel
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    SchemaValidationError,
    TenantPermissions,
    utcnow,
)
from boltrig.store.memory import InMemoryStore

T = "acme"
PIN = "mlx-community/Qwen2.5-7B-Instruct-4bit@main"
DIGEST = "a" * 64


def _ctx(grants: list[str] | None = None, run_id: str = "run-1") -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(grants or ["distill.*"]),
        actor="operator",
        actor_tier="human",
        run_id=run_id,
    )


class _Sidecar:
    """Scripted sidecar: records every request, answers by route."""

    def __init__(
        self,
        *,
        base_pin: str = PIN,
        logliks: dict[str, float] | None = None,
        diversities: dict[str, float] | None = None,
    ):
        self.requests: list[tuple[str, str, dict]] = []
        self.base_pin = base_pin
        self.logliks = logliks or {}
        self.diversities = diversities or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        self.requests.append((request.method, request.url.path, body))
        if request.url.path == "/train":
            return httpx.Response(
                200, json={"adapter_id": "craft-acme-1", "base_pin": self.base_pin}
            )
        if request.url.path == "/loglik":
            return httpx.Response(
                200, json={"mean_loglik": self.logliks.get(body.get("model"), -2.0)}
            )
        if request.url.path == "/diversity":
            return httpx.Response(
                200, json={"distinct_2": self.diversities.get(body.get("model"), 0.5)}
            )
        return httpx.Response(200, json={"ok": True})


async def _kernel_with_adapter(
    sidecar: _Sidecar,
) -> tuple[Kernel, DistillAdapter, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    adapter = DistillAdapter(
        store,
        audit=kernel.audit,
        cost=kernel.cost,
        base_pin=PIN,
        base_url="http://127.0.0.1:8930",
        serve_url="http://127.0.0.1:8931/v1",
        transport=httpx.MockTransport(sidecar.handler),
    )
    await kernel.register_adapter(T, adapter)
    return kernel, adapter, store


async def _candidate_endpoint(store: InMemoryStore, *, active: bool = False) -> None:
    await store.upsert_model_endpoint(
        ModelEndpoint(
            id="craft-acme-1", tenant_id=T, kind="openai", model="craft-acme-1",
            base_url="http://127.0.0.1:8930/v1", data_class="sensitive",
            is_active=active,
        )
    )
    if not active:
        await store.set_model_endpoint_active(T, "craft-acme-1", False)


@pytest.mark.invariant("DIS-4")
async def test_train_schema_has_no_field_to_name_another_base():
    sidecar = _Sidecar()
    kernel, _, _ = await _kernel_with_adapter(sidecar)
    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "distill", "distill.train",
            {"corpus_digest": DIGEST, "adapter_kind": "craft",
             "base": "yesterdays-adapter"},
            _ctx(),
        )
    assert sidecar.requests == []  # refused before anything left the kernel


@pytest.mark.invariant("DIS-4")
async def test_train_request_carries_the_composed_pin_and_refuses_drift():
    sidecar = _Sidecar()
    _, adapter, _ = await _kernel_with_adapter(sidecar)
    result = await adapter.execute(
        "distill.train", {"corpus_digest": DIGEST, "adapter_kind": "craft"},
        None, _ctx(),
    )
    assert result.ok
    (method, path, body) = sidecar.requests[0]
    assert (method, path) == ("POST", "/train")
    assert body["base_pin"] == PIN  # the composed pin, not caller input
    assert set(body) == {"corpus_digest", "adapter_kind", "base_pin"}

    drifted = _Sidecar(base_pin="some-prior-adapter")
    _, adapter2, _ = await _kernel_with_adapter(drifted)
    result = await adapter2.execute(
        "distill.train", {"corpus_digest": DIGEST, "adapter_kind": "craft"},
        None, _ctx(),
    )
    assert not result.ok
    assert "base other than the composed pin" in result.error.message


@pytest.mark.invariant("DIS-5")
async def test_promote_without_a_passing_gate_receipt_is_refused():
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _candidate_endpoint(store)
    result = await adapter.execute(
        "distill.promote",
        {"endpoint_id": "craft-acme-1", "corpus_digest": DIGEST,
         "price_micros_per_token": 0.0},
        None, _ctx(),
    )
    assert not result.ok
    endpoint = await store.get_model_endpoint(T, "craft-acme-1")
    assert endpoint.is_active is False  # no receipt, no seat


@pytest.mark.invariant("DIS-5")
async def test_promote_flips_active_only_with_a_matching_receipt():
    sidecar = _Sidecar(logliks={"incumbent": -2.0, "craft-acme-1": -1.5})
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _candidate_endpoint(store)
    gate = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "register",
         "candidate_model": "craft-acme-1", "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    assert gate.ok and gate.output["promote"] is True
    result = await adapter.execute(
        "distill.promote",
        {"endpoint_id": "craft-acme-1", "corpus_digest": DIGEST,
         "price_micros_per_token": 0.05},
        None, _ctx(),
    )
    assert result.ok
    endpoint = await store.get_model_endpoint(T, "craft-acme-1")
    assert endpoint.is_active is True


@pytest.mark.invariant("DIS-5")
async def test_a_holding_gate_receipt_does_not_authorise_promotion():
    sidecar = _Sidecar(logliks={"incumbent": -1.5, "craft-acme-1": -2.0})
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _candidate_endpoint(store)
    gate = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "register",
         "candidate_model": "craft-acme-1", "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    assert gate.ok and gate.output["promote"] is False
    result = await adapter.execute(
        "distill.promote",
        {"endpoint_id": "craft-acme-1", "corpus_digest": DIGEST,
         "price_micros_per_token": 0.0},
        None, _ctx(),
    )
    assert not result.ok
    endpoint = await store.get_model_endpoint(T, "craft-acme-1")
    assert endpoint.is_active is False


@pytest.mark.invariant("DIS-6")
def test_craft_verdict_holds_on_case_regression_even_with_higher_mean():
    incumbent = [CaseScore("a", True, 0.5), CaseScore("b", True, 0.5)]
    candidate = [CaseScore("a", True, 1.0), CaseScore("b", False, 0.9)]
    verdict = craft_verdict(incumbent, candidate)
    assert verdict.promote is False
    assert verdict.reason == "case_regression"
    assert verdict.regressed_cases == ("b",)


@pytest.mark.invariant("DIS-6")
def test_craft_verdict_promotes_on_equal_mean_without_regression():
    incumbent = [CaseScore("a", True, 0.5), CaseScore("b", False, 0.5)]
    candidate = [CaseScore("a", True, 0.5), CaseScore("b", False, 0.5)]
    assert craft_verdict(incumbent, candidate).promote is True
    below = [CaseScore("a", True, 0.4), CaseScore("b", False, 0.4)]
    assert craft_verdict(incumbent, below).reason == "mean_below_incumbent"


def test_register_verdict_holds_on_a_tie():
    assert register_verdict(-2.0, -2.0).promote is False
    assert register_verdict(-2.0, -1.9).promote is True


@pytest.mark.invariant("DIS-7")
async def test_gate_writes_a_receipt_on_hold_and_on_promote():
    for logliks, status in (
        ({"incumbent": -2.0, "cand": -1.0}, "distill_gate_promote"),
        ({"incumbent": -1.0, "cand": -2.0}, "distill_gate_hold"),
    ):
        sidecar = _Sidecar(logliks=logliks)
        _, adapter, store = await _kernel_with_adapter(sidecar)
        result = await adapter.execute(
            "distill.gate",
            {"corpus_digest": DIGEST, "adapter_kind": "register",
             "candidate_model": "cand", "incumbent_model": "incumbent"},
            None, _ctx(),
        )
        assert result.ok
        rows = [
            e for e in await store.audit_query(T, limit=50)
            if e.verb == "distill.gate"
        ]
        assert [e.status for e in rows] == [status]
        detail = rows[0].detail
        assert detail["corpus_digest"] == DIGEST
        assert detail["base_pin"] == PIN
        assert {"incumbent_score", "candidate_score", "reason"} <= set(detail)


@pytest.mark.invariant("DIS-8")
async def test_promotion_prices_the_model_in_the_same_act():
    sidecar = _Sidecar(logliks={"incumbent": -2.0, "craft-acme-1": -1.0})
    kernel, adapter, store = await _kernel_with_adapter(sidecar)
    await _candidate_endpoint(store)
    await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "register",
         "candidate_model": "craft-acme-1", "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    # before promotion the model prices at the tier default ($5/M => 5_000_000
    # micros for a million tokens) - the trap DIS-8 exists to close
    assert kernel.cost.price(1_000_000, "standard", model="craft-acme-1") == 5_000_000
    result = await adapter.execute(
        "distill.promote",
        {"endpoint_id": "craft-acme-1", "corpus_digest": DIGEST,
         "price_micros_per_token": 0.05},
        None, _ctx(),
    )
    assert result.ok
    assert kernel.cost.price(1_000_000, "standard", model="craft-acme-1") == 50_000
    promote_rows = [
        e for e in await store.audit_query(T, limit=50)
        if e.status == "distill_promote"
    ]
    assert len(promote_rows) == 1
    assert promote_rows[0].detail["price_micros_per_token"] == 0.05


async def test_craft_gate_without_eval_runner_degrades_typed():
    sidecar = _Sidecar()
    _, adapter, _ = await _kernel_with_adapter(sidecar)
    result = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "craft",
         "candidate_model": "cand", "incumbent_model": "inc"},
        None, _ctx(),
    )
    assert not result.ok
    assert "eval runner" in result.error.message


async def test_craft_gate_refuses_a_tenant_with_no_eval_cases():
    sidecar = _Sidecar()
    _, adapter, _ = await _kernel_with_adapter(sidecar)
    adapter.set_eval(object())  # bound, but there is nothing to score with
    result = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "craft",
         "candidate_model": "cand", "incumbent_model": "inc"},
        None, _ctx(),
    )
    assert not result.ok
    assert "no active eval cases" in result.error.message


async def test_corpus_build_refuses_a_standard_classed_target():
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await store.upsert_model_endpoint(
        ModelEndpoint(id="remote", tenant_id=T, kind="anthropic",
                      model="claude", data_class="standard")
    )
    result = await adapter.execute(
        "distill.corpus.build", {"target_endpoint_id": "remote"}, None, _ctx(),
    )
    assert not result.ok
    assert "sensitive" in result.error.message
    assert sidecar.requests == []  # nothing shipped


async def test_corpus_build_ships_jsonl_keyed_by_digest():
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await store.upsert_model_endpoint(
        ModelEndpoint(id="local", tenant_id=T, kind="openai", model="base",
                      base_url="http://127.0.0.1:8930/v1", data_class="sensitive")
    )
    result = await adapter.execute(
        "distill.corpus.build", {"target_endpoint_id": "local"}, None, _ctx(),
    )
    assert result.ok
    (method, path, body) = sidecar.requests[0]
    assert method == "PUT"
    assert path == f"/corpus/{result.output['digest']}"
    header = json.loads(body["jsonl"].splitlines()[0])
    assert header["base_pin"] == PIN


async def test_gate_receipt_is_scoped_to_digest_and_model():
    """A receipt for one (digest, model) never promotes another."""
    sidecar = _Sidecar(logliks={"incumbent": -2.0, "craft-acme-1": -1.0})
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _candidate_endpoint(store)
    # a passing receipt for a DIFFERENT digest
    await store.audit_append(
        AuditEvent(
            tenant_id=T, ts=utcnow(), actor="operator",
            action_type=ActionType.MODEL_CALL, status="distill_gate_promote",
            verb="distill.gate",
            detail={"corpus_digest": "b" * 64, "candidate": "craft-acme-1"},
        )
    )
    result = await adapter.execute(
        "distill.promote",
        {"endpoint_id": "craft-acme-1", "corpus_digest": DIGEST,
         "price_micros_per_token": 0.0},
        None, _ctx(),
    )
    assert not result.ok
    endpoint = await store.get_model_endpoint(T, "craft-acme-1")
    assert endpoint.is_active is False


async def _seed_clean_turn(store: InMemoryStore) -> None:
    from boltrig.models import Conversation, ConversationMessage, MessageRole, User

    await store.upsert_user(User(id="u1", tenant_id=T))
    await store.create_conversation(Conversation(id="c1", tenant_id=T, user_id="u1"))
    await store.add_message(ConversationMessage(
        id="m1", conversation_id="c1", tenant_id=T,
        role=MessageRole.USER, content="draft the note"))
    await store.add_message(ConversationMessage(
        id="m2", conversation_id="c1", tenant_id=T,
        role=MessageRole.ASSISTANT, content="here is the note", run_id="r-net"))
    await store.audit_append(AuditEvent(
        tenant_id=T, ts=utcnow(), actor="agent", actor_tier="ephemeral",
        action_type=ActionType.TOOL_CALL, verb="ticket.create", status="ok",
        run_id="r-net"))


async def test_night_runs_the_chain_and_never_promotes_by_default():
    """distill.night = build -> ship -> train -> gate, promotion left to its
    own high-consequence verb (a passing gate only leaves the receipt)."""
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _seed_clean_turn(store)
    await store.upsert_model_endpoint(
        ModelEndpoint(id="craft-candidate", tenant_id=T, kind="openai",
                      model="craft-acme-1", base_url="http://127.0.0.1:8930/v1",
                      data_class="sensitive")
    )
    await store.set_model_endpoint_active(T, "craft-candidate", False)
    # the mock scores the trained candidate above the incumbent
    sidecar.logliks = {"incumbent": -2.0, "craft-acme-1": -1.0}
    result = await adapter.execute(
        "distill.night",
        {"target_endpoint_id": "craft-candidate", "adapter_kind": "register",
         "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    assert result.ok
    assert result.output["gate"]["promote"] is True
    assert result.output["promoted"] is False  # receipt only, no seat
    endpoint = await store.get_model_endpoint(T, "craft-candidate")
    assert endpoint.is_active is False
    # the chain actually ran: corpus shipped, train and loglik hit the sidecar
    paths = [p for _, p, _ in sidecar.requests]
    assert any(p.startswith("/corpus/") for p in paths)
    assert "/train" in paths and "/loglik" in paths


async def test_night_with_auto_promote_flips_the_endpoint_on_a_pass():
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await _seed_clean_turn(store)
    await store.upsert_model_endpoint(
        ModelEndpoint(id="craft-candidate", tenant_id=T, kind="openai",
                      model="craft-acme-1", base_url="http://127.0.0.1:8930/v1",
                      data_class="sensitive")
    )
    await store.set_model_endpoint_active(T, "craft-candidate", False)
    sidecar.logliks = {"incumbent": -2.0, "craft-acme-1": -1.0}
    result = await adapter.execute(
        "distill.night",
        {"target_endpoint_id": "craft-candidate", "adapter_kind": "register",
         "incumbent_model": "incumbent", "auto_promote": True,
         "price_micros_per_token": 0.0},
        None, _ctx(),
    )
    assert result.ok and result.output["promoted"] is True
    endpoint = await store.get_model_endpoint(T, "craft-candidate")
    assert endpoint.is_active is True


async def test_night_on_an_empty_day_is_a_quiet_night():
    """No corpus records => no training run that fails three steps later; the
    night reports empty_corpus and touches neither the trainer nor the gate."""
    sidecar = _Sidecar()
    _, adapter, store = await _kernel_with_adapter(sidecar)
    await store.upsert_model_endpoint(
        ModelEndpoint(id="craft-candidate", tenant_id=T, kind="openai",
                      model="craft-acme-1", base_url="http://127.0.0.1:8930/v1",
                      data_class="sensitive")
    )
    result = await adapter.execute(
        "distill.night",
        {"target_endpoint_id": "craft-candidate", "adapter_kind": "register",
         "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    assert result.ok
    assert result.output["reason"] == "empty_corpus"
    paths = [p for _, p, _ in sidecar.requests]
    assert "/train" not in paths and "/loglik" not in paths


async def test_craft_gate_without_serve_url_refuses_typed():
    """The trainer sidecar serves no chat completions; a craft gate without a
    distill.serve_url must refuse typed, not route eval traffic at a dead URL."""
    sidecar = _Sidecar()
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    adapter = DistillAdapter(
        store, audit=kernel.audit, cost=kernel.cost, base_pin=PIN,
        base_url="http://127.0.0.1:8930",  # serve_url deliberately unset
        transport=httpx.MockTransport(sidecar.handler),
    )
    await kernel.register_adapter(T, adapter)
    adapter.set_eval(object())
    result = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "craft",
         "candidate_model": "cand", "incumbent_model": "inc"},
        None, _ctx(),
    )
    assert not result.ok
    assert "serve_url" in result.error.message


@pytest.mark.invariant("DIS-9")
def test_register_verdict_holds_on_entropy_collapse_despite_better_likelihood():
    """A likelihood win bought by collapsing onto a template is a hold: the
    candidate fits the accepted turns better AND generates with less than the
    diversity floor of the incumbent's distinct-2."""
    verdict = register_verdict(
        -3.0, -1.0, incumbent_diversity=0.60, candidate_diversity=0.40
    )
    assert verdict.promote is False
    assert verdict.reason == "entropy_collapse"
    # at the floor exactly (0.8 x 0.60 = 0.48) the candidate survives
    ok = register_verdict(
        -3.0, -1.0, incumbent_diversity=0.60, candidate_diversity=0.48
    )
    assert ok.promote is True


@pytest.mark.invariant("DIS-9")
async def test_register_gate_fetches_diversity_and_holds_on_collapse():
    sidecar = _Sidecar(
        logliks={"incumbent": -2.0, "cand": -1.0},        # candidate fits better...
        diversities={"incumbent": 0.6, "cand": 0.3},      # ...by collapsing
    )
    _, adapter, store = await _kernel_with_adapter(sidecar)
    result = await adapter.execute(
        "distill.gate",
        {"corpus_digest": DIGEST, "adapter_kind": "register",
         "candidate_model": "cand", "incumbent_model": "incumbent"},
        None, _ctx(),
    )
    assert result.ok
    assert result.output["promote"] is False
    assert result.output["reason"] == "entropy_collapse"
    # the receipt carries both diversity measurements (DIS-7 receipt shape)
    rows = [e for e in await store.audit_query(T, limit=50) if e.verb == "distill.gate"]
    assert rows[0].detail["incumbent_diversity"] == 0.6
    assert rows[0].detail["candidate_diversity"] == 0.3
