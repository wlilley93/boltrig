"""The delegated (pump) lane runs at the REQUESTING principal's authority (SEC-164/165).

The pump is the one spawn caller that used to build its execution context from the
TENANT permission ceiling, so any user able to file a work item that reached the pump
got a durable execution at the full tenant verb ceiling regardless of their role - a
vertical privilege escalation, since ``on_behalf_of`` was carried for audit but never
enforced. These tests pin the closed behaviour: authority comes from the principal the
item names, and is EMPTY when no principal can be identified. The tenant ceiling stays
the separate axis it always was, enforced independently at dispatch (US-IAM-04).

They assert on EFFECTIVE authority (what the child actually received, and what the
kernel chokepoint actually permits), never merely on a parameter being passed.
"""

from __future__ import annotations

import uuid

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet import ChiefOfStaff, Department, DepartmentHead, WorkPump, build_spawner
from boltrig.fleet.authority import context_for, principal_grants_for_item
from boltrig.fleet.pump import persist_new_work_items
from boltrig.kernel import Kernel
from boltrig.kernel.work_authority import (
    CREATOR_GRANT_CEILING_KEY,
    creator_ceiling_from_item,
    stamp_creator_ceiling,
)
from boltrig.models import (
    ActionType,
    AgentCapability,
    GrantMissing,
    GrantSet,
    Skill,
    TenantPermissions,
    User,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore

T = "acme"
DEPT = "engineering"
RISKY_VERB = "ticket.create"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    # The tenant ceiling is wide open: the ONLY thing that may narrow a run is the
    # requesting principal. This is exactly the condition the escalation lived in.
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 3, True, "cheap")
    )
    # A skill that DECLARES the risky grant. Under the bug this alone was enough to
    # hand the verb to any user's run, because the skill's grants were intersected
    # only against the tenant ceiling.
    await store.upsert_skill(
        Skill(
            id="risky",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="p",
            tool_grants=[RISKY_VERB],
            context_requirements={},
        )
    )
    return kernel


async def _seat(kernel: Kernel, user_id: str, scope: dict) -> None:
    await kernel.store.upsert_user(
        User(
            id=user_id,
            tenant_id=T,
            email=f"{user_id}@example.com",
            role="member",
            scope=scope,
            status="active",
        )
    )


def _pump(kernel: Kernel, *, heads: dict | None = None) -> WorkPump:
    spawner = build_spawner(kernel)
    if heads is None:
        heads = {DEPT: DepartmentHead(DEPT, ["risky"], [], 32, spawner=spawner, store=kernel.store)}
    cos = ChiefOfStaff(kernel, [Department(name=name) for name in heads])
    return WorkPump(kernel, spawner, cos, heads)


def _item(**kw) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4().hex,
        tenant_id=T,
        source="internal",
        intent="create a ticket",
        confidence=0.9,
        convergent=False,
        **kw,
    )


async def _run(kernel: Kernel, item: WorkItem) -> WorkItem:
    await kernel.store.create_work_item(item)
    assert await _pump(kernel).run_once(T) is True
    done = await kernel.store.get_work_item(T, item.id)
    assert done is not None
    return done


def _child_grants(item: WorkItem) -> set[str]:
    """The authority the spawned child ACTUALLY received (computed by the spawner)."""
    children = (item.result or {}).get("children") or []
    assert children, f"expected a spawned child, got result={item.result!r}"
    return set(children[0].get("effective_grants") or [])


# --- SEC-164: the escalation is CLOSED ---------------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_low_privilege_principals_item_cannot_execute_a_verb_it_lacks():
    """A low-privilege principal's work item does not get the risky verb, even though
    the selected skill declares it and the tenant ceiling permits it."""
    kernel = await _kernel()
    await _seat(kernel, "mallory", {"verbs": ["ticket.read"]})  # no ticket.create

    done = await _run(kernel, _item(on_behalf_of="mallory"))

    # effective authority, not a passed parameter: the child never received the verb
    assert RISKY_VERB not in _child_grants(done)

    # and the chokepoint actually refuses it under the item's real execution context
    ctx = await context_for(kernel.store, done, done.id)
    assert ctx.grants.permits(RISKY_VERB) is False
    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", RISKY_VERB, {"title": "escalated"}, ctx)


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_a_principal_holding_the_verb_still_gets_it():
    """The contrast case - without this the escalation test could pass vacuously
    (e.g. if the child simply never received any grant at all)."""
    kernel = await _kernel()
    await _seat(kernel, "alice", {"verbs": [RISKY_VERB]})

    done = await _run(kernel, _item(on_behalf_of="alice"))

    assert RISKY_VERB in _child_grants(done)
    ctx = await context_for(kernel.store, done, done.id)
    assert ctx.grants.permits(RISKY_VERB) is True
    await kernel.invoke("ticket", RISKY_VERB, {"title": "legitimate"}, ctx)  # no raise


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_a_tenant_wide_principal_is_still_bound_by_a_narrow_tenant_ceiling():
    """The two ceilings compose and BOTH bind. The tenant ceiling is a separate axis
    enforced at dispatch (US-IAM-04), so it is asserted here through real dispatch
    rather than through the context's grants."""
    kernel = await _kernel()
    kernel.store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["ticket.read"])))
    await _seat(kernel, "root", {"all": True})  # a tenant-wide principal

    item = _item(on_behalf_of="root")
    grants = await principal_grants_for_item(kernel.store, item)
    assert grants.permits(RISKY_VERB) is True  # the principal alone would allow it

    # ... but the tenant ceiling refuses it at the chokepoint anyway.
    ctx = await context_for(kernel.store, item, "run")
    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", RISKY_VERB, {"title": "over the ceiling"}, ctx)


