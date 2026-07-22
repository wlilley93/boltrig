"""Channel addressing (decision 0003, Phase 2; SEC-178): an inbound message
carries a TARGET - routing data, never authority. The default is the tier-1
chief of staff ("cos", today's behaviour); a verified sender or the channel's
config mapping can address a named tier-2 subagent/run instead. Identity stays
kernel-authoritative via the binding rows; the work item also carries the
reply route (channel + thread + sender) for round-trip delivery.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.base import Result, VerbSpec
from boltrig.adapters.builtin.inbound_webhook import (
    canonical_body,
    expected_signature,
    signed_content,
)
from boltrig.fleet import WorkPump, build_spawner
from boltrig.fleet.authority import context_for
from boltrig.fleet.hatchet_app import register_boltrig_tasks
from boltrig.fleet.pump import workflow_target_id
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    Channel,
    ChannelBinding,
    GrantSet,
    TenantPermissions,
    User,
    WorkflowDefinition,
    WorkflowSource,
    WorkStatus,
)
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "addrsec_test_123"


async def _kernel(channel_config: dict | None = None) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-a1", tenant_id=T, platform="slack", name="Ops", transport="socket",
                credential_ref="cred-1",
                config={"sender_field": "sender", **(channel_config or {})})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-a1", platform="slack",
                       external_user_id="U-9", subject="alice", role="member")
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _intake(client: TestClient, n: int, **fields) -> None:
    payload = {"sender": "U-9", "type": "message", "text": "hi", "id": f"evt-{n}", **fields}
    r = client.post("/v1/channels/ch-a1/inbound", json=payload, headers=_signed(payload))
    assert r.status_code == 202, r.text


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_intake_defaults_to_the_tier1_chief_of_staff():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    _intake(c, 1)
    (item,) = [w for w in asyncio.run(store.list_work_items(T)) if w.on_behalf_of == "alice"]
    # unconfigured channel: the CoS routes it (unchanged pre-Phase-2 behaviour)
    assert item.target == "cos"
    # the reply route is the way BACK: same channel, no thread, the sender
    assert item.reply_route == {"channel_id": "ch-a1", "thread": None, "sender": "U-9"}


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_an_explicit_target_addresses_a_tier2_subagent():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    _intake(c, 2, target="researcher")
    (item,) = [w for w in asyncio.run(store.list_work_items(T)) if w.on_behalf_of == "alice"]
    assert item.target == "researcher"


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_the_channel_config_maps_a_chat_to_a_target():
    config = {"addressing": {"routes": {"C-ops": "oncall"}, "default_target": "triage"}}
    kernel, store = asyncio.run(_kernel(config))
    c = _client(kernel)
    # a mapped chat addresses its pinned tier-2 target, and the thread is
    # captured on the reply route for the round trip
    _intake(c, 3, chat="C-ops")
    # an unmapped chat falls to the channel's default target
    _intake(c, 4, chat="C-random")
    # an explicit target beats the chat mapping; a malformed one is dropped to it
    _intake(c, 5, chat="C-ops", target="run-42")
    _intake(c, 6, chat="C-ops", target="not a valid slug!")
    items = {w.source_id or w.id: w for w in asyncio.run(store.list_work_items(T))}
    by_delivery = {w.raw.get("id"): w for w in items.values()}
    assert by_delivery["evt-3"].target == "oncall"
    assert by_delivery["evt-3"].reply_route["thread"] == "C-ops"
    assert by_delivery["evt-4"].target == "triage"
    assert by_delivery["evt-5"].target == "run-42"
    assert by_delivery["evt-6"].target == "oncall"


# --- SEC-178: a workflow:<wf_id> target executes the addressed workflow --------
_OBJ = {"type": "object"}


class _SpyAdapter:
    """A counting fake: each dispatch through the chokepoint is recorded."""

    id = "spy"
    version = "1"
    runtime = "script"

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(verb_id=v, noun_id="job", input_schema=_OBJ,
                     output_schema=_OBJ, consequence="low", description=v)
            for v in ("job.one", "job.two")
        ]

    async def execute(self, verb_id, params, credential, context) -> Result:
        self.calls[verb_id] = self.calls.get(verb_id, 0) + 1
        return Result.success({"verb": verb_id})


class _NeverRoutedCoS:
    async def route(self, item, context):
        raise AssertionError("cos.route must not be consulted for a workflow-addressed item")


async def _workflow_kernel(channel_config: dict) -> tuple[Kernel, InMemoryStore, _SpyAdapter]:
    kernel, store = await _kernel(channel_config)
    spy = _SpyAdapter()
    await kernel.register_adapter(T, spy)
    # The bound sender ("alice") holds ONLY job.one: the workflow's job.two step
    # must be denied - the address steers which workflow runs, never its authority.
    await store.upsert_user(User(
        id="alice", tenant_id=T, email="alice@example.com", role="member",
        scope={"verbs": ["job.one"]}, status="active",
    ))
    await store.upsert_workflow(WorkflowDefinition(
        id="wf-report", tenant_id=T, version="1", source=WorkflowSource.PRECREATED,
        definition={"steps": [
            {"id": "s1", "action": "job.one", "params": {}},
            {"id": "s2", "action": "job.two", "params": {}, "parents": ["s1"]},
        ]},
    ))
    return kernel, store, spy


def _workflow_pump(kernel: Kernel, executor: LocalDurableExecutor) -> WorkPump:
    register_boltrig_tasks(executor, kernel)
    return WorkPump(kernel, build_spawner(kernel), _NeverRoutedCoS(), {}, executor)


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
async def test_a_config_mapped_workflow_target_triggers_the_workflow():
    """A chat pinned to ``workflow:<wf_id>`` fires the named workflow through the
    durable trigger path - checkpointed, as the registered engine task - under the
    SENDER's grants: the step she holds runs (once), the step she lacks is denied.
    Addressing is routing data, never authority."""
    config = {"addressing": {"routes": {"C-deploy": "workflow:wf-report"}}}
    kernel, store, spy = await _workflow_kernel(config)
    pump = _workflow_pump(kernel, LocalDurableExecutor())
    c = _client(kernel)
    _intake(c, 10, chat="C-deploy")

    assert await pump.run_once(T) is True

    (item,) = [w for w in await store.list_work_items(T) if w.on_behalf_of == "alice"]
    assert item.target == "workflow:wf-report"
    assert item.status == WorkStatus.DONE
    assert item.result["workflow"]["workflow_id"] == "wf-report"
    # effective authority, not a passed parameter: the granted step dispatched
    # exactly once through the chokepoint; the ungranted one never executed.
    assert spy.calls == {"job.one": 1}
    ctx = await context_for(store, item, item.id)
    assert ctx.grants.permits("job.one") is True
    assert ctx.grants.permits("job.two") is False
    # the item records that it was workflow-addressed: route checkpoint + audit.
    cps = {cp.step: cp for cp in await store.list_checkpoints(T, item.id)}
    assert cps["route"].output == {"workflow": "wf-report"}
    triggers = [e for e in await store.audit_query(T) if e.verb == "workflow.trigger"]
    assert len(triggers) == 1
    assert triggers[0].on_behalf_of == "alice"
    assert triggers[0].detail["workflow"] == "wf-report"
    assert triggers[0].detail["work_item_id"] == item.id


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
async def test_an_unknown_workflow_target_parks_for_a_human():
    """Fail-closed symmetry with routing (SEC-165): an addressed workflow the
    tenant does not have parks the item AWAITING_HUMAN with a HITL filed - never
    a silent fallthrough to CoS routing (the CoS stub raises if consulted)."""
    kernel, store, _ = await _workflow_kernel({})
    pump = _workflow_pump(kernel, LocalDurableExecutor())
    c = _client(kernel)
    _intake(c, 11, target="workflow:no-such-wf")

    assert await pump.run_once(T) is True

    (item,) = [w for w in await store.list_work_items(T) if w.on_behalf_of == "alice"]
    assert item.status == WorkStatus.AWAITING_HUMAN
    pending = await store.list_pending_hitl(T)
    assert any(r.work_item_id == item.id for r in pending)
    cps = {cp.step: cp for cp in await store.list_checkpoints(T, item.id)}
    assert cps["route"].output == {"workflow": "no-such-wf", "error": "unknown_workflow"}


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_a_bare_workflow_prefix_is_not_a_workflow_target():
    """``workflow:`` with no id is not an addressing escape hatch: it resolves to
    no workflow target and falls through to ordinary routing like any other slug."""
    class _Item:
        target = "workflow:"

    assert workflow_target_id(_Item()) is None
