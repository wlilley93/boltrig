"""Opbox-depth audit: enrichment fields, MCP parity, rollup anchors ([2026] VJS-COUNTY 9).

SEC-120  an MCP-initiated audit row carries the caller's identity + org/workspace
         + ip/ua at the SAME field-depth as a human action (D2).
SEC-122  a rollup anchor's root hash matches a recompute over the segment and the
         local dev-fallback is flagged (RFC3161/KMS left as a NULL seam) (D4).
SEC-124  the new audit fields are additive: a row written without them
         canonicalises byte-for-byte as before and the existing chain is
         unchanged (its hashes still verify) (D1).
"""

from __future__ import annotations

import pytest

from boltrig.kernel.audit import _canonical
from boltrig.kernel.security_events import segment_root_hash
from boltrig.models import ActionType, AuditEvent, GrantSet, InvocationContext, utcnow
from tests.conftest import TENANT, make_ctx

_MCP_CALL = {
    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
    "params": {"name": "ticket.create", "arguments": {"title": "x", "id": "T-9"}},
}


def _human_ctx() -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT, grants=GrantSet.of(["ticket.create"]), actor="alice",
        actor_tier="human", run_id="run-h", workspace_id="ws-1",
        ip_address="10.0.0.9", user_agent="Mozilla/5.0",
    )


# --------------------------------------------------------------------------- #
# SEC-124  additive: old rows canonicalise (and verify) exactly as before
# --------------------------------------------------------------------------- #
@pytest.mark.kernel
@pytest.mark.invariant("SEC-124")
async def test_new_fields_are_additive_old_rows_unchanged(kernel):
    # A row with all enrichment fields None must canonicalise WITHOUT the new keys,
    # so a pre-migration row hashes byte-for-byte as it did before the fields
    # existed (its stored hash still verifies).
    plain = AuditEvent(
        tenant_id=TENANT, ts=utcnow(), actor="a", action_type=ActionType.TOOL_CALL,
        status="ok", seq=1, prev_hash=None,
    )
    canon = _canonical(plain)
    for key in ("ip_address", "user_agent", "resource", "resource_id", "workspace_id"):
        assert key not in canon

    # A whole chain of un-enriched rows verifies, and appending an ENRICHED row
    # after them keeps the chain contiguous + verifiable (the enriched fields fold
    # into that row's hash only).
    for i in range(3):
        await kernel.invoke("ticket", "ticket.create", {"title": f"t{i}"},
                            make_ctx(["ticket.create"]))
    ok, bad = await kernel.audit.verify(TENANT)
    assert ok and bad is None

    await kernel.invoke("ticket", "ticket.create", {"title": "e"}, _human_ctx())
    ok2, bad2 = await kernel.audit.verify(TENANT)
    assert ok2 and bad2 is None
    rows = await kernel.store.audit_query(TENANT)
    assert rows[-1].ip_address == "10.0.0.9" and rows[-1].workspace_id == "ws-1"
    # tampering the NEW field on the enriched row is detected (it is in that hash).
    rows[-1].ip_address = "6.6.6.6"
    ok3, bad3 = await kernel.audit.verify(TENANT)
    assert not ok3 and bad3 == rows[-1].seq


# --------------------------------------------------------------------------- #
# SEC-120  MCP-initiated row is enriched to the same depth as a human row
# --------------------------------------------------------------------------- #
@pytest.mark.kernel
@pytest.mark.invariant("SEC-120")
async def test_mcp_action_is_audited_at_the_same_depth_as_a_human_action(kernel):
    # Human action populates identity + workspace + ip + ua.
    await kernel.invoke("ticket", "ticket.create", {"title": "x", "id": "T-1"}, _human_ctx())
    human = (await kernel.store.audit_query(TENANT))[-1]
    depth_fields = ("actor", "workspace_id", "ip_address", "user_agent", "resource")
    assert all(getattr(human, f) is not None for f in depth_fields)

    # MCP-initiated action through the same chokepoint, enriched from the run token
    # (identity + workspace) and the request (ip + ua).
    token = kernel.mcp.issue_run_token(
        TENANT, GrantSet.of(["ticket.create"]), run_id="run-m", actor="agent-x",
        workspace_id="ws-1",
    )
    resp = await kernel.mcp.handle(
        token, _MCP_CALL, ip_address="203.0.113.7", user_agent="boltrig-agent/1.0"
    )
    assert resp["result"]["isError"] is False
    mcp_row = (await kernel.store.audit_query(TENANT))[-1]
    assert mcp_row.actor == "agent-x"
    assert mcp_row.workspace_id == "ws-1"
    assert mcp_row.ip_address == "203.0.113.7"
    assert mcp_row.user_agent == "boltrig-agent/1.0"
    assert mcp_row.resource == "ticket" and mcp_row.resource_id == "T-9"
    # SAME field-depth: every field a human row filled, the MCP row fills too.
    assert all(getattr(mcp_row, f) is not None for f in depth_fields)


# --------------------------------------------------------------------------- #
# SEC-122  rollup anchor root == recompute over the segment; dev-fallback flagged
# --------------------------------------------------------------------------- #
@pytest.mark.kernel
@pytest.mark.invariant("SEC-122")
async def test_rollup_anchor_root_matches_recompute_and_flags_dev_fallback(kernel):
    for i in range(4):
        await kernel.invoke("ticket", "ticket.create", {"title": f"t{i}"},
                            make_ctx(["ticket.create"]))
    anchor = await kernel.anchorer.anchor(TENANT)
    assert anchor is not None
    events = await kernel.store.audit_query(TENANT, limit=10_000)
    segment = [e for e in events if anchor.seq_start <= e.seq <= anchor.seq_end]
    # the anchor's root is exactly a recompute over the segment's row hashes.
    assert anchor.rollup_root_hash == segment_root_hash(segment)
    # LOCAL dev-fallback: flagged, with the external TSA/KMS fields left as a seam.
    assert anchor.is_dev_fallback is True
    assert anchor.rfc3161_token is None and anchor.kms_signature is None

    ok, got = await kernel.anchorer.verify_latest(TENANT)
    assert ok is True and got.id == anchor.id

    # a REWRITE of a row in the anchored segment (row + its hash re-forged) is
    # caught because the recomputed root no longer matches the anchored root - the
    # attacker cannot re-sign the anchor.
    events[1].hash = "deadbeef" + events[1].hash[8:]
    broken, _ = await kernel.anchorer.verify_latest(TENANT)
    assert broken is False


@pytest.mark.kernel
@pytest.mark.invariant("SEC-122")
async def test_anchor_advances_only_over_the_unanchored_tail(kernel):
    for i in range(2):
        await kernel.invoke("ticket", "ticket.create", {"title": f"a{i}"},
                            make_ctx(["ticket.create"]))
    first = await kernel.anchorer.anchor(TENANT)
    assert first.seq_start == 1 and first.seq_end == 2
    # nothing new -> no anchor written.
    assert await kernel.anchorer.anchor(TENANT) is None
    await kernel.invoke("ticket", "ticket.create", {"title": "a2"},
                        make_ctx(["ticket.create"]))
    second = await kernel.anchorer.anchor(TENANT)
    assert second.seq_start == 3 and second.seq_end == 3
