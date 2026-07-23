# 0017 - The two lawful trusted-Codex postures

- Status: accepted
- Date: 2026-07-23
- Relates: 0012 (Codex is the only target runtime), [2026] VJS-CC-VJS 2 D1,
  [2026] VJS-CC-VJS 7 J8

## Context

The trusted Codex wall (`boltrig/fleet/codex_trusted_wall.py`,
[2026] VJS-CC-VJS 2 D1) existed because the per-cell model bearer was minted
against an identity that was only *observed* (read from `/proc` by a
same-uid API), not kernel-attested. The court ruled that lawful only behind a
hard wall: single-operator dev auth, no production signal, and no real ingress
posture (OIDC / Cloudflare Access / session login). That barred every
deployment running session auth — i.e. every real chat deployment — from the
Codex lane, which 0012 says is the only target runtime.

Since then the per-cell-uid programme (Gap 5, [2026] VJS-CC-VJS 7) landed: a
privileged entrypoint forks a minimal spawner, hands the dropped API a live
spawner socket, and each cell runs under a distinct uid (2000N). The ingress
registers every App Server with its real uid, and peer attestation anchors on
the kernel-attested `SO_PEERCRED` uid (J8): a connecting auth-helper's uid must
equal the registered cell's uid, and issuance re-proves the cell's privilege
state (J5). The identity the bearer is minted against is now kernel-attested
end to end, which is the exact gap the wall was guarding.

## Decision

The wall admits exactly two postures, and both still require the explicit
`BOLTRIG_CODEX_TRUSTED` flag and refuse any production/staging signal:

- **(a) Legacy single-operator dev posture** — `BOLTRIG_DEV_AUTH=1` and no real
  ingress posture. Unchanged from VJS-CC-VJS 2 D1.
- **(b) Kernel-attested posture** — per-cell uids verifiably in force
  (`per_cell_uid_mode_available`: the dropped API holds the live spawner
  socket). Under (b) a real ingress posture, session login included, may
  coexist: the edge authenticates users and is not an input to cell identity,
  and a cell of one uid cannot be minted a bearer scoped to another.

This is not a production flip. `CodexAgentRuntime.production_ready` stays
`False`, the runtime still runs under the `allow_test_only_runtime` gate (D4),
and the court-gated `production_ready` application ([2026] VJS-CC-VJS 4 F9,
5 G1) is untouched. The claim is narrower: where cell identity is
kernel-attested, the HTTP edge's auth mode is no longer a reason to refuse the
lane.

## Consequences

- Chat can run on the Codex lane (including the SEC-184 kernel-tools lane) in a
  session-auth deployment that enacts per-cell uids; the pi bridge can retire.
- A session-auth deployment *without* per-cell uids is still refused, exactly
  as before — observed identity plus a multi-user edge remains the barred
  combination.
- Operators do not set a new flag: posture (b) is detected from the deployed
  privilege state, never asserted by configuration.
