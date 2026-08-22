# Handover: the release train, v0.4.37 to v0.4.45 (2026-08-22)

Written on the beelink by the session that ran the train from 2026-08-21 into
2026-08-22. Everything below is ON MAIN and DEPLOYED unless a section says
otherwise. Read sections 1 and 2 before touching anything; they are the ways
this work is destroyed by accident, and none of them fails loudly.

The companion documents are `apps/worker/tests/visual/HANDOVER-character-canon.md`
(the canon store, its one copy, and the verifier) and
`docs/HANDOVER-2026-08-22-ios-app.md` (the iPhone app). This one is about
getting things from a green PR to three running stacks and proving they got
there.

---

## 1. Where everything is right now

| stack | where | runs | how it gets a release |
| --- | --- | --- | --- |
| canary (`boltrig-*-1`) | `jellytot-prod`, compose project `boltrig` | **v0.4.45** | `scripts/roll-release.sh` (pinned overlay, migrate-then-deploy) |
| CV (`cv-boltrig-*-1`) | `jellytot-prod`, compose project `cv-boltrig` | **v0.4.45** | same script, second stack, gated on canary |
| dev (`boltrig-dev-*`, kernel on `127.0.0.1:8629`) | `jellytot-prod`, `~/boltrig-dev` | **v0.4.45** | NOT an image stack: backend by `git archive`, `dist/` from the ui image, migrations by hand (section 4) |
| beelink stack | this box | RETIRED 2026-08-21 (stopped, volumes intact) | one `up -d` restores it; Will: "dev is fine" |

All three report `readyz` `ready`, migration head `0086_conversation_addressing`,
and serve the identical bundle `index-DKnBn-fM.js`. The next migration number is
**0087**. The digest pins live in `~/Projects/opbox-prod-infra/boltrig-tenants/`
(`boltrig-io.override.yml` for canary, `cv/compose.override.yml` for CV; four
image lines each, kernel / fleet twice / ui), committed and pushed per release.

What each release carried, so you can bisect a regression by tag:

| tag | merged | what |
| --- | --- | --- |
| v0.4.37 | #329 | run-effect ledger (migration 0085), chromium advisory acceptance |
| v0.4.38 | #325 | turn-scoped chat + display objects, with the review's three defects fixed (migration 0086) |
| v0.4.39 | #331 | adapter inverses + the Undo affordance (approval-aware revert) |
| v0.4.40 | #333 #334 | mood reset row, `character_adopted` appraisal, a de-flaked emotion test |
| v0.4.41 | #336 | per-turn Codex tool-step budget (`BOLTRIG_CODEX_MAX_TOOL_STEPS`, default 16) |
| v0.4.42 | #337 | the brand-mark bodies: Jarvis V2, Ultron re-cut, Familiar states, character bench |
| v0.4.43 | #338 | THE CANON: Jarvis "v2 final 1822", Ultron "final 1800", Colossus say/sign |
| v0.4.44 | #340 #341 | character contracts docs; the arc reactor's original tuning (Will's pick) |
| v0.4.45 | #339 #344 #342 #343 | iPhone app + Familiar island; desktop hardening (boltrig.ai guard); data/storage docs |

`#335` (roll-script self-counting, reap-test de-flake) merged without a release.

## 2. The ways this breaks silently

**Dev is not an image stack.** `roll-release.sh` only knows canary and CV. Dev
gets `backend/boltrig` from `git archive <tag> boltrig migrations alembic.ini`,
`dist/` copied out of the ui image, and, when a release carries a migration, an
alembic run in a throwaway container on the stack's network. A release that
touches `libraries/*` reaches NEITHER CV nor dev through images: both mount their
own `libraries` directories; sync the files and bounce the kernel. If you roll
canary+CV and forget dev, `readyz` on 8629 still says `ready` - on the old code.

**The canon store is not in git.** `apps/worker/tests/visual/presets.json` is
gitignored; the one live copy is in `/home/jellytot/boltrig-fixtree` (Will's
bench tree) and the backups are in `~/Backups/shader-bench-settings-20260820-2010/`
(newest: `presets-20260822-0552-pre-main-merge.json`). The shipped tuning tables
are a DERIVED copy. Never `git clean -x` or re-clone that tree; never edit
`shader-bench.{ts,html}` there while Will is mixing (it reloads his tab).
`verify-canon-port.mjs` is the only thing that catches a tuning table merged
wrongly - run it after any merge that touches `src/components/canvas/`.

