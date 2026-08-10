# Handover — Familiar + Console, 2026-08-10

One day's arc: the Familiar became a browser-native shader being shipped inside
Worker, the console was redesigned to the decided target, the shader canon
moved into this repo, and the first two Boltrig Mobile screens were built. Four
sessions collaborated on a shared checkout; lanes and authorship are recorded
below.

**State at handover**: PR #265 (`feat/console-polish`) is green locally and
unmerged. Typecheck clean, 349 tests / 43 files, worker browser suite 22/22,
prose-claim gate 0 unresolved, working tree empty. Nothing is known-broken;
the outstanding work is one push plus three unbuilt mobile screens.

**The one remaining action**: relay-push `feat/console-polish` and merge #265.
Ten commits are unpushed. Read the "Pushing" note below first — the count and
the fetch state have both been wrong in this document before, so verify with
`git log --oneline origin/feat/console-polish..HEAD` rather than trusting any
number written here.

## Shipped (merged to main)

| PR | What | Key commits |
| --- | --- | --- |
| #261 | WebGL Familiar in Worker: ADR 0025, FamiliarBadge/Stage, state v2 SDK contract, phenotype projection (EMO-7), voice embodiment (AnalyserNode → 8 bands) | `98534a0` merge |
| #262 | Filament-shell shader vendored into Worker (fibre wash, hero streamers, breathing warp; genotype defaults via uGene) | `c9f1331` merge |
| #263 | Console redesign of Worker from the Claude Design artifact: tokens (both themes, WCAG-corrected), sidebar shell, chat surface, Stage placement, e2e+axe fixes | `2be2396` merge |
| #264 | Familiar canon migration: `familiar/` (canonical familiar.frag, GLES desktop host, familiar-bench, DESIGN-BRIEF, GENOTYPE) + byte-parity test binding the Worker copy | merged |

Also merged along the way: boltrig-familiar repo's `feat/filament-shell` and
`feat/familiar-unreal-preflight` (its master), and the UE vertical-slice
verdict recorded in `boltrig-familiar/docs/UNREAL-PREFLIGHT-M4.md` — that file
lives in the boltrig-familiar repo, not this tree.

## In flight — PR #265 (feat/console-polish)

Contents (multi-session, authorship in the PR body): parity session's
settings/Plugins-Routines work + decided-target Welcome (`e378f74`: quiet
empty state superseding ADR 0025 hero placement THERE only; 38vh Stage bound
fixing the user-hit short-window collapse; nav to the target four) + moved
acceptance contract (`553b578`, Playwright 22/22 verified); this session's
renderer black-hole retirement, /v1/cost ledger reclassification, VDS register
commit, breakpoint-race fix, lint, gitleaks allowlist (`e5ab36d`, ready in the
worktree at scratchpad/polish-wt, NOT yet pushed — the disk-full block that
stopped it is now cleared, so this is simply outstanding).

Outstanding to land it:
1. ~~**Disk space** on the M4~~ — RESOLVED. Was 100% full (0 bytes); now 55Gi
   free. Cause per the DAG session: docker builds plus repeated live-test runs
   inflated OrbStack's sparse image, which only compacts on
   `orb stop && orb start`. It is worth knowing what full looks like from
   inside a session: `Edit` fails with `ENOSPC ... .tmp`, Bash cannot open its
   own output file, and a full vitest run reports dozens of unrelated test
   FILES failing to collect. None of that is a code fault — check `df` first.
2. ~~**ui-e2e red**~~ — FIXED by the DAG session in `ef703be`:
   `e2e/workflow-live.spec.ts:18` used `toHaveValue` on `.wf3-header__name`,
   but the chat-first pivot made the Studio canvas read-only, so that name is
   now a static `<span>`. Now `toHaveText`; ui typecheck clean.
3. Security gate: WAS red on a gitleaks false positive — the VDS figma ledger
   `file_key` (a URL identifier, not a credential). Fixed by narrow allowlist
   in `.gitleaks.toml`; verified locally (977 commits, 0 leaks).
4. **Claim gate**: was red on ONE unresolved prose reference — line 19 of this
   very file, pointing at `docs/UNREAL-PREFLIGHT-M4.md`, which lives in the
   boltrig-familiar repo and not this tree. Fixed by naming the repo; the
   checker (`scripts/check_prose_references.py`, run it directly) now passes
   with 0 unresolved. Note this file is still UNTRACKED — it must be committed
   or dropped before the gate means anything in CI.
5. **Unpushed**: 10 commits sit local on `feat/console-polish` — this
   session's (`b455da7`, `c847e24`, `280a7b4`, `d3644ae`), the DAG session's
   (`93b3e07`, `ef703be`, `41c4687`, `10cb92f`), and the merge below. The M4
   has no GitHub creds — see the relay recipe.

   Beware the arithmetic here. Counting against `main` gives 27 and counting
   against a stale `origin/main` gave 21; both were quoted as "unpushed" at
   points today and both were wrong. The only count that means anything is
   against the remote BRANCH: `git log --oneline origin/feat/console-polish..HEAD`.
