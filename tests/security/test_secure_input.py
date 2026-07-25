"""SEC-181 secure input: a governed "ask the human for a value the agent never
sees".

A ``chat.ask_user`` question with ``secure: true`` + a bounded ``purpose`` label
creates an ordinary QUESTION HITL carrying the secure marker, but its ANSWER
never enters the run: the shared answer path (hitl_http.answer_hitl_question)
seals the value through the credential seam as a run+purpose-scoped credential
(``run:<run_id>:<purpose>``, envelope-sealed at rest) and records the enveloped
REFERENCE (``credential:run/<run_id>/<purpose>``) as the decision, so the
ordinary resume wiring replays the reference. A verb param holding that
reference is resolved to the material INSIDE the kernel at the dispatch
resolve-credential stage - the adapter receives the material; the agent, the
run events and the audit only ever carried the reference. Resolution is scoped:
another run's or purpose's reference fails closed (CredentialResolution).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.credentials import run_scoped_cred_id
from boltrig.kernel.questions import QUESTIONS_VERB, register_questions_verb
from boltrig.models import (
    CredentialResolution,
    GrantSet,
    HITLType,
    InvocationContext,
    PendingHuman,
    SchemaValidationError,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed

T = "acme"
SECRET = "https://hooks.slack.test/services/T0/B0/s3cr3t-secure-value-zzz"
PURPOSE = "slack-webhook-destination"
REFERENCE = f"credential:run/r1/{PURPOSE}"


class SpyAdapter:
    """Records the exact params it was handed at execute time."""

    id = "spy"
    version = "1.0.0"
    runtime = "script"

    def __init__(self) -> None:
        self.seen: list[dict] = []

    def describe(self):
        return [
            VerbSpec(
                verb_id="spy.send",
                noun_id="spy",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            )
        ]

    async def execute(self, verb, params, credential, context):
        self.seen.append(dict(params))
        return Result.success({"ok": True})

    async def health(self):
        return "ok"


# The run this material was sealed for belongs to a user, and only that user
# resolves it (credentials._owner_matches). "alice" is the owner the HTTP leg
# of these tests answers as, so the direct-kernel contexts use it too.
OWNER = "alice"


def _ctx(
    grants: list[str], *, run_id: str | None = "r1", owner: str | None = OWNER
) -> InvocationContext:
    return InvocationContext(
        tenant_id=T, grants=GrantSet.of(grants), actor="agent", run_id=run_id,
        on_behalf_of=owner,
    )


async def _kernel() -> tuple[InMemoryStore, Kernel, SpyAdapter]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    spy = SpyAdapter()
    await k.register_adapter(T, spy)
    await register_questions_verb(k.store, T)
    return store, k, spy


async def _seed_secure_question(k: Kernel) -> str:
    """Raise a secure QUESTION on run r1 (owned by alice); return the request id."""
    await k.store.create_work_item(WorkItem(
        id="r1", tenant_id=T, source="chat", intent="x", confidence=1.0,
        convergent=False, status=WorkStatus.IN_FLIGHT,
        owner_member="chief-of-staff", hatchet_run_id="r1", on_behalf_of="alice",
    ))
    with pytest.raises(PendingHuman) as pending:
        await k.invoke("chat", QUESTIONS_VERB, {
            "prompt": "Paste the Slack webhook URL",
            "secure": True, "purpose": PURPOSE,
        }, _ctx(["chat.*"]))
    return pending.value.hitl_request_id


def _hdr(subject: str, role: str = "engineer") -> dict[str, str]:
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject,
            "x-boltrig-role": role, "x-boltrig-tier": "human"}


# --------------------------------------------------------------------------- #
# secure ask -> answer: value sealed at rest, run resumes with the reference
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
def test_secure_answer_is_sealed_and_the_run_carries_only_the_reference():
    store, k, _ = asyncio.run(_kernel())
    fired: list[str] = []
    k.hitl.set_resume_notifier(lambda req: fired.append(req.id))
    qid = asyncio.run(_seed_secure_question(k))

    # the QUESTION carries the secure marker, and both run-stream projections
    # (the question event and the hitl pause event) flag it for consumers
    req = asyncio.run(k.hitl.get(T, qid))
    assert req.type == HITLType.QUESTION
    assert req.secure is True and req.secure_purpose == PURPOSE
    events = k.events.snapshot(T, "r1")
    q_events = [e for e in events if e["type"] == "question"]
    hitl_events = [e for e in events if e["type"] == "hitl"]
    assert q_events and q_events[0]["secure"] is True
    assert q_events[0]["purpose"] == PURPOSE
    assert hitl_events and hitl_events[0]["secure"] is True

    # the list projection marks it too (additive; a secure-input affordance)
    client = TestClient(create_app(k))
    listed = client.get("/v1/hitl", headers=_hdr("alice"))
    rows = [r for r in listed.json()["requests"] if r["id"] == qid]
    assert rows and rows[0]["secure"] is True
    assert rows[0]["secure_purpose"] == PURPOSE

    # the owner answers with the secret value
    r = client.post(f"/v1/hitl/{qid}/answer", json={"answer": SECRET},
                    headers=_hdr("alice"))
    assert r.status_code == 200
    # no echo: the value appears nowhere in the answer response body
    assert SECRET not in json.dumps(r.json())

    # the recorded decision (what the resume wiring replays into the run) is
    # the enveloped REFERENCE, never the value
    resp = asyncio.run(store.get_hitl_response(T, qid))
    assert resp is not None
    assert REFERENCE in resp.decision
    assert resp.decision.startswith('<untrusted kind="user_answer"')
    assert SECRET not in resp.decision
    assert fired == [qid]  # the ordinary resume wiring fired

    # the value rests ONLY behind the sealed credential seam: the raw store row
    # is an envelope holding no plaintext
    raw = store._creds[(T, run_scoped_cred_id("r1", PURPOSE))]
    assert is_sealed(raw)
    assert SECRET not in json.dumps(raw)
    # ... and unseals kernel-side to exactly the submitted value
    unsealed = asyncio.run(store.get_credential_ref(T, run_scoped_cred_id("r1", PURPOSE)))
    assert unsealed["value"] == SECRET
    assert unsealed["run_id"] == "r1" and unsealed["purpose"] == PURPOSE

    # no echo in audit either: the answer audit row carries the secure marker,
    # not even the answer length; no audit detail holds the value anywhere
    rows = asyncio.run(store.audit_query(T, limit=50))
    ans = [e for e in rows if e.verb == "hitl.question.answer"]
    assert ans and ans[0].detail.get("secure") is True
    assert "answer_len" not in ans[0].detail
    assert SECRET not in json.dumps([e.detail for e in rows])
    # and the run stream never saw the value
    assert SECRET not in json.dumps(k.events.snapshot(T, "r1"))


# --------------------------------------------------------------------------- #
# a verb param carrying the reference resolves at the dispatch credential stage
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_reference_resolves_to_material_at_dispatch_events_keep_reference():
    store, k, spy = await _kernel()
    reference = await k.credentials.seal_run_scoped_value(T, "r1", PURPOSE, SECRET, OWNER)
    assert reference == REFERENCE

    out = await k.invoke("spy", "spy.send", {
        "url": reference,
        "tags": ["static", reference],  # nested references resolve too
    }, _ctx(["spy.*"]))
    assert out == {"ok": True}
    # the adapter received the MATERIAL, top-level and nested
    assert spy.seen == [{"url": SECRET, "tags": ["static", SECRET]}]

    # the agent-authored params, the run events and the audit only ever carried
    # the reference
    blob = json.dumps(k.events.snapshot(T, "r1"))
    assert reference in blob and SECRET not in blob
    rows = await store.audit_query(T, limit=50)
    assert SECRET not in json.dumps([e.detail for e in rows])


# --------------------------------------------------------------------------- #
# fail-closed scoping: another run, another purpose, a tampered or foreign row
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_cross_run_and_cross_purpose_resolution_fails_closed():
    store, k, spy = await _kernel()
    await k.credentials.seal_run_scoped_value(T, "r1", PURPOSE, SECRET, OWNER)

    # a reference from ANOTHER run never resolves in this run
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send", {"url": REFERENCE},
                       _ctx(["spy.*"], run_id="r2"))
    # ... and a run-less context can never resolve a run-scoped reference
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send", {"url": REFERENCE},
                       _ctx(["spy.*"], run_id=None))
    # a purpose the run never sealed has no row behind it
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send",
                       {"url": "credential:run/r1/other-purpose"}, _ctx(["spy.*"]))
    # a tampered row (id says one purpose, the sealed payload says another)
    # fails closed on the mismatch
    await store.set_credential_ref(T, run_scoped_cred_id("r1", "p-tampered"), {
        "kind": "secure_answer", "run_id": "r1", "purpose": PURPOSE, "value": "x",
    })
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send",
                       {"url": "credential:run/r1/p-tampered"}, _ctx(["spy.*"]))
    # a FOREIGN credential that merely sits under a run: id is not a secure
    # answer and never resolves as one
    await store.set_credential_ref(T, run_scoped_cred_id("r1", "p-foreign"),
                                   {"secret": "not-a-secure-answer"})
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send",
                       {"url": "credential:run/r1/p-foreign"}, _ctx(["spy.*"]))

    assert spy.seen == []  # no failing call ever reached the adapter
    # the failed resolutions are still audited (audit-always), value-free
    rows = await store.audit_query(T, limit=50)
    failures = [e for e in rows if e.status == "credential_resolution_failed"]
    assert len(failures) == 5
    assert SECRET not in json.dumps([e.detail for e in rows])


# --------------------------------------------------------------------------- #
# lifecycle: the documented run-settle sweep removes a run's secure credentials
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_sweep_removes_only_the_finished_runs_secure_credentials():
    store, k, spy = await _kernel()
    await k.credentials.seal_run_scoped_value(T, "r1", PURPOSE, SECRET, OWNER)
    await k.credentials.seal_run_scoped_value(T, "r1", "second-purpose", "v2", OWNER)
    await k.credentials.seal_run_scoped_value(T, "r2", PURPOSE, "other-run", OWNER)

    assert await k.credentials.sweep_run_scoped(T, "r1") == 2
    # r1's references are gone: resolution now fails closed
    with pytest.raises(CredentialResolution):
        await k.invoke("spy", "spy.send", {"url": REFERENCE}, _ctx(["spy.*"]))
    # another run's credentials are untouched and still resolve for that run
    out = await k.invoke("spy", "spy.send", {"url": "credential:run/r2/" + PURPOSE},
                         _ctx(["spy.*"], run_id="r2"))
    assert out == {"ok": True}
    assert spy.seen[-1]["url"] == "other-run"


# --------------------------------------------------------------------------- #
# schema pairing: secure requires purpose; purpose only allowed with secure
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
@pytest.mark.parametrize("params", [
    {"prompt": "x", "secure": True},                             # missing purpose
    {"prompt": "x", "purpose": PURPOSE},                         # purpose w/o secure
    {"prompt": "x", "secure": False, "purpose": PURPOSE},        # purpose w/o secure
    {"prompt": "x", "secure": True, "purpose": "bad/purpose"},   # unsafe label
    {"prompt": "x", "secure": True, "purpose": ""},              # empty label
])
async def test_secure_purpose_pairing_fails_schema_validation(params):
    _, k, _ = await _kernel()
    with pytest.raises(SchemaValidationError):
        await k.invoke("chat", QUESTIONS_VERB, params, _ctx(["chat.*"]))


# --------------------------------------------------------------------------- #
# a non-secure question behaves exactly as before (no marker, plain answer path)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-181")
def test_non_secure_ask_user_is_unchanged():
    store, k, _ = asyncio.run(_kernel())
    fired: list[str] = []
    k.hitl.set_resume_notifier(lambda req: fired.append(req.id))

    async def ask() -> str:
        await store.create_work_item(WorkItem(
            id="r1", tenant_id=T, source="chat", intent="x", confidence=1.0,
            convergent=False, status=WorkStatus.IN_FLIGHT,
            owner_member="chief-of-staff", hatchet_run_id="r1", on_behalf_of="alice",
        ))
        with pytest.raises(PendingHuman) as pending:
            await k.invoke("chat", QUESTIONS_VERB,
                           {"prompt": "Which region?"}, _ctx(["chat.*"]))
        return pending.value.hitl_request_id

    qid = asyncio.run(ask())
    req = asyncio.run(k.hitl.get(T, qid))
    assert req.secure is False and req.secure_purpose is None
    q_events = [e for e in k.events.snapshot(T, "r1") if e["type"] == "question"]
    assert q_events and "secure" not in q_events[0]  # marker only when secure

    client = TestClient(create_app(k))
    answer = "eu-west plain text"
    r = client.post(f"/v1/hitl/{qid}/answer", json={"answer": answer},
                    headers=_hdr("alice"))
    assert r.status_code == 200
    resp = asyncio.run(store.get_hitl_response(T, qid))
    assert answer in resp.decision  # ordinary answers are recorded as before
    assert "credential:run/" not in resp.decision
    rows = asyncio.run(store.audit_query(T, limit=50))
    ans = [e for e in rows if e.verb == "hitl.question.answer"]
    assert ans and ans[0].detail.get("answer_len") == len(answer)
    assert not hasattr(store, "_creds") or not any(
        key[1].startswith("run:r1:") for key in store._creds
    )  # no credential was sealed for a plain answer
