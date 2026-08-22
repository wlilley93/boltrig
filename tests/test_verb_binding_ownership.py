"""Registration must not overwrite a binding it does not own (K-5 companion).

THE DEFECT THIS PINS. `bind_verb_to_agent` re-points a verb at a reasoning
agent; every startup then re-runs `register_adapter_verbs` for each adapter,
which used to upsert an ADAPTER binding unconditionally. The deliberate
re-point silently reverted on the next boot, and the symptom -- "verb bindings
revert on restart" -- looked like a persistence bug rather than a registry one.

The convention that fixes it already existed in the INVERSE: deactivation's
`_unpublish_owned_verbs` only removes bindings whose target_ref is the
adapter's own id. It now lives on `VerbBinding.owned_by` so the effect and its
inverse cannot disagree about who owns what.
"""

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel.registry import KernelRegistry
from boltrig.kernel.revertible import EffectLog
from boltrig.models import TargetType, VerbBinding
from boltrig.store import InMemoryStore

TENANT = "t-ownership"


def _binding(target_type: TargetType, target_ref: str) -> VerbBinding:
    return VerbBinding(
        verb_id="ticket.create",
        tenant_id=TENANT,
        target_type=target_type,
        target_ref=target_ref,
    )


class TestOwnership:
    """The predicate itself, which both the effect and its inverse consult."""

    def test_adapter_owns_its_own_adapter_binding(self):
        assert _binding(TargetType.ADAPTER, "tickets").owned_by("tickets") is True

    def test_adapter_does_not_own_another_adapters_binding(self):
        assert _binding(TargetType.ADAPTER, "tickets").owned_by("other") is False

    def test_no_adapter_owns_an_agent_binding(self):
        # target_type settles it before the ref is compared: a capability that
        # happens to share an adapter's name is still not that adapter's.
        assert _binding(TargetType.AGENT, "tickets").owned_by("tickets") is False


@pytest.mark.asyncio
class TestRegistrationDoesNotClobber:
    async def test_agent_repoint_survives_re_registration(self):
        """The reported bug, pinned: a restart must not undo a deliberate re-point."""
        store = InMemoryStore()
        registry = KernelRegistry(store)
        adapter = build_tickets()

        await registry.register_adapter_verbs(TENANT, adapter)
        await registry.bind_verb_to_agent(TENANT, "ticket.create", "drafting-agent")
        await registry.register_adapter_verbs(TENANT, adapter)  # "restart"

        binding = await store.get_binding(TENANT, "ticket.create")
        assert binding.target_type is TargetType.AGENT
        assert binding.target_ref == "drafting-agent"

    async def test_registration_still_updates_a_binding_it_owns(self):
        """Not-clobbering must not become not-updating: its own row still moves."""
        store = InMemoryStore()
        registry = KernelRegistry(store)
        adapter = build_tickets()
        await registry.register_adapter_verbs(TENANT, adapter)

        # Displace it with an adapter binding owned by someone else, then let
        # the owner re-register: the owner's row is restored because it is his.
        await store.upsert_binding(_binding(TargetType.ADAPTER, adapter.id))
        await registry.register_adapter_verbs(TENANT, adapter)
        binding = await store.get_binding(TENANT, "ticket.create")
        assert binding.target_type is TargetType.ADAPTER
        assert binding.target_ref == adapter.id

    async def test_a_later_adapter_may_still_take_the_verb(self):
        """Adapter-over-adapter is PROVIDER SELECTION and must keep working.

        The example manifest has jira and memory-tickets both publishing
        ticket.create, and five audio adapters publishing voice.speak; last
        registration wins, so manifest order picks the provider. An earlier
        version of this rule refused adapter-over-adapter too and booted the
        stack onto whichever adapter happened to register first.
        """
        store = InMemoryStore()
        registry = KernelRegistry(store)
        first = build_tickets()
        await registry.register_adapter_verbs(TENANT, first)

        later = build_tickets()
        later.id = "other-tickets"
        await registry.register_adapter_verbs(TENANT, later)

        binding = await store.get_binding(TENANT, "ticket.create")
        assert binding.target_ref == "other-tickets"

    async def test_a_native_kernel_binding_survives_re_registration(self):
        """`questions.py` binds its verb to native:questions and the chokepoint
        intercepts it in-kernel. An adapter publishing that verb id must not be
        able to disable the human-question pause by registering over it."""
        store = InMemoryStore()
        registry = KernelRegistry(store)
        adapter = build_tickets()
        await registry.register_adapter_verbs(TENANT, adapter)
        await store.upsert_binding(
            VerbBinding(
                verb_id="ticket.create",
                tenant_id=TENANT,
                target_type=TargetType.AGENT,
                target_ref="native:questions",
            )
        )

        await registry.register_adapter_verbs(TENANT, adapter)

        binding = await store.get_binding(TENANT, "ticket.create")
        assert binding.target_type is TargetType.AGENT
        assert binding.target_ref == "native:questions"


@pytest.mark.asyncio
class TestRegistrationCarriesItsInverse:
    async def test_revert_removes_what_registration_added(self):
        store = InMemoryStore()
        registry = KernelRegistry(store)
        effects = EffectLog()
        await registry.register_adapter_verbs(TENANT, build_tickets(), effects=effects)
        assert len(effects) > 0

        assert await effects.revert() == []
        assert await store.get_binding(TENANT, "ticket.create") is None
        assert await store.get_verb(TENANT, "ticket.create") is None

    async def test_revert_restores_what_registration_displaced(self):
        """The reason the inverse is built at apply time rather than written later.

        Only the call that replaced a row knows there WAS a row. A
        hand-written undo that deletes is right for a created binding and wrong
        for a replaced one, and nothing at revert time can tell them apart.
        """
        store = InMemoryStore()
        registry = KernelRegistry(store)
        adapter = build_tickets()
        await registry.register_adapter_verbs(TENANT, adapter)
        before = await store.get_binding(TENANT, "ticket.create")

        effects = EffectLog()
        await registry.register_adapter_verbs(TENANT, adapter, effects=effects)
        await effects.revert()

        after = await store.get_binding(TENANT, "ticket.create")
        assert after is not None, "revert deleted a binding it had only replaced"
        assert after.target_ref == before.target_ref

    async def test_an_empty_log_reverts_cleanly(self):
        assert await EffectLog().revert() == []

    async def test_a_failing_inverse_does_not_strand_the_others(self):
        """Report the casualty, run the rest: half-reverted with no record is worse."""
        done: list[str] = []
        effects = EffectLog()

        async def ok_first() -> None:
            done.append("first")

        async def boom() -> None:
            raise RuntimeError("no")

        effects.record("first", ok_first)
        effects.record("second", boom)

        failures = await effects.revert()
        assert len(failures) == 1
        assert "second" in failures[0]
        # LIFO, so the failing newest ran before the oldest -- which still ran.
        assert done == ["first"]
        # An inverse that has run must never run twice.
        assert await effects.revert() == []