6. **`git fetch` works from the M4** even though pushing does not — read
   access needs no local creds. It had not been run since 10:59 today, which
   is why the numbers above drifted. Fetch before trusting any of them.
7. **The remote branch can be ahead of you.** `9e2007f` (a lint fix to
   `tests/unit/test_workflow_parity.py`, authored via the relay by another
   session at 15:26) existed only on `origin/feat/console-polish`. It is now
   merged in locally — by MERGE, deliberately, not rebase, so that the commit
   hashes quoted throughout this document stay valid. A blind `git push
   --force` from the M4 would have destroyed it. Always fetch and integrate
   first.
8. Merge on green via `gh pr merge 265` on the beelink.

## Boltrig Mobile — 2 of 5 screens built (this session, on feat/console-polish)

The Claude Design project's "Boltrig Mobile" was listed as unimplemented. Two
of its five screens now exist, built against real data, plus the mobile chat
surface that preceded them.

| Commit | Screen | Notes |
| --- | --- | --- |
| `b455da7` | **Today** (phone home) | Pending decisions from the HITL list with Approve / Not now wired to `respondHitl`; conversations split "Working now" / "Earlier" |
| `c847e24` | **Settings** + **Settings detail** | iOS grouped list from `SETTINGS_SECTIONS`; detail reuses the console's `SettingsSectionPane` under a mobile head |

Two decisions worth keeping:

- **Today lives on the `home` route, not on "phone with no conversation".**
  The obvious wiring — render Today whenever a phone has no conversation
  selected — removed the task-details trigger at that width and broke the
  invariant `39c14bd` establishes (one trigger at every width, stable across a
  breakpoint flip). Routing Today separately leaves the conversation surface
  untouched at every width; the browser flip test passes unedited.
- **The detail screen reuses the console pane rather than restating it.**
  Sections come from `SETTINGS_SECTIONS`; the body is the same component the
  console renders, so the phone cannot drift from the console on budgets,
  readiness or the archive. `SettingsSectionPane` grew one `head` prop so
  mobile can draw its own title without the console head appearing twice.
  Console chrome is restyled inside `.mobile-surface` only.

`useMediaQuery` moved out of `ChatView` into `apps/worker/src/useMediaQuery.ts`
— App needs a breakpoint, and importing the hook from `ChatView` made every
test that mocks `ChatView` fail on a missing export.

**Remaining: 3 of 5 screens** — Helper, and the two the target draws that this
session did not reach. Settings at phone width was previously falling through
to the console surface; that is now the mobile list, but **Helper still falls
through**. Design source: `Boltrig Mobile.dc.html` in the Claude Design export.

Verified at the time of writing: typecheck clean, **349 tests / 43 files**,
worker browser suite **22/22** including the axe sweep.

## Session lanes (agreed)

- **Console-parity session**: apps/worker console surfaces (design source: the
  user's 2026-08-10 12:31 export "Theme control and settings design.zip";
  decided target pinned in Figma file `iVQBKFc3NpRH3zdOOxfPqr` and the `.vds`
  register). Their recovery patch (now redundant):
  `/private/tmp/claude-501/-Users-williamlilley/e9926e7a…/scratchpad/console-parity-uncommitted.patch`.
- **DAG-rollout session**: boltrig/workflows, ui/src/panels/workflowCanvas,
  docker-compose, sdks/web, VM deployment. They held a freeze on branch
  switches/resets in the shared checkout while their Docker roll built off the
  tree; **that freeze has since been lifted** — the VM build finished and the
  roll is done. Still worth announcing a branch op, since the checkout is
  shared four ways.
- **This session** (console-redesign/familiar): familiar/ canon, the Worker
  familiar renderer, release mechanics (relay pushes, PRs, merges).
- Loose in the tree: RESOLVED, the working tree is now clean. All three strays
  are gone — `tests/integration/test_hatchet_live.py` was committed by the DAG
  session in `41c4687`; `apps/worker/pnpm-workspace.yaml` (an unfilled pnpm
  stub reading `esbuild: set this to true or false`) and
  `sdks/web/package-lock.json` (a stray npm lockfile in a pnpm workspace) were
  debris from the broken pnpm store. Both were moved, not deleted — they are
  untracked, so git could not bring them back — to this session's scratchpad
  under `stray-artifacts/`. Typecheck, 349 tests and a production build all
  pass without them.
- Also landed by the DAG session today, none touching `apps/worker`: `93b3e07`
  (draft lane: `control.workflow.draft.upsert` low-consequence, publish high),
  `41c4687` (live-test fixes), `10cb92f` and
  `docs/HANDOVER-2026-08-10-workflow-dag.md` (their handover). Their
  boltrig-vm roll is DONE — hatchet-worker serving, 3/4 live DAG gates passed
  including kill/restart/resume — and the branch-op freeze on the shared
  checkout is **lifted**.

## Operational facts (also in Claude memory)