# --- SEC-164: fail closed with no identified principal ------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-164")
@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"on_behalf_of": None}, "system-originated: names no principal"),
        ({"on_behalf_of": "ghost"}, "names a principal with no user record"),
    ],
)
async def test_an_unidentified_principal_carries_no_authority(kwargs, why):
    """Fail-closed (K-13): no identified principal means NO authority - never the
    tenant ceiling. An unidentified principal is not a tenant-wide principal."""
    kernel = await _kernel()
    item = _item(**kwargs)

    assert (await principal_grants_for_item(kernel.store, item)).allow == (), why
    ctx = await context_for(kernel.store, item, "run")
    assert ctx.grants.permits(RISKY_VERB) is False
    assert ctx.grants.allow == ()


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_a_deactivated_principal_carries_no_authority():
    """Deactivation revokes a work item's authority too (SEC-34), because the pump
    resolves through the same ``effective_grants_for_request`` the request path uses."""
    kernel = await _kernel()
    await kernel.store.upsert_user(
        User(
            id="ex",
            tenant_id=T,
            email="ex@example.com",
            role="member",
            scope={"all": True},
            status="deactivated",
        )
    )
    grants = await principal_grants_for_item(kernel.store, _item(on_behalf_of="ex"))
    assert grants.allow == ()


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_system_originated_item_still_completes_and_audits_on_behalf_of():
    """Fail-closed authority does not break the loop: a system item still runs, and
    the audit trail's on_behalf_of behaviour is unchanged (carried, never enforced-as-
    authority). It simply carries no verb authority while doing so."""
    kernel = await _kernel()
    done = await _run(kernel, _item(on_behalf_of=None))

    assert done.status == WorkStatus.DONE
    assert _child_grants(done) == set()  # ran, but with nothing granted
    spawns = [
        e for e in await kernel.store.audit_query(T) if e.action_type == ActionType.AGENT_SPAWN
    ]
    assert spawns and all(e.on_behalf_of is None for e in spawns)


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_on_behalf_of_is_still_carried_through_the_tree_and_the_audit():
    """The audit / provenance behaviour is unchanged by the fix: on_behalf_of still
    rides the context, the spawn audit row, and every child work item."""
    kernel = await _kernel()
    await _seat(kernel, "alice", {"verbs": [RISKY_VERB]})

    done = await _run(kernel, _item(on_behalf_of="alice", workspace_id="ws-1"))

    assert done.on_behalf_of == "alice" and done.workspace_id == "ws-1"
    kids = await kernel.store.list_work_items(T, parent_id=done.id)
    assert kids and all(k.on_behalf_of == "alice" and k.workspace_id == "ws-1" for k in kids)
    spawns = [
        e for e in await kernel.store.audit_query(T) if e.action_type == ActionType.AGENT_SPAWN
    ]
    assert spawns and all(e.on_behalf_of == "alice" for e in spawns)


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_creator_ceiling_survives_promotion_and_propagates_to_follow_on_work():
    """Queued work never acquires authority granted after it was created.

    The ceiling is server-stamped on the parent and replaces any reserved value a
    model tries to place in a follow-on payload. Descendants therefore remain no
    broader than the authority under which the original work was accepted.
    """
    kernel = await _kernel()
    await _seat(kernel, "alice", {"verbs": ["ticket.read"]})
    parent = _item(on_behalf_of="alice")
    stamp_creator_ceiling(parent, GrantSet.of(["ticket.read"]))
    await kernel.store.create_work_item(parent)

    # A later role change must not retroactively widen already-queued authority.
    await _seat(kernel, "alice", {"all": True})
    parent_context = await context_for(kernel.store, parent, parent.id)
    assert not parent_context.grants.permits(RISKY_VERB)

    (child,) = await persist_new_work_items(
        kernel.store,
        parent,
        [
            {
                "intent": "follow on",
                # Reserved authority-shaped model data is not a trusted stamp.
                CREATOR_GRANT_CEILING_KEY: {"allow": ["*"], "deny": []},
            }
        ],
        source="test",
    )
    assert creator_ceiling_from_item(child) == GrantSet.of(["ticket.read"])
    child_context = await context_for(kernel.store, child, child.id)
    assert not child_context.grants.permits(RISKY_VERB)


