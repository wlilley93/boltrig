"""Only opbox's auth/tenancy core was copied, never its domain models.

[2026] VJS-COUNTY 8 D9. Boltrig's org/workspace tenancy was modelled on opbox's,
under an express limit: take the auth and tenancy core, leave the domain. That
limit is the whole reason the copy was permitted - opbox is a legal-practice
product, and its Matters, Forms, Dashboards and Tables are ITS domain. A boltrig
that grew them would not be a governed agent kernel that borrowed a tenancy model,
it would be a second copy of another product drifting away from the first.

WHAT MAKES THIS CHECKABLE. Opbox names its tables explicitly (`@@map`), and so
does boltrig, so "did an opbox table arrive here" is a set intersection over two
real schemas rather than an opinion about what counts as domain. The intersection
is small enough to enumerate, and enumerating it is the test: every shared name
must be one this file names and justifies as auth/tenancy.

The pass/fail therefore turns on DERIVED evidence. A new opbox-named table in
boltrig's schema fails on the next run whether or not anyone remembers D9, and
the failure names the table.

WHAT IT DOES NOT PROVE. That boltrig has not reimplemented an opbox domain
concept under a different table name. Nothing static can decide that - it is a
judgement about meaning, and it is what the court is for. This proves the
mechanical half: no opbox table name has appeared here unexamined.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_REPO = Path(__file__).resolve().parents[2]
_BOLTRIG_SCHEMA = _REPO / "boltrig" / "store" / "schema.sql"
_OPBOX_SURFACE = _REPO / "tests" / "fixtures" / "opbox-model-surface.txt"

# The shared names, each justified. Auth and tenancy are what D9 PERMITS, so a
# name here is not a violation - it is the copy the court allowed, recorded so it
# stays a short list somebody has read.
_PERMITTED_SHARED = {
    "users": "the identity itself - the auth core D9 expressly permits",
    "workspaces": "the tenancy core: COUNTY 8's org/workspace model",
    "workspace_members": "tenancy membership, the re-authorization surface (COUNTY 8 D3)",
    # NOT a copy. Verified by reading both: opbox's is a capability CATALOGUE for
    # API-key grants (key, category, risk_class, touches_external,
    # implied_autonomy_level); boltrig's is the agent RUNTIME registry (runtime,
    # model_endpoint, supported_skills, max_depth, cost_tier). They share a name
    # and not one column. Recorded here rather than silently allowed, because a
    # coincidence that nobody has written down looks exactly like a violation to
    # the next reader.
    "agent_capabilities": "name collision, not a copy: zero shared columns",
}


def _boltrig_tables() -> set[str]:
    schema = _BOLTRIG_SCHEMA.read_text(encoding="utf-8")
    found = set(re.findall(r"^CREATE TABLE IF NOT EXISTS (\w+)", schema, re.MULTILINE))
    assert found, f"scanned nothing: no CREATE TABLE found in {_BOLTRIG_SCHEMA.name}"
    return found


def _opbox_tables() -> set[str]:
    lines = _OPBOX_SURFACE.read_text(encoding="utf-8").splitlines()
    found = {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}
    assert len(found) > 100, (
        f"the vendored opbox surface holds only {len(found)} names, which is far too "
        "few for a 384-model schema - it was truncated or half-written, and an empty "
        "one would make this whole boundary vacuous"
    )
    return found


def test_no_opbox_domain_table_has_arrived_in_boltrig() -> None:
    """The directive, mechanically. A shared name that nobody has justified is a
    domain model that crossed the boundary - or, at best, a collision nobody has
    checked, which is the same thing until someone does."""
    shared = _boltrig_tables() & _opbox_tables()
    unjustified = sorted(shared - set(_PERMITTED_SHARED))
    assert not unjustified, (
        f"boltrig now defines table(s) opbox also defines, with no recorded reason: "
        f"{unjustified}. [2026] VJS-COUNTY 8 D9 permits opbox's AUTH/TENANCY core "
        "only. If one of these really is tenancy, add it to _PERMITTED_SHARED with "
        "the reason; if it is a domain model, it does not belong here and the answer "
        "is the court, not an entry in this list."
    )


def test_the_permitted_list_cannot_outlive_the_tables_it_names() -> None:
    """A justification for a table that no longer exists is a claim about nothing.

    Same failure mode as a stale waiver: it reads as analysis already done, and it
    quietly widens what the list above would tolerate if that name ever returns.
    """
    shared = _boltrig_tables() & _opbox_tables()
    stale = sorted(set(_PERMITTED_SHARED) - shared)
    assert not stale, (
        f"_PERMITTED_SHARED justifies {stale}, which is no longer shared by both "
        "schemas. Drop the entry."
    )


def test_the_overlap_stays_small_enough_to_have_been_read() -> None:
    """A bound on the mechanism itself, not on any one table.

    The list above only means anything while a human has actually read every entry.
    At four names that is true. If it ever reaches double figures, the honest
    conclusion is that the boundary has moved and belongs back in front of the
    court - not that the list needs another line.
    """
    shared = _boltrig_tables() & _opbox_tables()
    assert len(shared) <= 6, (
        f"{len(shared)} tables are now shared with opbox: {sorted(shared)}. D9's "
        "limit is the auth/tenancy CORE; an overlap this size is a merge, and that "
        "is a question for the court rather than for this file."
    )
