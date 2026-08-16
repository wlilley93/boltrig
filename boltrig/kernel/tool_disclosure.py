"""Progressive tool disclosure: the ordered OFFER, computed away from authority.

The verb row is the chokepoint, and the offer is not. ``_invoke_inner`` resolves
the verb and its binding, validates the call against the row's ``input_schema``,
checks the caller's grants, and reads the row's ``consequence`` for the HITL gate
(boltrig/kernel/dispatch.py). An adapter must therefore still publish every tool
it will ever accept a call for, and nothing here changes that: this module
decides what reaches a model's CONTEXT, never what reaches the verbs table and
never what a run is authorised to call.

The MCP face already keeps those two apart, which is what makes this slice
fork-free. ``_list_tools`` computes the offer from the tenant ceiling intersected
with the run's grants, and ``_call_tool`` never consults it - it hands the call
to the kernel under the run token's own context, so authority is re-derived from
the grants at call time (boltrig/kernel/mcp.py). Narrowing the offer therefore
cannot narrow, or widen, what a call is allowed to do.

The codex lane is the stated exception and is untouched here. Its offer is
compiled at admission into an exact wire-name ceiling, attested, and enforced on
both the request and the response
(boltrig/fleet/infrastructure/codex_kernel_tools_phase.py). Offer and authority
are FUSED there deliberately, so a lane whose ceiling IS its attestation cannot
be handed a truncated offer without losing the attestation. That is a constraint
to state, not one to defeat, and this module is not wired into it.

WHERE A DECLARED SIGNAL WOULD GO. Every signal below is DERIVED: read off values
that already exist, the verb row (``noun_id``, ``consequence``, the verb id) and
the run token (its loaded skill ids, its allow patterns). None of them is a
statement by an adapter author about when a tool is worth spending context on. A
DECLARED signal - a disclosure rank on the verb row, or a skill naming the verbs
it wants in context - would enter as a new FIRST element of the tuple returned by
``_ranking_key``, ahead of the three derived ones, which would then survive only
as the tie-break among verbs that declare nothing. Whether that declared signal
should exist at all is open, and is deliberately not built in this slice.

Pure by construction: no store, no I/O, no async, no clock, and no re-implemented
grant matching. Eligibility is asked of the grant primitive itself, so
deny-dominance and the terminal-wildcard rule stay in one place.
"""

from __future__ import annotations

from collections.abc import Iterable

from boltrig.models import Consequence, GrantSet, Verb
from boltrig.models.grants import normalize_identifier

# A skill id is a path-ish label ("analysis/ticket-decomposition", "ops/opbox"),
# so its segments are the only statement of task the run token carries today.
# Splitting on these yields the token set a verb's noun is matched against.
_SKILL_ID_SEPARATORS = ("/", "-", "_", ".", ":")


class ToolDisclosureError(ValueError):
    """An offer input is not an exact bounded value, so no offer is computed."""


def _skill_tokens(skills: Iterable[str]) -> frozenset[str]:
    """The lowercase segment set of the run's loaded skill ids.

    ``normalize_identifier`` first, for the same reason grant matching applies it:
    a confusable or compatibility form must not read as a different token from the
    ASCII one it imitates.
    """
    tokens: set[str] = set()
    for skill in skills:
        if type(skill) is not str:
            raise ToolDisclosureError("a loaded skill id must be an exact string")
        normalized = normalize_identifier(skill).lower()
        for separator in _SKILL_ID_SEPARATORS:
            normalized = normalized.replace(separator, " ")
        tokens.update(part for part in normalized.split() if part)
    return frozenset(tokens)


def _skill_affinity(verb: Verb, tokens: frozenset[str]) -> int:
    """0 when a loaded skill's id names this verb's noun, 1 otherwise.

    The coarsest honest unit: a skill loaded for a job is the strongest statement
    of what THIS run is for, and the noun is the concept the verb hangs off. It
    is a lexical match and it is derived, not declared - see the module docstring.
    """
    noun = normalize_identifier(verb.noun_id or "").lower()
    return 0 if noun and noun in tokens else 1


def _grant_specificity(verb: Verb, grants: GrantSet) -> int:
    """0 when an allow token names this verb exactly, 1 when a wildcard reached it.

    An operator who wrote ``ticket.create`` into a grant named a verb; one who
    wrote ``ticket.*`` named a namespace and left the choice open. That is the
    nearest thing to intent already present on the run token, so it ranks above
    consequence and below the run's own loaded skills.
    """
    verb_id = normalize_identifier(verb.id)
    return 0 if any(normalize_identifier(pattern) == verb_id for pattern in grants.allow) else 1


def _consequence_rank(verb: Verb) -> int:
    """0 for a low-consequence verb, 1 for a high-consequence one.

    Not a safety rule - the HITL gate owns consequence and this cannot move it.
    It is a budget rule: when context is scarce, spend it first on the calls a
    run can carry to completion without a human round trip.
    """
    return 1 if verb.consequence == Consequence.HIGH else 0