@pytest.mark.security
@pytest.mark.invariant("SEC-164")
async def test_malformed_creator_ceiling_fails_closed():
    kernel = await _kernel()
    await _seat(kernel, "alice", {"all": True})
    item = _item(on_behalf_of="alice")
    item.constraints[CREATOR_GRANT_CEILING_KEY] = {
        "allow": ["*"],
        "deny": "not-a-list",
    }

    context = await context_for(kernel.store, item, item.id)
    assert context.grants.allow == ()
    assert not context.grants.permits(RISKY_VERB)


# --- SEC-165: an unroutable department parks, never mis-routes ----------------
@pytest.mark.security
@pytest.mark.invariant("SEC-165")
async def test_an_unroutable_department_parks_instead_of_running_under_another_head():
    """A department with no head must NOT silently execute under a different head:
    the run's ``principal_scope`` claims ``owner_member``, so a mis-route would make
    the run's own scope claim untrue. Deterministic is not the same as correct."""
    kernel = await _kernel()
    spawner = build_spawner(kernel)

    class _UnroutableCoS:
        async def route(self, item, context):
            return "finance"  # a department the pump has no head for

    finance_head = DepartmentHead(DEPT, ["risky"], [], 32, spawner=spawner, store=kernel.store)
    pump = WorkPump(kernel, spawner, _UnroutableCoS(), {DEPT: finance_head})

    item = _item(on_behalf_of="alice")
    await kernel.store.create_work_item(item)
    assert await pump.run_once(T) is True

    parked = await kernel.store.get_work_item(T, item.id)
    assert parked is not None
    assert parked.status == WorkStatus.AWAITING_HUMAN  # parked, never mis-routed
    assert parked.owner_member != DEPT  # never adopted the wrong head's identity
    assert not await kernel.store.list_work_items(T, parent_id=item.id)  # nothing ran
    pending = await kernel.store.list_pending_hitl(T)
    assert any(r.work_item_id == item.id for r in pending)


# --- SEC-178: an addressed item routes to its named head -------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-178")
async def test_an_addressed_item_routes_to_its_named_head_not_the_inferred_one():
    """A work item carrying an explicit ``target`` (channel addressing) is routed
    to that head directly - the CoS's inferred route is never consulted. The
    target is routing data, not authority: grants still bind at the chokepoint."""
    kernel = await _kernel()
    await _seat(kernel, "will", {"verbs": [RISKY_VERB]})
    spawner = build_spawner(kernel)

    class _MisroutingCoS:
        async def route(self, item, context):
            raise AssertionError("cos.route must not be consulted for an addressed item")

    head = DepartmentHead(DEPT, ["risky"], [], 32, spawner=spawner, store=kernel.store)
    pump = WorkPump(kernel, spawner, _MisroutingCoS(), {DEPT: head})

    item = _item(on_behalf_of="will", target=DEPT)
    await kernel.store.create_work_item(item)
    assert await pump.run_once(T) is True

    done = await kernel.store.get_work_item(T, item.id)
    assert done is not None
    assert done.owner_member == DEPT
    assert done.status == WorkStatus.DONE


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
async def test_an_unknown_target_falls_back_to_the_inferred_route():
    """A target that names no configured head (and the tier-1 default "cos") is
    not an addressing escape hatch: the CoS routes as usual."""
    kernel = await _kernel()
    await _seat(kernel, "will", {"verbs": [RISKY_VERB]})
    spawner = build_spawner(kernel)

    class _RecordingCoS:
        def __init__(self):
            self.consulted = 0

        async def route(self, item, context):
            self.consulted += 1
            return DEPT

    cos = _RecordingCoS()
    head = DepartmentHead(DEPT, ["risky"], [], 32, spawner=spawner, store=kernel.store)
    pump = WorkPump(kernel, spawner, cos, {DEPT: head})

    for target in ("cos", "no-such-department"):
        item = _item(on_behalf_of="will", target=target)
        await kernel.store.create_work_item(item)
        assert await pump.run_once(T) is True
        done = await kernel.store.get_work_item(T, item.id)
        assert done is not None and done.status == WorkStatus.DONE
    assert cos.consulted == 2  # both fell through to the inferred route