**The evidence digest counts the INDEX, not the worktree.**
`apps/worker/tests/visual/sourceDigest.mjs` hashes `git ls-files` under
`apps/worker/src` and `apps/worker/tests/visual` with current contents. A new
file you have not `git add`ed is invisible: the capture passes every local gate
and fails only in CI, which checks out everything. `git add` new files BEFORE the
recapture cascade, and commit `.vds/ledgers/*.yaml` together with the evidence.

The prose gate has the SAME blindness pointing the other way: it resolves a cited
path against the worktree, so an untracked or gitignored file makes the citation
pass locally and fail in CI. This document tripped it on its own first run, by
naming the canon store. Whenever a gate disagrees between here and CI, ask what
the two trees disagree about before you ask what the code does.

**A dirty PR runs no CI at all.** `mergeStateStatus: DIRTY` shows zero checks,
not red ones. Merge main in, push, and only then read the checks.

**The worker structural baseline is monotone in BOTH directions.**
`docs/refactoring/worker-structural-debt.json` may never record more debt than
`merge-base(HEAD, origin/main)`, AND the gate refuses a ratchet left stale-high
after you reduce a file ("lower the ratchet from N in this change"). New behavior
goes in NEW files; banking a reduction is mandatory. A branch that never ran
`make worker-structure` lands all its growth on whoever merges it up (bench-
unified: ~20 items at once, all paid down for real in #338).

**The document is the authority, the bundle is a copy.** `docs/characters/*.md`
section N (see `SHIPPED_SECTION` in the persona tests) must equal
`apps/worker/src/bundles/<name>/character.json` `prompts.system` VERBATIM, and
`boltrig/fleet/personas_shipped.py` is generated from the bundles
(`python3 scripts/gen_personas.py`, `--check` in CI). Editing the bundle alone
fails two tests; edit the document, copy to the bundle, regenerate.

## 3. Merging: what works and what the permission layer refuses

- `gh pr merge` is refused by the classifier. The sanctioned path, used for every
  merge this window on Will's explicit approval:
  `gh api repos/wlilley93/boltrig/pulls/<n>/merge -X PUT -f merge_method=merge`.
- `gh pr create` here sometimes produces a DRAFT ("Pull Request is still a
  draft" from the merge API): `gh pr ready <n>` first.
- 18 checks; `mergeStateStatus` must read `CLEAN`. CodeQL is not a required
  check, but do not leave its alerts open: fix the real vector, then if the
  query's heuristic still cannot see the guard (it cannot see a computed
  `Set.has(ev.origin)`, a fixpoint loop in `for` form, or any guard on a tainted
  property name), dismiss with the guard cited - "used in tests" for
  `tests/visual/`, "false positive" for our own build output. Comment cap is
  280 characters.
- Every `apps/worker/src` or `tests/visual` edit, including a merge-up,
  invalidates both capture receipts. The cascade, in order:
  `capture-current.mjs --evidence` (governed seven states; it promotes
  `current/` atomically and DELETES `diff/`, `metrics.json` and
  `vds-route-manifest.json`), `capture-current.mjs --additive-evidence`,
  `compare-current.py`, `git checkout HEAD -- .../vds-route-manifest.json`,
  `scripts/regen_vds_route_manifest.py` (rebinds; carries routes and
  doesNotCover through untouched), `vds ledger screens`, `vds ledger routes
  --from docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json`,
  `make vds-ledgers`. Pass `--playwright /home/jellytot/Projects/waymark/node_modules/playwright/index.mjs`
  on this box. Two concurrent merges ALWAYS conflict on the evidence trio - take
  either side, recapture on the merged tree, never hand-edit a digest.
- The committed Familiar island page
  (`ios/Boltrig/Resources/FamiliarIsland/familiar-island.html`) is a build of
  `apps/worker/src`; `make familiar-island-check` (inside `worker-quality`)
  refuses a stale one; `make familiar-island` rebuilds and syncs it.

## 4. The train, step by step

1. Main `ci` + `security` green on the merge sha
   (`gh run list --branch main`), never tag a sha whose CI you have not read.
2. `git fetch origin --tags` (a stale ref once refused to resolve the sha), then
   `git tag -a vX.Y.Z <sha> -m "..."` and `git push origin vX.Y.Z`.
3. `release.yml` fires on EVERY tag. Known transients, all cured by
   `gh run rerun <id> --failed` once the run has fully completed (it refuses
   while sibling jobs are pending): "expected exactly one GitHub release for
   vX" (a draft race - fired on 6 of the last 7 releases), a network reset
   mid-asset ("read: connection reset by peer"), and the macOS DMG bundling
   failure (`bundle_dmg.sh`) on PR checks. One wedge is NOT a transient: reruns
   rebuild candidates with new digests, so if a previous attempt attached
   `image-ref-X.txt` and `sbom-X.txt` and then died, every later rerun fails
   "immutable release asset image-ref-X.txt differs from this run". Cure: list
   the DRAFT release's assets (`gh api repos/wlilley93/boltrig/releases`, filter
   draft by tag), delete that image's partial triplet by asset id, rerun failed.
   Never touch a published release's assets. The release runs in `core` mode:
   desktop candidates are skipped there; the desktop packages are built and
   verified on the PR checks.
