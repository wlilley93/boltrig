"""Drive session distillation through the REAL governed write, not just selection.

Why this file exists. On 2026-07-30 six unit tests covered SELECTION - idle
window, deleted-thread exclusion, idempotency - and all six were green while the
feature failed on EVERY thread in the deployment:

    GrantMissing: cannot write memory to scope user:will.lilley93@gmail.com

The seat was one generic system context with no ``on_behalf_of``. Memory RBAC
derives the permitted owner scopes from that field, so a context with no
principal has no scopes and is refused for every user. Selection tests could
never see it, because they stop short of ``kernel.invoke``.

So this drives the chokepoint: a real Kernel, the real memory adapter, the real
verb. It is the test whose absence let a live deployment fail silently for a
whole sweep interval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from boltrig.kernel import Kernel
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.memory.session_distillation import (
    already_distilled,
    distil_conversation,
    distillation_context,
)
from boltrig.models import GrantSet, TenantPermissions
from boltrig.models.conversation import Conversation, ConversationMessage, MessageRole
from boltrig.store import InMemoryStore

T = "t-distil-write"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
OWNER = "alice@example.com"


async def _kernel_with_memory() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_memory_adapter(
            LocalMemoryEngine(), kernel.store, audit=kernel.audit, config={}
        ),
    )
    return kernel


async def _thread(kernel: Kernel, conv_id: str, owner: str = OWNER) -> Conversation:
    conv = Conversation(
        id=conv_id,
        tenant_id=T,
        user_id=owner,
        title="a quiet thread",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(minutes=90),
    )
    kernel.store._convs[(T, conv_id)] = conv
    for i, (role, text) in enumerate(
        [(MessageRole.USER, "how do I file a claim"), (MessageRole.ASSISTANT, "use form B")]
    ):
        await kernel.store.add_message(
            ConversationMessage(
                id=f"{conv_id}-m{i}",
                conversation_id=conv_id,
                tenant_id=T,
                role=role,
                content=text,
            )
        )
    return conv


@pytest.mark.invariant("SEC-42")
async def test_distillation_writes_through_the_governed_verb():
    """The whole point: a fact lands, in the OWNER's scope, and it was audited."""
    kernel = await _kernel_with_memory()
    conv = await _thread(kernel, "c1")

    wrote = await distil_conversation(
        kernel, T, conv, distillation_context(T, conv.user_id)
    )
    assert wrote is True

    facts = await kernel.store.list_memory_facts(T, [f"user:{OWNER}"], kind="summary")
    assert len(facts) == 1, "the governed write did not land a fact"
    assert facts[0].source_kind == "conversation"
    assert facts[0].source_ref == conv.id

    rows = await kernel.store.audit_query(T)
    assert any(r.verb == "memory.remember" and r.status == "ok" for r in rows), (
        "the write must ride the chokepoint, where the SEC-42 screen lives"
    )
    assert await already_distilled(kernel.store, T, conv.id) is True


@pytest.mark.invariant("SEC-42")
async def test_a_seat_without_on_behalf_of_is_refused_and_leaves_no_receipt():
    """The exact deployment failure, reproduced.

    This is the red-seed made permanent: strip the principal and the governed
    write is refused for the owner's scope. Crucially the RECEIPT must not be
    written either, or a refused thread would be marked distilled and never
    retried.
    """
    from dataclasses import replace

    kernel = await _kernel_with_memory()
    conv = await _thread(kernel, "c2")

    principal_less = replace(distillation_context(T, conv.user_id), on_behalf_of=None)

    with pytest.raises(Exception) as excinfo:
        await distil_conversation(kernel, T, conv, principal_less)
    assert "scope" in str(excinfo.value).lower()

    assert await already_distilled(kernel.store, T, conv.id) is False, (
        "a refused write must leave NO receipt, so the next sweep retries it"
    )
    facts = await kernel.store.list_memory_facts(T, [f"user:{OWNER}"], kind="summary")
    assert facts == []


@pytest.mark.invariant("SEC-42")
async def test_the_seat_cannot_write_into_another_users_scope():
    """The bound the per-owner seat buys: alice's seat cannot write to bob."""
    kernel = await _kernel_with_memory()
    conv = await _thread(kernel, "c3", owner="bob@example.com")

    alices_seat = distillation_context(T, OWNER)  # wrong principal for this thread

    with pytest.raises(Exception):
        await distil_conversation(kernel, T, conv, alices_seat)

    assert await kernel.store.list_memory_facts(
        T, ["user:bob@example.com"], kind="summary"
    ) == []
