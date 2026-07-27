"""Skill tool_grants are a SELECTION, and this is what holds them to it.

County Court, SUBMISSION-2026-07-27-123842 (CONVENING-county-2026-07-27-125100). Ratio:

    An upper bound on authority must never be used as the selection of what an
    agent is offered for a task. Offering is an affirmative, enumerated,
    task-scoped choice made from within that bound; where reach falls short, the
    repair belongs at the boundary that actually withholds it, and is supplied as
    data, never by raising, splitting, or silencing the bound.

``spawn.py:152`` composes ``GrantSet.of(skill tool_grants).intersect(caller
ceiling)``. That intersection IS the selection slot. Three ways it goes wrong,
and one gate each:

* CP2 - a WILDCARD in the slot. Selection by upper bound, which the ratio forbids
  outright. This is the live defect of 2026-07-24: a blanket ``opbox.*`` expanded
  against a 633-verb consumed door, blew through ``MAX_KERNEL_TOOLS`` and degraded
  EVERY org-admin chat turn with ``CodexKernelToolsError``.

* CP1 - an expansion ABOVE the bound. The same outage seen from the other side.
  ``validated_kernel_tool_names`` raises rather than truncating (deliberately: the
  corollary of the ratio is that a bound imposed for exactness must fail loudly),
  so an over-wide skill does not degrade gracefully, it kills the turn.

* DEAD GRANTS - an expansion of ZERO. Not ordered by the court, added because
  implementing CP1 uncovered it live. The 07-24 fix narrowed ``ops/opbox`` from
  ``opbox.*`` to eight enumerated verbs, but wrote them in the opbox KERNEL door's
  noun-first form (``opbox.matter.list``) while the tenant runs the FRONTEND
  door's verb-first form (``opbox.list_matters``). Zero of the eight resolve
  against the live tenant; the skill's effective opbox reach has been NIL since
  the day the outage was "fixed". The outage stopped, so nobody looked.

  That is the shape this repo keeps meeting: a green that could not have gone red.
  An over-wide grant announces itself by breaking every turn. A dead grant is
  perfectly silent - the agent simply, quietly, cannot do the thing. So the
  zero-expansion case needs a gate MORE than the over-expansion case does, not
  less.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from boltrig.fleet.infrastructure.codex_kernel_tools_phase import MAX_KERNEL_TOOLS
from boltrig.models.grants import GrantSet

_REPO = Path(__file__).resolve().parents[2]
_SKILLS = _REPO / "libraries" / "skills"
_SURFACE = _REPO / "tests" / "fixtures" / "registered-verb-surface.txt"
# An adapter with this runtime is a CONSUMED server: its tool surface is returned
# from the far side's tools/list and can grow between deploys with no commit here.
# That is what makes a wildcard over it selection-by-upper-bound.
_CONSUMED_RUNTIME = "mcp"


def _load_rows() -> tuple[tuple[str, str, str], ...]:
    """(verb id, adapter id, adapter runtime). Vendored: a gate that skips is not a gate."""
    rows: list[tuple[str, str, str]] = []
    for line in _SURFACE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        assert len(parts) == 3, f"malformed surface row: {line!r}"
        rows.append((parts[0], parts[1], parts[2]))
    assert rows, "the vendored verb surface is empty - the gate would pass vacuously"
    return tuple(rows)


def _load_surface() -> tuple[str, ...]:
    return tuple(verb for verb, _adapter, _runtime in _load_rows())


def _load_skills() -> list[tuple[str, list[str]]]:
    """(skill path relative to the repo, tool_grants) for every shipped skill."""
    out: list[tuple[str, list[str]]] = []
    for path in sorted(_SKILLS.rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        grants = doc.get("tool_grants") or []
        if isinstance(grants, list):
            out.append((str(path.relative_to(_REPO)), [g for g in grants if isinstance(g, str)]))
    return out


def _consumed_namespaces() -> frozenset[str]:
    """Namespaces served by a CONSUMED (mcp-runtime) adapter, derived from bindings.

    Derived, not listed. A hand-kept roster of "the consumed servers" is the same
    artefact that has already been found stale twice in the sibling repo, and
    [2026] VJS-CC-OPBOX 4 removed one for exactly that reason. Deriving it from the
    binding row means a newly consumed server is covered the moment it registers.
    """
    return frozenset(
        _namespace(verb)
        for verb, _adapter, runtime in _load_rows()
        if runtime == _CONSUMED_RUNTIME
    )


def _namespace(grant: str) -> str:
    return grant.split(".", 1)[0]


def _is_consumed(namespace: str) -> bool:
    return namespace in _consumed_namespaces()


def _expand(grants: list[str], surface: tuple[str, ...]) -> list[str]:
    gs = GrantSet.of(allow=grants)
    return [v for v in surface if gs.permits(v)]


# --- CP2: no wildcard in the selection slot ----------------------------------
@pytest.mark.security
def test_no_terminal_wildcard_over_a_consumed_namespace():
    """A wildcard over a surface the far side controls is selection by upper bound."""
    offences: list[str] = []
    for skill, grants in _load_skills():
        for grant in grants:
            if grant == "*":
                offences.append(f"{skill}: bare '*' grants everything registered")
                continue
            if grant.endswith(".*") and _is_consumed(_namespace(grant)):
                offences.append(
                    f"{skill}: '{grant}' wildcards a CONSUMED namespace, whose surface "
                    f"is chosen by the far side and can grow without a commit here"
                )
    assert not offences, "wildcard in the selection slot:\n  " + "\n  ".join(offences)


# --- CP1: expansion stays under the bound ------------------------------------
@pytest.mark.security
def test_no_skill_expands_beyond_the_kernel_tool_bound():
    """An over-wide skill does not degrade: it raises and kills the whole turn."""
    surface = _load_surface()
    offences = [
        f"{skill}: expands to {len(hits)} verbs, over MAX_KERNEL_TOOLS={MAX_KERNEL_TOOLS}"
        for skill, grants in _load_skills()
        if grants and len(hits := _expand(grants, surface)) > MAX_KERNEL_TOOLS
    ]
    assert not offences, "skill grant expansion exceeds the bound:\n  " + "\n  ".join(offences)


# --- The silent one: a grant that selects nothing ----------------------------
@pytest.mark.security
def test_every_granted_namespace_resolves_to_at_least_one_registered_verb():
    """A grant naming verbs that do not exist is inert, and says nothing when it is.

    Asserted per NAMESPACE rather than per token on purpose. A single token may
    legitimately name a verb absent from one tenant's surface. A whole namespace
    resolving to nothing means the skill is addressing a door that is not there -
    which is the live ``ops/opbox`` defect, and is never intentional.
    """
    surface = _load_surface()
    offences: list[str] = []
    for skill, grants in _load_skills():
        namespaces = {_namespace(g) for g in grants if g != "*"}
        for ns in sorted(namespaces):
            if not any(v.split(".", 1)[0] == ns for v in surface):
                continue  # the namespace is absent from this surface entirely
            tokens = [g for g in grants if _namespace(g) == ns]
            if not _expand(tokens, surface):
                offences.append(
                    f"{skill}: every grant on '{ns}' resolves to nothing "
                    f"({', '.join(tokens)}) while the namespace IS registered - "
                    f"the skill is addressing a door that is not there"
                )
    assert not offences, "dead grants:\n  " + "\n  ".join(offences)
