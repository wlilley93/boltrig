"""Deterministic capability routing (docs/SPEC-capability-doctrine.md §2, §8).

A capability may have MANY eligible implementations. Every invocation still
produces ONE execution plan, and the kernel - never the model - chooses it. The
precedence, top down:

  1. a workspace routing policy for this capability version and operation class,
  2. a tenant routing policy for the same,
  3. the only eligible binding, if there is exactly one,
  4. otherwise :class:`RouteRequired`, naming the human-readable destinations.

Falling back to "pick the first one" is the failure this exists to prevent, so
there is no step 5. The doctrine's level-0 precedence - an explicit destination
carried in the request - has no channel yet (SPEC §11.9); when it lands it goes
in ABOVE step 1 and outside the business arguments (§7.B).

WHAT WP2 DOES NOT DO: fan-out. A read with two eligible bindings is ambiguous
here rather than merged, because merging needs canonical output transforms and
opaque record refs - doctrine step 3. That keeps the refusal honest instead of
silently answering from one of two CRMs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boltrig.models import BindingNotFound
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    capability_ref,
    parse_capability_ref,
)
from boltrig.models.errors import RouteRequired

# The operation class decides whether a route may ever be plural and how hard a
# missing destination fails. Read from the capability's own last segment, which
# the doctrine's naming makes meaningful (crm.contact.search, matter.open).
_READ_SUFFIXES = frozenset(
    {"read", "get", "list", "search", "find", "lookup", "export", "describe"}
)
_CREATE_SUFFIXES = frozenset({"create", "add", "open", "incorporate", "prepare", "issue"})
_DELETE_SUFFIXES = frozenset({"delete", "remove", "archive", "purge", "cancel", "revoke"})


def operation_class_for(capability_id: str) -> str:
    """Classify a capability by its final segment.

    Unknown suffixes are classed ``update``: the write path, which never fans
    out and always demands a definite destination. An unrecognised name must
    fail towards the careful branch, not the permissive one.
    """
    suffix = capability_id.rpartition(".")[2]
    if suffix in _READ_SUFFIXES:
        return "read"
    if suffix in _CREATE_SUFFIXES:
        return "create"
    if suffix in _DELETE_SUFFIXES:
        return "delete"
    return "update"


@dataclass(frozen=True)
class PlanTarget:
    """The one destination an invocation resolves to."""

    binding_id: str
    source_operation_id: str
    connection_id: str
    connection_label: str
    # SPEC §8 dispatch step 5: effective consequence comes from the capability
    # AND the selected binding. A binding may only ever RAISE it - a mapping
    # that could lower a source operation's consequence would let a route
    # downgrade a governed action, which is the wrong direction to fail.
    consequence_override: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    capability_id: str
    capability_version: int
    operation_class: str
    target: PlanTarget
    selected_by: str  # workspace_policy | tenant_policy | only_eligible

    @property
    def ref(self) -> str:
        return capability_ref(self.capability_id, self.capability_version)


def _destination(binding: CapabilityBinding, connection: ProviderConnection) -> dict[str, str]:
    """One candidate, named the way a human would recognise it (§3, §7.C)."""
    return {
        "binding_id": binding.binding_id,
        "connection_id": connection.id,
        "connection": connection.label,
        "source_operation_id": binding.source_operation_id,
    }


def _eligible(
    bindings: list[CapabilityBinding],
    connections: dict[str, ProviderConnection],
    workspace_id: str | None,
) -> list[tuple[CapabilityBinding, ProviderConnection]]:
    pairs = []
    for binding in bindings:
        connection = connections.get(binding.connection_id)
        if binding.status != "approved" or not binding.serves(workspace_id):
            continue
        if connection is None or not connection.eligible:
            continue
        pairs.append((binding, connection))
    return pairs


def _policy_choice(policies, pairs, version: int, operation_class: str, workspace_id):
    """The first policy, workspace scope before tenant scope, naming a still
    eligible binding. A policy pointing at a disabled or deleted binding is
    SKIPPED rather than fatal - the next rule (or the ambiguity refusal) then
    decides, which is what stops a stale rule from becoming an outage."""
    by_id = {binding.binding_id: (binding, connection) for binding, connection in pairs}
    for scope in ("workspace", "tenant"):
        for policy in policies:
            if policy.scope != scope or not policy.applies(version, operation_class, workspace_id):
                continue
            chosen = by_id.get(policy.binding_id)
            if chosen is not None:
                return chosen, f"{scope}_policy"
    return None, ""


async def resolve_execution_plan(
    store: Any,
    tenant_id: str,
    name: str,
    *,
    workspace_id: str | None = None,
    authorize: Callable[[str], None] | None = None,
) -> ExecutionPlan:
    """Resolve ``crm.contact.search`` (or ``...@1``) to one execution plan.

    ``authorize`` is called with the capability id AFTER the capability is known
    to exist and BEFORE any destination is read. That order is the doctrine's
    own (§8 dispatch steps 3 then 4) and it is load-bearing rather than tidy:
    ``route_required`` names the tenant's connections by their human-readable
    labels, so resolving the route first hands an ungranted caller a list of
    every CRM the tenant has connected. The caller learns only whether the
    capability exists - exactly what an unknown verb id already discloses.
    """
    capability_id, pinned = parse_capability_ref(name)
    bindings = await store.list_capability_bindings(tenant_id, capability_id)
    if pinned is not None:
        bindings = [b for b in bindings if b.capability_version == pinned]
    if not bindings:
        raise BindingNotFound(f"unknown verb '{name}'")
    if authorize is not None:
        authorize(capability_id)
    connections = {c.id: c for c in await store.list_provider_connections(tenant_id)}
    pairs = _eligible(bindings, connections, workspace_id)
    if not pairs:
        raise BindingNotFound(f"capability '{name}' has no eligible binding")
    # Unpinned addressing means the newest live version, never a mixture: a plan
    # that straddled two versions would be routing across two contracts.
    version = pinned if pinned is not None else max(b.capability_version for b, _ in pairs)
    pairs = [pair for pair in pairs if pair[0].capability_version == version]
    operation_class = operation_class_for(capability_id)
    policies = await store.list_routing_policies(tenant_id, capability_id)
    chosen, selected_by = _policy_choice(
        policies, pairs, version, operation_class, workspace_id
    )
    if chosen is None:
        if len(pairs) > 1:
            raise RouteRequired(
                f"capability '{capability_ref(capability_id, version)}' has "
                f"{len(pairs)} eligible destinations and no routing rule selects one",
                capability=capability_ref(capability_id, version),
                operation_class=operation_class,
                destinations=[_destination(b, c) for b, c in pairs],
            )
        chosen, selected_by = pairs[0], "only_eligible"
    binding, connection = chosen
    return ExecutionPlan(
        capability_id=capability_id,
        capability_version=version,
        operation_class=operation_class,
        target=PlanTarget(
            binding_id=binding.binding_id,
            source_operation_id=binding.source_operation_id,
            connection_id=connection.id,
            connection_label=connection.label,
            consequence_override=binding.consequence_override,
        ),
        selected_by=selected_by,
    )


async def resolve_invocation_target(
    store: Any,
    tenant_id: str,
    verb: str,
    meta: dict[str, Any],
    *,
    workspace_id: str | None = None,
    authorize: Callable[[str], None] | None = None,
) -> tuple[Any, Any, ExecutionPlan | None]:
    """The dispatcher's step 1: the verb definition, its binding, and the route.

    A stored verb id resolves exactly as it always did - single binding, no
    capability layer, byte-identical behaviour. Only a name that is NOT a stored
    verb is offered to the capability resolver, so this can add a route where
    there was a 404 and can never change an existing one.
    """
    verb_def = await store.get_verb(tenant_id, verb)
    plan = None
    if verb_def is None:
        plan = await resolve_execution_plan(
            store, tenant_id, verb, workspace_id=workspace_id, authorize=authorize
        )
        verb_def = await store.get_verb(tenant_id, plan.target.source_operation_id)
    if verb_def is None:
        raise BindingNotFound(f"unknown verb '{verb}'")
    binding = await store.get_binding(tenant_id, verb_def.id)
    if binding is None:
        raise BindingNotFound(f"verb '{verb_def.id}' has no binding")
    # Which adapter/agent serviced the call, so the audit can attribute it - and,
    # for a routed call, WHICH capability, binding and connection decided it
    # (SPEC §8 dispatch step 15).
    meta["target_adapter"] = binding.target_ref
    if plan is not None:
        meta["capability"] = plan.ref
        meta["capability_binding_id"] = plan.target.binding_id
        meta["connection"] = plan.target.connection_label
        meta["source_operation"] = plan.target.source_operation_id
        meta["route_selected_by"] = plan.selected_by
    return verb_def, binding, plan


def grant_verbs(verb: str, verb_def: Any, plan: ExecutionPlan | None) -> tuple[str, ...]:
    """Every grant a routed call must hold: the capability AND the source
    operation behind it, each checked by ``GrantChecker.check``.

    Checking only the capability would make a canonical name a way to reach a
    verb the caller was never granted - ``TenantPermissions`` and every grant
    list are verb-id shaped today, so the capability layer must ADD a check
    through the same checker, never replace one.

    THE CHECK PRECEDES SCHEMA VALIDATION, and that order is not tidiness. A
    routed call is validated against the SOURCE OPERATION's input schema, and
    the rejection hands the caller that schema's field names and a digest - the
    same value stored as the binding's ``source_schema_digest``. Validating
    first therefore described a verb to a caller who may not call it, using the
    capability name as the way in.

    The capability is checked UNVERSIONED. ``crm.contact.search@1`` is an
    addressing detail of one call, not a separate permission, and a grant list
    spelled with pinned versions would silently stop matching the day a
    capability's version moved. A version-specific grant, if one is ever wanted,
    is a deliberate new mechanism rather than a side effect of how the caller
    happened to spell the name.
    """
    return (verb,) if plan is None else (plan.capability_id, verb_def.id)


def blocking_names(verb: str, verb_def: Any, plan: ExecutionPlan | None) -> tuple[str, ...]:
    """The names available WITHOUT a store read: what the caller typed, the
    capability it resolved to, and the source operation it will execute.

    Deliberately NOT the versioned form. ``grant_verbs`` refuses the pinned
    spelling because a list written as ``crm.contact.create@1`` silently stops
    matching the day the version moves, and that argument is stronger for a
    human gate than for a grant: the pin adds no coverage (a caller who TYPES
    the pinned name is already matched by ``verb``, and an unpinned operator
    entry is already matched by ``capability_id``), while offering exactly one
    configuration - operator pins, caller does not - that works until it
    quietly does not.

    This is only half the answer; see ``governed_capabilities`` for the half a
    name cannot know.
    """
    if plan is None:
        return (verb,)
    return (verb, plan.capability_id, verb_def.id)


async def governed_aliases(store: Any, tenant_id: str, verb: str) -> tuple[str, ...]:
    """Every name one recorded action answers to, resolved from stored bindings.

    A held call records the name the CALLER typed. For a routed call that is the
    canonical capability, so an approver granted `hubspot.contact.create` - the
    person who administers the system the call will actually touch, and who could
    perform the action themselves - could neither see the request nor answer it.
    The call then sits waiting for a human who does not exist.

    Symmetric on purpose, because the asymmetry is what made it a bug: given a
    capability this returns the source operations that implement it, and given a
    source operation it returns the capabilities that route to it. Only APPROVED
    bindings count, exactly as routing counts them - an unapproved mapping serves
    nothing, so it confers nothing.
    """
    names = {verb}
    capability_id, _pinned = parse_capability_ref(verb)
    for binding in await store.list_capability_bindings(tenant_id, capability_id):
        if binding.status == "approved":
            names.add(binding.source_operation_id)
    for binding in await store.list_capability_bindings(
        tenant_id, source_operation_id=verb
    ):
        if binding.status == "approved":
            names.add(binding.capability_id)
    return tuple(sorted(names))


def unpinned(names: Any) -> frozenset[str]:
    """An operator's always-ask entries with any version pin removed.

    Three ways to treat ``crm.contact.create@1`` in a blocking list, and only one
    is safe. Honour it as written and the gate stops firing the day a binding's
    version moves - silently, because nothing reads that list back. Ignore it and
    the gate never fires at all - also silently. Normalise it and the operator
    gets what they plainly meant: this capability, at whatever version serves it.
    A plain verb id has no pin and passes through unchanged.
    """
    return frozenset(parse_capability_ref(str(name))[0] for name in names)


async def governed_capabilities(
    store: Any, tenant_id: str, verb_def: Any, plan: ExecutionPlan | None
) -> tuple[frozenset[str], str | None]:
    """The capabilities this call answers to, and the strongest override on the
    binding that serves it - resolved from STORED bindings when the caller
    addressed the source operation directly.

    A name-only match cannot see this, and that gap was a hole rather than an
    inelegance: ``crm.contact.create`` and ``hubspot.contact.create`` are the
    same action through the same binding, so an operator who blocked the
    capability blocked nothing a model could actually reach - the MCP face
    offers source-operation verb ids and never capability names. The binding's
    ``consequence_override`` has the same shape of bug: it is a property of the
    ROUTE, so reading it only when the caller happened to spell the canonical
    name let the identical call through the identical binding go ungated.

    ``status != approved`` bindings are ignored here exactly as they are ignored
    by routing: an unapproved mapping governs nothing because it serves nothing.
    """
    if plan is not None:
        return frozenset({plan.capability_id}), plan.target.consequence_override
    names: set[str] = set()
    override: str | None = None
    for binding in await store.list_capability_bindings(
        tenant_id, source_operation_id=verb_def.id
    ):
        if binding.status != "approved":
            continue
        names.add(binding.capability_id)
        if binding.consequence_override == "high":
            override = "high"
    return frozenset(names), override