4. `gh release download vX --pattern "image-ref-*.txt"`, then sed the four image
   lines in each overlay from the previous tag and digest to the new ones; the
   script's repin check expects exactly two matching lines per image line
   (since #335 it counts them itself). Commit and push `opbox-prod-infra`.
5. Roll: `ROLL_HOST=jellytot-prod ROLL_TENANTS=/home/jellytot/Projects/opbox-prod/boltrig-tenants ROLL_COMPOSE=/home/jellytot/Projects/boltrig-main/docker-compose.yml ROLL_SRC=/home/jellytot/Projects/opbox-prod-infra/boltrig-tenants bash scripts/roll-release.sh vX.Y.Z`.
   Canary first, gated, then CV; each stack migrates then deploys; since #335
   the script pulls and bounces `hatchet-worker` itself. It ends with both
   kernels healthy, "addons active: opbox/1.0.0", and the unclaimed-bearer alarm
   silent.
6. Dev: `git archive vX boltrig migrations alembic.ini | gzip`, scp to
   `jellytot-prod:~/boltrig-dev/`, stage, pull `boltrig-ui:vX`, `docker cp` the
   image's `/usr/share/nginx/html` to a stage dir, stop `boltrig-dev-kernel` and
   `boltrig-dev-hatchet-worker`, swap `backend/boltrig` and `dist` (keep the old
   ones as `*.rollback-*` / `backend.old-*`), start. When the release carries no
   backend change (check `git diff --stat vPrev vX -- boltrig migrations
   libraries`), swap `dist` only. When it carries a migration, run alembic in a
   throwaway container on the `boltrig_default` network before starting. When it
   touches `libraries/`, copy the files into `~/boltrig-dev/config/libraries/`
   and CV's tenant dir, and bounce both kernels.
7. Verify AT THE DESTINATION, by content, not by exit code: `readyz` status and
   migration head on all three (canary `127.0.0.1:8628`, CV via `docker exec`
   on the kernel, dev `8629`); the served bundle hash identical on canary
   (`:8622`), CV (`:8621`) and `~/boltrig-dev/dist/index.html`; and one string
   literal the release is known to add, fetched from the served bundle. Probe
   literals that survive minification - GLSL source text, `"field:index"` map
   keys, asset URLs like `companion/jarvis-lattice.mp4` - never symbol names or
   comments. Desktop-only code is tree-shaken out of the web bundle; for it the
   PR's desktop-package checks are the measurement.
8. Record it. The train ledger is
   `~/.claude/projects/-home-jellytot/memory/boltrig-run-undo-program.md` on
   this box (it outgrew its name); one memory file per trap, indexed in
   `MEMORY.md` there.

## 5. Running with other sessions on the same repo

- `ListAgents` shows live peers on this box; their names are `SendMessage`
  addresses. Tell a session when its PR merges (a merged PR does not reopen on
  further pushes; it needs a new one). The iPhone session pinned its own done-tip
  in its memory note and confirmed "nothing to hold" before I merged - ask rather
  than race.
- A session that pulls a branch you are landing (bench-unified, feat/ios-app):
  merge main INTO the branch and push the merge (no rewrite), then it pulls
  cleanly. Never rebase a branch another session pulls.
- Branches: `bench-unified` is KEPT (the mixing session pulls it); superseded
  work goes under `archive/*` (the cheap supersession test is a post-merge
  `git diff origin/main HEAD` of zero lines); merged branches are pruned. Zero
  unmerged non-archive branches at the time of writing.
- The other sessions' parked work I found and landed: the hosted-shape
  hardening (#342, #343) from scratchpad worktrees under
  `/var/tmp/claude/claude-1011/-home-jellytot/*/scratchpad/`. Look there when a
  memory note says "unpushed".
- DNS on this box flaps (glibc "Temporary failure in name resolution" while
  `resolvectl` resolves). Every `gh`/`git push` step here is wrapped in
  retries; if a merge call returns nothing, the PR is probably still open.

## 6. Open, and whose call it is

- **Chromium advisory acceptance (Will or whoever is on the train):** 11 HIGH
  CVEs in `.trivyignore.yaml` + `docs/security/accepted-advisories.json`, expiry
  **2026-09-11**. Debian bookworm-security still serves `151.0.7922.137-1~deb12u1`
  (checked 2026-08-22); delete the entries the day `151.0.7922.169-1~deb12u1`
  appears, rebuild fleet, scan.
- **Codex production gate (Will):** `readyz` reports `codex_runtime: test_only,
  production_gate_closed, blocker_count 7`. The seven are the quarantined
  preflight receipt fields in
  `boltrig/fleet/infrastructure/codex_preflight_receipt.py`;
  `boltrig/observability/codex_admission.py` is explicit that opening it is an
  authority-backed change replacing the receipt source, not a constant flip.
- **Crest films (Will):** HELD by his word; Atlas returns 402. Would supersede
  the shipped `jarvis-lattice.mp4`.
- **V1 dial as default (Will, deliberate):** the canon is one skin-picker click
  away; do not "fix".
- **iPhone app, non-code track (Will):** privacy policy + demo credentials for
  App Review, `DELETE /v1/me` account deletion, the live run against dev, and the
  three desktop-link decisions (0027, sole-author relief, a published download
  address) - all in `docs/IOS-LAUNCH-READINESS.md` and the iOS handover.
- **opbox seam fix (opbox train):** `fix/ai-table-writes-via-kernel-seam`
  (`6d3107a9`) is pushed to the opbox relay, NOT merged or deployed; opbox has
  its own gates and roll.
- **Credential rotation (Will):** 38 items still owed at
  `~/Backups/opbox-db/CREDENTIAL-ROTATION-CHECKLIST-20260819.md`; the R2 pair is
  done.
- **Estate (parked):** the OrbStack move onto this box and the Balmoral
  consolidation wait on boltrig settling and the RAM resize respectively.

## 7. Facts you would otherwise hunt for

- Canary ports on `jellytot-prod`: kernel `127.0.0.1:8628`, ui `:8622`; CV ui
  `:8621`, CV kernel has no published port; dev kernel `:8629`; hatchet
  dashboards and engines are long-lived and untouched by the roll.
- The tool-step cap: `BOLTRIG_CODEX_MAX_TOOL_STEPS` (default 16, explicit 0 =
  unbounded) in `boltrig/fleet/codex_runtime_support.py`; a runaway weak-model
  turn now degrades as `codex_tool_budget_exhausted:<n>`. Dev is where that
  model lives.
- Ultron's settled tuning (`apps/worker/src/components/canvas/ultronTuning.ts`)
  carries main's live-membrane keys at their identity zeros on purpose: the
  canon was authored on the film deck (`lattice: [2.2, 0]` IS his membrane).
  Do not "restore" `membraneGain`.
- Merging `python-quality` locally: `make python-quality` is the CI step; run
  `.venv/bin/python -m pytest` for targeted suites (the system `python3` lacks
  `asyncpg`).
- The M4 is the only iOS build box and the only Xcode; the beelink is the only
  native amd64 builder; the fixtree is the live bench. Three machines, three
  jobs, do not cross them.
