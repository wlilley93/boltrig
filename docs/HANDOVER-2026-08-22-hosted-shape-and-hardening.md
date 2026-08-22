# Handover 2026-08-22: the hosted shape is kept, and what was hardened

Session: the boltrig pen-holder on the beelink, working in scratchpad
worktrees off `origin/main` because `~/Projects/boltrig` was on another
session's branch all day. Companion: the Principal's M4 session, which
recaptured evidence on #342 and adjusted the prose gate on #343 while this
ran. Everything below is measured unless marked otherwise.

## 1. The decision

The day started as a question ("can a Boltrig agent add to or see Opbox
Tables when Opbox is not installed?" answer: no, and it is a real gap, see
`docs/PROPOSAL-native-tables-surface.md`) and became a product-shape
question once the dmg's contents were measured: the desktop is the Worker UI,
native shims and a pinned Codex 0.144.3, with the API origin baked at build.
No database, no object store. The Principal considered a private-first shape
(local kernel, own GPU, only auth phoning home) and then chose: **"harden
what we have and phone home."** The desktop stays a client that logs into the
server; its local agent keeps real reach on the user's computer (decision
0027); cloud runs get a per-run sandbox cell, not a machine per agent
(`boltrig/fleet/infrastructure/codex_cell_provisioning.py`,
`boltrig/fleet/infrastructure/codex_cell_supervisor.py`). The private shape
and the native tables surface are parked, recorded, and not scheduled.

## 2. What landed, as three draft PRs

**boltrig #342, `harden/desktop-origin-and-local-runtime`.** `1385f330`
admits `boltrig.ai` and `*.boltrig.ai` in the Tauri CSP and the release
origin guard (the guard still pinned `boltrig.io` four days after the domain
move; a desktop build for `app.boltrig.ai` could not be produced). `779a64ed`
runs the bundled Codex under an app-private `CODEX_HOME` (owner-only, a
minimal `config.toml` seeded once, never inherited from the launching
environment), adds device-code sign-in and sign-out for local tasks in
Settings, Advanced, and amends decision 0027. Re-run by the integrator:
`cargo test` 49/49 (7 new), `tsc --noEmit` clean, `pnpm structure` pass,
pytest subset 44/44, worker vitest 1107/1108 with the one red being the
source-bound evidence receipt. The Principal then pushed `fa73aa53` and
`b86cb834` from the M4 (merge of main plus evidence recapture); CI on
`b86cb834` is green for both `ci` and `security`.

**boltrig #343, `docs/data-storage-and-tables-proposal`.** `6f357759` adds
`docs/DATA-AND-STORAGE.md` (the Boltrig answer to "does the app have its own
database, and what leaves my computer", written in the shape of the Codex
storage explainer), `docs/PROPOSAL-native-tables-surface.md` (deferred), and
corrects the "kernel table verbs" wording in
`docs/PLAN-opbox-boltrig-merge-2026-08-17.md` and decision 0034 (documents are
written through the kernel `tables.*` plural family, not the fact-per-cell
`table.*` data plane). `9de23fd7` (Principal) lets the prose gate accept the
files a deferred proposal says it would create. CI 18/18.

**opbox-frontend #213, `fix/ai-table-writes-via-kernel-seam`.** `6d3107a9`
closes a split-brain writer: the AI/MCP tables tool family wrote the Tables
SoR Prisma-direct while the HTTP routes wrote the same tables through the
kernel `tables.*` seam. All eleven AI/MCP table writes now dispatch the seam
with the caller's kernel bearer (fail-closed, no seat or Prisma fallback),
reads stay Prisma, side-effects are shared. Verified: targeted vitest 80/80,
wider suites 154 files / 1771 tests, eslint clean, `tsc --noEmit` exit 0, and
the repo's pre-push hook ran tsc plus "gate census + 12 gate(s) clean" on
push. Two docs ship with it: the verified before/after handler map and a
runbook for the MCP agent seat verb fence.

## 3. What is open, in order

1. Merge #343, then #342 (both green).
2. #213 needs, before merge, one `npm run build` on the M4 or another quiet
   box (opbox-frontend has no CI). On the beelink three attempts died: one
   SIGTERMed at 41 minutes under load 100+, two killed by the build lock's
   12 GiB RSS ceiling (exit 137, "not by a build error") at the default and
   the 6144 MiB heap. Webpack compiled cleanly once and the type pass is
   clean twice, so the code is not in doubt; the single-invocation verdict is.
3. #213 needs, before DEPLOY, the three demo MCP agent seats re-minted with
   the `tables.*` verbs (they were minted 2026-08-21 with a 67-verb fence
   that predates this change). Seats first, image second, or MCP-door table
   writes return FORBIDDEN. The Principal chose to do this at deploy time.
   The runbook in #213 carries the verb list and the procedure.
4. Not done, deliberately: no seat minting, no merges, no database change,
   no court record (the private-shape forks became moot when the shape was
   kept), no API-key sign-in path in the desktop UI.

## 4. Traps met today, for whoever is next

- **The shell cap is ten minutes; the opbox pre-push hook is longer.** It
  only completed inside tmux (8 minutes at low load). tmux suffered one
  transient DNS failure ("Could not resolve host: github.com") and the box's
  resolver blipped twice more during the day; retry before diagnosing.
- **The build lock's 12 GiB ceiling is real and it is per build.** Under
  cross-session load (load average 80 to 118, swap 100% full at one point,
  186 MB free) the production build does not fit. Do not raise the ceiling
  on the shared box; run the build where it is quiet.
- **The stale-Prisma-client pre-push check is an mtime heuristic.** A fresh
  worktree checkout trips it with a byte-identical schema. Set the worktree
  schema's mtime to its source (`touch -r`) rather than regenerate the shared
  client under another session's tsc or bypass the gate.
- **`~/Projects/boltrig` and `~/Projects/opbox-build-main` moved under me
  twice each.** Other sessions own those trees; work in a worktree off
  `origin/main`, never in them.
- **A subagent that ends its turn waiting on a background waiter may lose
  the waiter.** The opbox agent's build survived its turn once and was
  SIGTERMed the second time; the integrator finished the gates and committed.
- **Two heap-sized type-checks at once is what the lock exists to prevent.**
  When an agent and the main loop each start one, kill the duplicate first
  and ask questions after; memory went from 186 MB free to 11.6 GB on the
  kill.
- **`CODEX_HOME` semantics changed on #342.** Before: inherited if the
  launching environment had it, otherwise the user's personal `~/.codex`
  (their MCP servers, provider overrides, memories, history flowed into
  Boltrig local tasks). After: always the app-private home, and local tasks
  are unsigned until the user signs the runtime in. Plain `codex login` binds
  a local port and launches a browser itself; the device-code flow does
  neither, which is why it was chosen.

## 5. Where things are

Branches are on origin under the names above. The scratchpad worktrees
(`boltrig-harden`, `boltrig-docs2`, `opbox-harden`) live under this session's
scratchpad and may be cleaned; nothing depends on them. The memory note
`boltrig-hosted-shape-hardening-2026-08-22.md` in the pen-holder's memory
carries the same PR numbers and the two pre-merge/deploy steps.
