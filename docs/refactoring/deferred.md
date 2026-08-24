# Deferred findings — NORMAL-mode followups (not structural-sweep work)

Rules (structural-sweep playbook + AGENTS.md): real bugs found during a sweep
are logged here, never fixed inline in a structural commit. Each entry needs
evidence + one concrete failure scenario + a status. Adversarial drift review
of 2026-08-23 (`arc-1/round-1-refresh/findings.md`), scope 003886f7..35383663.

## F-01 · MEDIUM · in-flight turn resurrects a closed conversation / reverts renames

- `fleet/chat_turn_flow.py:249-270` (`_persist_assistant` writes the turn-start
  snapshot back: status + title, no CAS) → `store/conversation_binding_postgres.py:87-102`
  (`update_conversation` has no CAS) → `kernel/conversation_account_routes.py:11-23`
  (`_close_conversation` has no active-run guard; contrast the move route :109-119).
- Scenario: user closes/deletes or renames a conversation mid-turn; when the
  turn ends the stale snapshot overwrites status/title. Close silently undone.
- Status: OPEN.

## F-02 · MEDIUM · re-registration resets human-approved capability bindings

- `kernel/capability_records.py:128-143` (upsert overwrites status on conflict:
  first_party→approved else proposed) + `store/capability_routing.py:246-259`;
  contrast the "A PACK PROPOSES ONCE" guard in `apply_mapping_pack` (:174-184).
- Scenario: operator approves a binding in review → worker restart or MCP
  re-vetting re-runs register_adapter_verbs → binding flips to proposed,
  route withdrawn. Human decision does not survive a reboot.
- Status: OPEN. No re-registration-survival test exists
  (`tests/kernel/test_capability_binding_review.py`).

## F-03 · MEDIUM(speculative) · trajectory purge needs only read visibility

- `kernel/trajectory_routes.py:100-111` — DELETE gated on
  `visible_work_item_by_run` alone; documented as deliberate ("available to
  whoever can read it"). Verbatim prompt/tool records are the incident-response
  evidence; audit rows are summaries without values.
- Status: OPEN — re-litigate the deliberate decision with the owner.

## F-04 · LOW(speculative) · trajectory LIST is workspace-unfenced

- `kernel/trajectory_routes.py:44-51` — acknowledged in-code; cross-workspace
  run counts/recency visible within a tenant.
- Status: OPEN.

## F-05 · LOW · negative limit becomes unbounded query

- `kernel/trajectory_routes.py:50` clamps only the top (`min(limit, 200)`);
  `?limit=-1` → `store/trajectory_postgres.py:102-111` `LIMIT $2` = -1 =
  NO LIMIT in Postgres, contradicting the "bounded reads" docstring (:29-31).
- Fix shape: `max(1, min(limit, 200))`. Status: OPEN (cheap).

## F-06 · LOW · revert failure reason swallowed server-side

- `kernel/platform_routes/run_effects.py:93-94` — `except Exception: return
  "revert_failed", None` with no log (contrast `kernel/revertible.py:84-86`).
- Status: OPEN (cheap).

## F-07 · LOW(speculative) · steered content executes attributed to the original sender

- `fleet/chat_turn_flow.py:108-130` + `:355-390` — a principal passing
  `resolve_conversation` can enqueue a steer into another user's active turn;
  it executes under the ORIGINAL requester's grants + on_behalf_of. Intra-tenant
  scoped-role power, but attribution is a seam worth a deliberate decision.
- Status: OPEN.

## F-08 · LOW(speculative) · AGENTS.md doctrine text stale vs dispatch order

- `kernel/dispatch.py` `_invoke_inner` now runs resolve → GRANT → validate
  (rationale: `kernel/routing.py:250-262`, `mcp_errors.py:24-38` —
  security-positive, schema rejection no longer describes verbs to ungranted
  callers). AGENTS.md still states "validate params -> grant check".
- Status: OPEN — update the doctrine text (one-paragraph doc change), do not
  revert the code.

## Older entries

(None — this file starts 2026-08-23; the July pre-arc findings live in
`arc-1/pre-arc/findings.md` and are all closed/triaged.)
