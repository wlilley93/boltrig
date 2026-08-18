"""The proxy ceiling and the kernel's tool offer must be the SAME set.

`_compile_codex_tool_ceiling` says it is "byte-for-byte the kernel MCP face's
tools/list derivation (FR-MCP-02), so the admission-compiled proxy ceiling and
the tools the kernel will actually advertise to the cell are the same set". That
was prose. Two copies of one filter live in two files, and nothing compared
them.

WHY IT MATTERS MORE THAN TIDINESS. The two failure directions are not
symmetrical, and neither is loud:

  * ceiling NARROWER than the offer - the model is shown a tool it may call, and
    `model_proxy_tool_ceiling` drops the call from the request body with no
    error, no log and no status change. The model reports an ordinary turn in
    which the tool simply did nothing.
  * ceiling WIDER than the offer - the run carries authority for a tool the
    model is never told about. Nothing breaks; the surface is just quietly
    larger than the record says.

This is also the safety net any future adoption of a projection BUDGET needs
(SPEC 11.10). The moment either derivation starts selecting - ranking to a
bound, filtering by skill, projecting capabilities instead of verbs - the other
must select identically, and this is the test that says so.
"""

from __future__ import annotations

import pytest

from boltrig.kernel import tool_disclosure
from boltrig.fleet.runtime_resolver import RuntimeResolver
from boltrig.models import Consequence, GrantSet, Verb

TENANT = "tenant-parity"


def _verb(verb_id: str, *, consequence: Consequence = Consequence.LOW) -> Verb:
    return Verb(
        id=verb_id,
        tenant_id=TENANT,
        noun_id=verb_id.split(".")[0],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        description=f"{verb_id} description",
        consequence=consequence,
    )


class _Kernel:
    store: object


class _Store:
    """One tenant whose ceiling admits some verbs and not others."""

    def __init__(self, verbs: tuple[Verb, ...], ceiling: GrantSet) -> None:
        self._verbs = verbs
        self._ceiling = ceiling

    async def get_tenant_permissions(self, tenant_id: str) -> object:
        ceiling = self._ceiling

        class _Perms:
            grants = ceiling

        return _Perms()

    async def list_verbs(self, tenant_id: str) -> tuple[Verb, ...]:
        return self._verbs


def _offer_names(store_verbs, ceiling: GrantSet, run: GrantSet, skills=()) -> set[str]:
    """What the MCP face would advertise, by the face's own derivation."""
    page = tool_disclosure.offer_page(
        [verb for verb in store_verbs if ceiling.permits(verb.id)], run, skills
    )
    return {row["name"] for row in page["tools"]}


@pytest.mark.parametrize(
    "ceiling_tokens, run_tokens",
    [
        (["*"], ["*"]),
        (["ticket.*", "doc.*"], ["ticket.*"]),
        (["ticket.*"], ["*"]),
        (["*"], ["ticket.read", "doc.write"]),
        (["ticket.read"], ["doc.write"]),  # disjoint: both sides must be empty
    ],
)
async def test_the_proxy_ceiling_and_the_tool_offer_are_the_same_set(
    ceiling_tokens, run_tokens
) -> None:
    verbs = tuple(
        _verb(name)
        for name in (
            "ticket.read",
            "ticket.write",
            "doc.read",
            "doc.write",
            "secret.read",
        )
    )
    ceiling = GrantSet.of(ceiling_tokens)
    run = GrantSet.of(run_tokens)

    kernel = _Kernel()
    kernel.store = _Store(verbs, ceiling)
    resolver = RuntimeResolver(kernel, codex_config={"trusted": True})

    admitted = set(await resolver._compile_codex_tool_ceiling(TENANT, run))
    advertised = _offer_names(verbs, ceiling, run)

    assert admitted == advertised, (
        "the admission-compiled proxy ceiling and the kernel's advertised tools "
        f"diverged: only-admitted={sorted(admitted - advertised)}, "
        f"only-advertised={sorted(advertised - admitted)}"
    )


async def test_the_parity_check_can_actually_see_a_divergence() -> None:
    """The anti-vacuous half: a comparison of two empty sets proves nothing, so
    this pins that the fixture really produces a non-trivial set."""
    verbs = tuple(_verb(name) for name in ("ticket.read", "ticket.write", "doc.read"))
    kernel = _Kernel()
    kernel.store = _Store(verbs, GrantSet.of(["*"]))
    resolver = RuntimeResolver(kernel, codex_config={"trusted": True})

    admitted = set(await resolver._compile_codex_tool_ceiling(TENANT, GrantSet.of(["*"])))
    assert admitted == {"ticket.read", "ticket.write", "doc.read"}
    assert admitted == _offer_names(verbs, GrantSet.of(["*"]), GrantSet.of(["*"]))
