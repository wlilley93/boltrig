"""`boltrig audit-verify` must report the three outcomes DISTINCTLY.

The audit chain claims tamper evidence, and until 2026-07-30 nothing read it:
AuditWriter.verify was reachable only from Python, with no subcommand and no
schedule. The beelink's chain had been failing since 2026-07-24 - 38 rows, six
days - and nobody knew.

The distinction that matters most here is 2 vs 0. A check that CANNOT LOOK must
not exit 0, because a green meaning "did not verify" is the exact failure this
command exists to answer. Same trap the fleet healthcheck fell into.
"""

from __future__ import annotations

from boltrig.api import audit_verify

TENANT = "t-audit-cli"


async def _writer_with_rows(n: int):
    from boltrig.kernel.audit import AuditWriter
    from boltrig.models import ActionType, AuditEvent
    from boltrig.store import InMemoryStore

    store = InMemoryStore()
    writer = AuditWriter(store)
    for i in range(n):
        await writer.write(
            AuditEvent(
                tenant_id=TENANT,
                run_id=f"r{i}",
                actor="tester",
                actor_tier="human",
                action_type=ActionType.TOOL_CALL,
                noun="ticket",
                verb="ticket.create",
                status="ok",
                detail={},
                ts=None,
            )
        )
    return store, writer


def test_cannot_look_is_exit_2_and_never_0(monkeypatch, capsys):
    """No DATABASE_URL means the chain was NOT checked. That is not success."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BOLTRIG_DATABASE_URL", raising=False)

    code = audit_verify.main(["--tenant", TENANT])

    assert code == 2, "a check that could not look must not report success"
    assert code != 0
    assert "cannot verify" in capsys.readouterr().err


async def test_a_sound_chain_verifies():
    """Positive control: without this, exit 1 below could be vacuous."""
    _, writer = await _writer_with_rows(12)
    ok, bad = await writer.verify(TENANT)
    assert ok is True
    assert bad is None


async def test_a_tampered_row_is_caught_and_named():
    """The negative control the whole command exists for.

    Mutate one row's stored hash and require verify to point AT it - not merely
    return False. `first_bad_seq` is what makes the output actionable, and it is
    what told us the beelink broke at 368 rather than somewhere.
    """
    store, writer = await _writer_with_rows(12)
    rows = await store.audit_query(TENANT, limit=100)
    target = sorted(rows, key=lambda r: r.seq)[6]

    ok_before, _ = await writer.verify(TENANT)
    assert ok_before is True, "the chain must be sound before it is broken"

    object.__setattr__(target, "hash", "0" * 64)

    ok, bad = await writer.verify(TENANT)
    assert ok is False
    assert bad == target.seq, f"expected the break named at {target.seq}, got {bad}"


async def test_a_segment_verifies_only_when_seeded_from_the_preceding_row():
    """``seed_prev`` is load-bearing, not convenience.

    verify_chain returns at the FIRST bad row, so one unrepairable break makes
    every later row permanently unchecked - measured on the beelink, where a
    2026-07-24 key rotation with no recorded epoch left the walk aborting at seq
    368 while 300 newer rows said nothing about themselves.

    Segment mode fixes that, but only if the segment is seeded: its first row
    chains to a hash OUTSIDE the window, so seeding prev as None reports a break
    on a perfectly sound chain. That cry-wolf is what verify_chain's own docstring
    warns about, and this pins both halves.
    """
    store, writer = await _writer_with_rows(12)
    rows = sorted(await store.audit_query(TENANT, limit=100), key=lambda r: r.seq)
    cut = rows[5]

    whole_ok, _ = await writer.verify(TENANT)
    assert whole_ok is True, "the chain must be sound before segmenting it"

    # SEEDED: the segment above the cut verifies.
    seeded_ok, seeded_bad = await writer.verify(
        TENANT, start_after=cut.seq, seed_prev=cut.hash
    )
    assert seeded_ok is True, f"a seeded segment must verify, got first_bad={seeded_bad}"

    # UNSEEDED: the same segment reports a break, on a chain that is fine.
    unseeded_ok, unseeded_bad = await writer.verify(TENANT, start_after=cut.seq)
    assert unseeded_ok is False, (
        "an unseeded segment MUST cry wolf - if it did not, the seed would be "
        "decoration and a real break could hide behind a window boundary"
    )
    assert unseeded_bad == rows[6].seq


async def test_a_segment_still_catches_tampering_inside_it():
    """Segment mode must not become a way to skip past a break silently."""
    store, writer = await _writer_with_rows(12)
    rows = sorted(await store.audit_query(TENANT, limit=100), key=lambda r: r.seq)
    cut, victim = rows[3], rows[8]

    object.__setattr__(victim, "hash", "0" * 64)

    ok, bad = await writer.verify(TENANT, start_after=cut.seq, seed_prev=cut.hash)
    assert ok is False
    assert bad == victim.seq, "tampering ABOVE the cut must still be named"
