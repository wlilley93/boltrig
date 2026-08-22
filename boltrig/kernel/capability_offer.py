"""What the model is OFFERED: canonical capabilities in place of raw operations.

SPEC §10 step 1 ends "stop exposing them directly through Boltrig's MCP face
once a canonical mapping exists". This is that, and it is the last mile of the
capability layer. Approving a binding already made ``matter.open`` DISPATCHABLE;
until this, nothing ever offered the name, so only a caller who already knew it
could reach it.

ONE DERIVATION, TWO CALLERS, AND THAT IS THE POINT. The MCP face and the Codex
proxy ceiling each derived the offer themselves, from ``list_verbs()`` filtered
by ``permits(verb.id)``, and the ceiling's docstring called itself
"byte-for-byte the kernel MCP face's tools/list derivation". Two copies of one
rule stay identical only while someone keeps them so, and here a divergence is
not cosmetic: the face advertising a tool the ceiling refuses gives the model a
tool that always fails. They now call this.

SUPPRESSION IS CONDITIONAL, AND THAT IS THE WHOLE SAFETY ARGUMENT. A capability
is offered only where the caller holds BOTH grants the dispatcher will demand -
the capability's and the source operation's (``routing.grant_verbs``) - and the
source operation is hidden only where its capability actually took its place.
Suppressing unconditionally is the failure §11.10 names: grants are verb-id
shaped, so a caller granted ``opbox.*`` and not ``matter.*`` would lose the raw
verb without gaining the canonical one, and the tool would vanish rather than
be renamed. Nobody loses reach here; some callers gain a better name.
"""

from __future__ import annotations

from typing import Any

from boltrig.models.registry import Consequence, Verb


def _consequence(binding: Any, operation: Any) -> Consequence:
    """The binding may RAISE a source operation's consequence, never lower it.

    Same direction as dispatch step 5: a mapping that could lower one would let
    a route downgrade a governed action.
    """
    for candidate in (binding.consequence_override, operation.consequence_hint):
        if candidate == Consequence.HIGH.value:
            return Consequence.HIGH
    return Consequence.LOW


def _capability_verb(tenant_id: str, capability_id: str, binding: Any, operation: Any) -> Verb:
    """The capability as the model sees it.

    Its CONTRACT is the selected binding's, because without canonical
    transforms a capability's contract IS the contract of the binding behind it
    (SPEC §11.9). That is stated rather than hidden: when transforms land this
    is where the canonical schema replaces the provider's.
    """
    return Verb(
        id=capability_id,
        tenant_id=tenant_id,
        noun_id=capability_id.split(".")[0],
        input_schema=operation.input_schema,
        output_schema=operation.output_schema or {"type": "object"},
        description=operation.description,
        consequence=_consequence(binding, operation),
    )


async def offer_candidates(store: Any, tenant_id: str, *, permits) -> list[Verb]:
    """The candidate rows to offer, canonical names replacing raw ones.

    ``permits`` is a predicate over a single id, and BOTH authorities must be
    folded into it by the caller before it arrives - the tenant ceiling and the
    run's own grants - because offering on the strength of either alone is how
    an upper bound gets mistaken for a selection.
    """
    verbs = await store.list_verbs(tenant_id)
    bindings = [
        b
        for b in await store.list_capability_bindings(tenant_id)
        if b.status == "approved"
    ]
    if not bindings:
        # The overwhelmingly common path today, and byte-identical to what both
        # callers did before this module existed.
        return [verb for verb in verbs if permits(verb.id)]

    operations = {op.id: op for op in await store.list_source_operations(tenant_id)}
    offered: dict[str, Verb] = {}
    replaced: set[str] = set()
    for binding in sorted(bindings, key=lambda b: (b.priority, b.binding_id)):
        operation = operations.get(binding.source_operation_id)
        if operation is None:
            continue
        # Exactly the pair routing.grant_verbs demands, so a tool is offered
        # only where the dispatcher would actually run it.
        if not (permits(binding.capability_id) and permits(binding.source_operation_id)):
            continue
        replaced.add(binding.source_operation_id)
        offered.setdefault(
            binding.capability_id,
            _capability_verb(tenant_id, binding.capability_id, binding, operation),
        )
    return [
        *(verb for verb in verbs if verb.id not in replaced and permits(verb.id)),
        *offered.values(),
    ]