def _ranking_key(verb: Verb, grants: GrantSet, tokens: frozenset[str]) -> tuple[int, int, int, str]:
    """The whole ranking rule, in one readable tuple. Lower sorts earlier.

    Ordered by how directly each signal speaks to THIS run: what the run loaded,
    then how precisely its authority was written, then what a call will cost it,
    then the verb id as a total order so the offer is deterministic for identical
    inputs regardless of the order the verbs arrived in. A declared signal would
    become a fifth element, first in the tuple.
    """
    return (
        _skill_affinity(verb, tokens),
        _grant_specificity(verb, grants),
        _consequence_rank(verb),
        normalize_identifier(verb.id),
    )


def compute_tool_offer(
    verbs: Iterable[Verb],
    grants: GrantSet,
    skills: Iterable[str],
    budget: int,
) -> tuple[Verb, ...]:
    """Rank the granted verbs and return the first ``budget`` of them.

    ``verbs`` is the candidate rows (a tenant's verbs, already tenant-scoped by
    whoever read them), ``grants`` the caller's effective authority, ``skills``
    the run token's loaded skill ids, ``budget`` how many tools the caller is
    willing to put in front of a model.

    Three properties hold by construction and are the reason this is one pure
    function rather than a branch inside the MCP face:

      * the offer is a SUBSET of what the grants admit. Eligibility is asked of
        ``permits`` and never re-derived here, so an upper bound on authority can
        never be mistaken for the selection of what is offered - and a verb left
        out of the offer is left out of CONTEXT, not out of authority. It stays
        callable, and the chokepoint still gates it.
      * the offer never exceeds the budget, and a budget of zero offers nothing
        while changing no one's authority at all.
      * the order is total and deterministic: identical inputs in any order give
        the identical offer.

    Raises ToolDisclosureError on a budget that is not a non-negative int, on a
    ceiling that is not the grant primitive, or on a skill id that is not a
    string. An offer computed from a value nobody validated is worse than none.
    """
    if type(budget) is not int or budget < 0:
        raise ToolDisclosureError("the offer budget must be a non-negative int")
    if type(grants) is not GrantSet:
        raise ToolDisclosureError("the ceiling must be a GrantSet, not a re-derived matcher")
    tokens = _skill_tokens(skills)

    eligible: list[Verb] = []
    seen: set[str] = set()
    for verb in verbs:
        verb_id = normalize_identifier(verb.id)
        if verb_id in seen:
            continue  # the offer is keyed by tool name, so a repeat is one tool
        seen.add(verb_id)
        if grants.permits(verb.id):
            eligible.append(verb)

    ordered = sorted(eligible, key=lambda verb: _ranking_key(verb, grants, tokens))
    return tuple(ordered[:budget])


def offer_payload(
    candidates: Iterable[Verb],
    grants: GrantSet,
    skills: Iterable[str],
) -> list[dict]:
    """The ``tools/list`` payload for one run, in ranked order.

    Wired at the MCP face per [2026] VJS-CC-VJS 10 D3: an unwired ranker decides
    nothing and protects nothing. ``candidates`` is already narrowed to the tenant
    ceiling by the caller, so ``grants`` here is the RUN's authority and the
    eligibility this applies is the same ceiling-intersect-run it always was.

    NOTHING IS DROPPED. The budget is the candidate count, so this changes the
    ORDER of the offer and not its membership. That is deliberate: ranking is
    provably authority-neutral, whereas choosing a truncation size is a policy
    question the order reserves (D4), and a wiring commit is the wrong place to
    settle it. When a budget is adopted it is passed here and nowhere else.
    """
    # Materialise once. `len(list(candidates))` evaluated as an argument beside
    # `candidates` would consume a generator before compute_tool_offer ever saw it,
    # and the offer would silently be empty for every non-list caller.
    rows = list(candidates)
    ranked = compute_tool_offer(rows, grants, skills, len(rows))
    return [
        {
            "name": verb.id,
            "description": _model_description(verb),
            "inputSchema": verb.input_schema,
        }
        for verb in ranked
    ]


def _model_description(verb: Verb) -> str:
    """Render useful model guidance without inventing execution semantics.

    Consequence is kernel-owned registry data, so it is safe to disclose to an
    already-authorised caller. We do not infer read-only, destructive, or
    idempotent MCP annotations: those are different properties and the registry
    does not yet carry them.
    """

    description = (verb.description or verb.id).strip()
    if verb.consequence is Consequence.HIGH:
        return (
            f"{description}\n\nBoltrig governance: this is a high-consequence "
            "tool. The kernel may hold the exact call for human approval; a held "
            "call has not executed."
        )
    return description