- **Pushing**: the M4 has no GitHub creds. Relay: push branch →
  `ssh -p 24222 jellytot@beelink` clone of boltrig → `git push origin` /
  `gh pr create` / `gh pr merge` there (gh is authed as wlilley93; main is
  protected, PRs only). The pre-push gate validates the WORKING TREE — push
  from a `git worktree` matching the branch (detached at the tip works;
  a branch checked out elsewhere can't get a second worktree).
- **Worker e2e locally**: pnpm store is broken (`make worker-e2e` dies).
  Recipe that ran green today (22/22), from `apps/worker`:

      ./node_modules/.bin/vite build
      BOLTRIG_KERNEL_URL=http://127.0.0.1:8792 \
        ./node_modules/.bin/vite preview --host 127.0.0.1 --port 4180 --strictPort

  then from `ui/`: `BOLTRIG_E2E_PYTHON=$HOME/Projects/boltrig/.venv/bin/python3
  ./node_modules/.bin/playwright test --config=playwright.worker.config.ts`.

  **The trap that cost time today**: `BOLTRIG_KERNEL_URL` is read by
  `apps/worker/vite.config.ts` to configure the PREVIEW PROXY, so it must be
  set on the `vite preview` command, not just at build. Omit it and the proxy
  points at the default `localhost:8000`, the app renders the sign-in screen,
  and five specs fail on a missing `Worker navigation` sidebar — which reads
  exactly like a render crash in your own code. If specs fail that way, load
  the preview URL and look at the page before debugging components.

  Other traps: stale preview on reuse (kill the port between builds); the
  in-memory kernel accumulates seeded HITLs (restart between runs). Vitest's
  reporter is `dot`/`verbose` — `--reporter=line` is Playwright's and dies with
  an unrelated `ERR_LOAD_URL`.
- **Dev stack**: kernel runs in OrbStack `boltrig-vm`, host port **18000**
  (`orb start boltrig-vm` if stopped). Dev worker:
  `BOLTRIG_KERNEL_URL=http://192.168.139.14:18000 vite --port 1420`.
  Dev login: will.lilley93@gmail.com; password was reset today via
  `boltrig set-password` inside the kernel container (value in this session's
  scratchpad dev-pw.txt; change at will).
- **Gitleaks locally**: run against the REAL repo dir, not a linked worktree
  (the container can't follow the .git pointer file → "0 commits scanned",
  a vacuous green).

## Decisions of record

- **The Familiar is the shader** (boltrig-familiar/docs/UNREAL-PREFLIGHT-M4.md
  "Outcome"): browser/consumer hardware, 2D composition. UE retired; engine
  deleted from the M4; the FamiliarUE project + MCP authoring pipeline remain
  in boltrig-familiar as the experiment record. boltrig-familiar is otherwise
  an archive candidate.
- **Canon lives here**: `familiar/` is the source of truth; the Worker copy is
  held byte-identical by `apps/worker/tests/familiarShaderParity.test.ts`.
- **ADR 0025 placement, as amended by the decided target** (recorded in
  `e378f74` and the Figma/VDS register): empty state opens quiet (no hero
  Stage); the one Stage is the newest assistant turn's bullet (bob 2.5px/7.9s,
  rotate 42s, reduced-motion aware); voice calls centre it; black-hole
  entrance retired (aperture starts open).
- Desktop familiar: filament shader installed to the beelink's
  `~/.config/familiar/` — applies next time familiar-bg runs (no active
  session at install time).

## Cross-lane state at close (both sessions reconciled)

The DAG-rollout session and this one closed out against each other: tree clean
both sides, nothing mid-flight, no ordering constraint between our commits.
Their remaining work is post-#265 and briefed in
`docs/HANDOVER-2026-08-10-workflow-dag.md`: Will's hands-on Studio session
(human UX validation of the chat-first authoring loop), then studio polish and
Hatchet child-run fan-out. Their boltrig-vm roll is done — hatchet-worker
serving, 3/4 live DAG gates passed including kill/restart/resume.

## Backlog (post-#265)

- FamiliarState v2 full adoption: server-side activity events + familiar.express
  gestures into the Stage (contract + sanitizer already in the SDK).
- MilkDrop-harvest host upgrades: AGC attack/release bands, band-integrated
  time, spring-chain nucleus (cheap JS, big "alive" payoff).
- Genotype-driven per-agent Stage identity (uGene currently canonical defaults).
- Console: right-rail run groups, subagent tabs, DAG-editor/Build/Knowledge
  skins, "What's new" popover (needs changelog source), light-theme taste pass.
- Unimplemented designs in the Claude Design project: **Boltrig Mobile — 3 of 5
  screens remain** (Helper still falls through to the console surface at phone
  width; see the Boltrig Mobile section above), and Codex Chat (untouched).
- VDS: 62 register records at `proposed`; contrast floor removal needs a
  warrant (assent event) — see .vds/logs/decisions/DECISION-0002.yaml.
- Housekeeping: archive boltrig-familiar on GitHub; delete merged local
  branches (grep for the feature first — several stale branches were already
  reimplemented under other hashes).
