"""The host boundary stays shut, and the shipped approval window is answerable
([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D1, D5, D7).

On 2026-07-28 an operator applied to open the host boundary with a new
``seat-operator`` command, on the ground that four-eyes had deadlocked
Classical Visas: the sole-author exemption had lapsed the moment the client was
promoted to ``admin`` (the last act performed under the exemption destroyed
it), and every route to a second operator appeared to need an approval that
needed a second operator. The court walked the respond path and found no
author-tier gate anywhere on it: the route was OPEN the whole time and had
simply never been used. What had actually happened was that three approvals
expired on a 3600-second window.

So both limbs were refused, and the defects the record disclosed were ordered
repaired instead. This module holds the three that are checkable statically:

D1 - the identity command set stays exactly {initiate, set-password,
     mint-token}, and ``initiate`` stays the only host-boundary site that
     constructs a ``User``. A fourth command creating an identity is the thing
     that was refused, so it must not be reachable by simply adding a
     subparser later.
D5 - the shipped ``control.*`` approval window is at least 24 hours, at BOTH
     the dataclass default and the parser fallback, and the two agree.
D7 - the Python and TypeScript ``AUTHOR_ROLES`` sets are equal.

These read the SHIPPED artefacts - the parser this CLI actually builds, the
constants this module actually compiles, the two source files as they are on
disk. A test that supplies its own value and asserts it back cannot report the
drift it exists to catch.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import re
from pathlib import Path

import pytest

from boltrig.api import cli as cli_mod
from boltrig.config.manifest import (
    APPROVAL_TIMEOUT_SECONDS_FLOOR,
    HitlConfig,
    _parse_hitl,
)
from boltrig.identity.rbac import AUTHOR_ROLES

REPO_ROOT = Path(__file__).resolve().parents[2]

# The set the court fixed. Written out rather than imported so that widening the
# implementation cannot widen the assertion with it.
IDENTITY_COMMANDS = frozenset({"initiate", "set-password", "mint-token"})


# --- D1: no fourth host-boundary command that creates an identity -----------


def test_dispatch_identity_guard_tuple_is_exactly_the_three_commands() -> None:
    """The router's membership test is the real gate, so assert its literal.

    ``_dispatch_identity`` returns None for anything outside this tuple, which
    is what keeps a new subparser from reaching an identity code path by
    accident. Read out of the compiled source, not from a constant the
    implementation could redefine.
    """
    tree = ast.parse(inspect.getsource(cli_mod._dispatch_identity))
    literals: list[frozenset[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
        ):
            for comparator in node.comparators:
                if isinstance(comparator, (ast.Tuple, ast.Set, ast.List)):
                    values = [
                        e.value
                        for e in comparator.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if values:
                        literals.append(frozenset(values))

    assert literals, "_dispatch_identity no longer guards on a literal command set"
    assert IDENTITY_COMMANDS in literals, (
        "the identity guard tuple in _dispatch_identity is no longer exactly "
        f"{sorted(IDENTITY_COMMANDS)}; found {[sorted(s) for s in literals]}. "
        "A host-boundary command that creates a user identity was REFUSED by "
        "[2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001 D1."
    )


def test_registered_identity_subparsers_are_exactly_the_three_commands() -> None:
    """Assert the parser the CLI actually builds, not the helper in isolation.

    A command is reachable once it is registered, wherever it was registered
    from, so the question is what ``_build_parser`` ends up offering.
    """
    parser = cli_mod._build_parser()
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert subparsers, "the CLI no longer builds a subparser table"
    registered = set(subparsers[0].choices)

    identity_like = {
        name
        for name in registered
        if name in IDENTITY_COMMANDS
        or re.search(r"(seat|create|add|new|provision)-?(operator|user|owner|admin)", name)
        or name in {"seat-operator", "create-user", "add-user"}
    }
    assert identity_like == IDENTITY_COMMANDS, (
        f"the identity command surface is {sorted(identity_like)}, expected "
        f"{sorted(IDENTITY_COMMANDS)}. Adding a host-boundary command that "
        "seats a user identity was refused (D1); reopening it needs a court, "
        "on a record showing D8 satisfied."
    )


def _host_boundary_modules() -> set[str]:
    """The modules ``_dispatch_identity`` actually reaches, derived from it.

    Deliberately NOT a hand-written list, and deliberately not "everything under
    boltrig/api". Both would be a scope this test chose for itself: the first
    goes stale the moment a command is added, and the second sweeps in
    ``auth_routes.py``, which constructs a ``User`` on the in-band
    invite-acceptance path - the very route the court found open and directed be
    used (D8). Sweeping that would report the lawful route as the violation.

    Derived this way, a fourth identity command importing a fresh module is
    covered automatically, which is the case D1 exists to catch.
    """
    tree = ast.parse(inspect.getsource(cli_mod._dispatch_identity))
    return {
        node.module.lstrip(".")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level and node.module
    }


def test_initiate_is_the_only_host_boundary_site_constructing_a_user() -> None:
    """A second construction site is a second boundary, whatever it is called."""
    modules = _host_boundary_modules()
    assert "initiate" in modules, (
        f"_dispatch_identity no longer reaches initiate; found {sorted(modules)}"
    )

    offenders: list[str] = []
    for module in sorted(modules):
        path = REPO_ROOT / "boltrig" / "api" / f"{module}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "User"
            ):
                offenders.append(f"boltrig/api/{module}.py:{node.lineno}")

    assert offenders, (
        "no User(...) construction found in any host-boundary module "
        f"({sorted(modules)}) - has initiate moved? A check that can only pass "
        "is not a check."
    )
    assert all(o.startswith("boltrig/api/initiate.py:") for o in offenders), (
        f"User(...) is constructed at the host boundary outside initiate.py: {offenders}. "
        "initiate.py is the single reasoned carve-out ([2026] VJS-COUNTY 7 D7: "
        "invite-only needs a first inviter); a second one was refused."
    )


# --- D5: an approval window a human can actually answer ---------------------


def test_shipped_approval_timeout_meets_the_24h_floor_at_both_sites() -> None:
    """Both shipped defaults, read from the module, and they must agree.

    ``HitlConfig()`` is the posture of a manifest with no ``hitl`` block;
    ``_parse_hitl({})`` is the posture of one whose block omits the key. They
    describe the same tenant, so a tenant cannot get a different window
    depending on which way its manifest expressed the same silence.
    """
    dataclass_default = HitlConfig().approval_timeout_seconds
    parser_fallback = _parse_hitl({}).approval_timeout_seconds

    assert dataclass_default == parser_fallback, (
        f"the two shipped approval-window defaults disagree: dataclass "
        f"{dataclass_default}s vs parser fallback {parser_fallback}s"
    )
    assert dataclass_default >= 86400, (
        f"the shipped approval window is {dataclass_default}s. An hour was the "
        "proximate cause of what was experienced as a four-eyes deadlock on "
        "Classical Visas and of an application to open the host boundary "
        "([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D5)."
    )
    assert APPROVAL_TIMEOUT_SECONDS_FLOOR >= 86400


@pytest.mark.parametrize("stated", [60, 3600, 86400, 604800])
def test_a_stated_window_is_still_honoured(stated: int) -> None:
    """The floor moves the DEFAULT, never a tenant's deliberate statement.

    Raising a default silently to a floor would be the same class of surprise
    as the promotion that ended the exemption: a value the operator did not
    write, taking effect unannounced.
    """
    assert _parse_hitl({"approval_timeout_seconds": stated}).approval_timeout_seconds == stated


# --- D7: one name, one set --------------------------------------------------


def _typescript_author_roles() -> set[str]:
    """Parse the shipped TypeScript source; do not restate it here."""
    src = (REPO_ROOT / "ui" / "src" / "deck" / "deckMap.ts").read_text()
    match = re.search(
        r"export const AUTHOR_ROLES\s*:\s*ReadonlySet<string>\s*=\s*new Set\(\[(.*?)\]\)",
        src,
        re.S,
    )
    assert match, "AUTHOR_ROLES is no longer declared in ui/src/deck/deckMap.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_python_and_typescript_author_roles_are_equal() -> None:
    """Divergence in EITHER direction fails: each is a different live bug.

    Missing in TypeScript hides a studio from someone the kernel would let in
    (which is what shipped: `superadmin` and `admin` were absent). Missing in
    Python offers a studio the kernel then 403s.
    """
    ts = _typescript_author_roles()
    py = set(AUTHOR_ROLES)
    assert ts == py, (
        f"AUTHOR_ROLES has drifted. Only in TypeScript: {sorted(ts - py)}; "
        f"only in Python: {sorted(py - ts)}. One name must not mean two sets "
        "([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D7)."
    )
