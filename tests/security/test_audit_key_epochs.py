"""Rotating a leaked audit key must not destroy the history you rotated away from.

The live event (Classical Visas, 2026-07-26): the tenant's audit chain was HMAC'd with the
placeholder shipped in `.env.example`, so anyone with the repository could forge it - and it
verified GREEN, which is worse than no check at all. Rotating was plainly right. It cost
verification of all 111 prior rows, because `verify_chain` re-derives from seq 1 under ONE key.

That price is the defect these tests pin. It makes rotation mean "lose your history", which
argues for never rotating a LEAKED key - exactly the wrong incentive - and it destroys signal,
because a permanently failing verify is indistinguishable from tampering.

An epoch keeps a retired key for VERIFICATION ONLY, bounded by the seq at which it was retired.
The bound is the security property, not bookkeeping: without it anyone holding a retired key
(here, a PUBLIC constant) could append fresh rows that verify perfectly.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from boltrig.kernel import audit as audit_mod
from boltrig.kernel.audit import _key_for_seq, _retired_epochs, verify_chain


class _Row:
    """The two fields verify_chain reads, plus a canonical body."""

    def __init__(self, seq: int, body: str, key: bytes, prev: str | None):
        self.seq = seq
        self.body = body
        self.prev_hash = prev
        self.hash = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


def _scan(rows: list[_Row]):
    async def scan(_tenant: str, after: int, page: int):
        return [r for r in rows if r.seq > after][:page]

    return scan


def _canonical(row: _Row) -> str:
    return row.body


def _chain(specs: list[tuple[int, bytes]]) -> list[_Row]:
    """Build a valid chain, each row sealed under the key given for its seq."""
    rows: list[_Row] = []
    prev: str | None = None
    for seq, key in specs:
        row = _Row(seq, f"body-{seq}", key, prev)
        rows.append(row)
        prev = row.hash
    return rows


OLD = b"the-public-placeholder-key"
NEW = b"a-real-32-byte-random-secret-xx"


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
def test_no_epochs_configured_behaves_exactly_as_before(monkeypatch):
    monkeypatch.delenv("BOLTRIG_AUDIT_HMAC_RETIRED", raising=False)
    assert _retired_epochs() == []
    # every row resolves to the live key - the pre-epoch behaviour, unchanged
    assert _key_for_seq(1, []) == audit_mod._HMAC_KEY
    assert _key_for_seq(None, []) == audit_mod._HMAC_KEY


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
async def test_a_rotated_chain_still_verifies_across_the_boundary(monkeypatch):
    """THE point. Rows 1-3 sealed under the retired key, 4-5 under the live one."""
    monkeypatch.setattr(audit_mod, "_HMAC_KEY", NEW)
    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_RETIRED", f"4:{OLD.decode()}")
    rows = _chain([(1, OLD), (2, OLD), (3, OLD), (4, NEW), (5, NEW)])

    ok, bad = await verify_chain(_scan(rows), _canonical, "t", 10)
    assert ok, f"a rotated chain must still verify; failed at {bad}"


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
async def test_without_the_epoch_the_same_chain_fails_at_row_one(monkeypatch):
    """The control: this is the state CV is in today, and what the epoch cures.

    Same rows, no epoch configured - verification dies at seq 1 and cannot tell a re-key
    from tampering.
    """
    monkeypatch.setattr(audit_mod, "_HMAC_KEY", NEW)
    monkeypatch.delenv("BOLTRIG_AUDIT_HMAC_RETIRED", raising=False)
    rows = _chain([(1, OLD), (2, OLD), (3, OLD), (4, NEW), (5, NEW)])

    ok, bad = await verify_chain(_scan(rows), _canonical, "t", 10)
    assert not ok and bad == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
async def test_a_retired_key_cannot_vouch_for_a_row_after_its_boundary(monkeypatch):
    """The security property the bound exists for.

    A retired key is a key somebody may hold - here it is a PUBLIC constant. If it could
    seal rows at or after the rotation, an attacker could append forged history that
    verifies, and the rotation would have bought nothing.
    """
    monkeypatch.setattr(audit_mod, "_HMAC_KEY", NEW)
    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_RETIRED", f"4:{OLD.decode()}")
    # seq 4 is AT the boundary and forged under the retired key
    rows = _chain([(1, OLD), (2, OLD), (3, OLD), (4, OLD), (5, NEW)])

    ok, bad = await verify_chain(_scan(rows), _canonical, "t", 10)
    assert not ok, "a retired key must not seal a row at or after its boundary"
    assert bad == 4


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
async def test_tampering_inside_a_retired_segment_is_still_caught(monkeypatch):
    """An epoch widens WHICH key may verify a row - never whether the row must verify."""
    monkeypatch.setattr(audit_mod, "_HMAC_KEY", NEW)
    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_RETIRED", f"4:{OLD.decode()}")
    rows = _chain([(1, OLD), (2, OLD), (3, OLD), (4, NEW), (5, NEW)])
    rows[1].body = "body-2-TAMPERED"  # hash no longer matches under any key

    ok, bad = await verify_chain(_scan(rows), _canonical, "t", 10)
    assert not ok and bad == 2


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
def test_a_malformed_epoch_is_ignored_rather_than_trusted(monkeypatch):
    """Fail-safe direction: a bad entry drops the row through to the live key, where it
    fails honestly. It must never widen what is accepted."""
    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_RETIRED", "notanumber:k,:nokey,7:good")
    assert _retired_epochs() == [(7, b"good")]


@pytest.mark.security
@pytest.mark.invariant("SEC-16")
def test_epochs_are_ordered_and_the_earliest_boundary_wins(monkeypatch):
    monkeypatch.setattr(audit_mod, "_HMAC_KEY", NEW)
    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_RETIRED", "9:second,4:first")
    epochs = _retired_epochs()
    assert epochs == [(4, b"first"), (9, b"second")]
    assert _key_for_seq(1, epochs) == b"first"    # oldest segment
    assert _key_for_seq(5, epochs) == b"second"   # middle segment
    assert _key_for_seq(9, epochs) == NEW         # live segment
