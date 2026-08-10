# Handover — Workflow DAG parity, chat-first Studio, production roll

**Date:** 2026-08-10
**Branch:** `feat/console-polish` (converged; carries this work + the console second pass)
**Scope:** boltrig's workflow/automation DAG system — engine semantics, the chat-first Studio, the SDK, the production roll to `boltrig-vm`, and live validation.

Companion specs (on disk, not in repo): `~/dify-graphon-cleanroom-spec.md`, `~/boltrig-workflow-spec.md`. The first drove this build; §5 is the parity map.

---

## 1. What this delivered (all committed)

The goal was a "world-class dify/graphon-level DAG system, run by boltrig and inside boltrig." The engine now covers graphon's compositional core, authored in chat, governed at the one `kernel.invoke` chokepoint, durable on Hatchet, **serving in production**.

Commits (newest first, on `feat/console-polish`):

| Commit | What |
|---|---|
| `ef703be` | e2e: read-only Studio header asserted as text not input value |
| `93b3e07` | **Draft lane** — low-consequence draft upsert + high-consequence publish |
| `41c4687` | **Live Hatchet gates made runnable; 3 passed live** |
| `4e19f9a` | ui: keep only the live SDK release-age exclusion (pnpm footgun) |
| `8293002` | ui: consume published boltrig-web-sdk 0.2.0 |
| `66baa05` | e2e chat-first authoring loop validated in-process; SDK 0.2.0 bump |
| `180a717` | **parallel loop iterations + routable approval rejection/timeout** |
| (earlier, pre-converge) `41c37d6` `985081a` | OR-join/skip lineages, multi-case branch, error strategies+retry, loop error modes, `parallel:N`, `$inputs`, chat-first Studio, diff preview, inline approvals |

### Engine (`boltrig/workflows/`)
- **OR-join / skip lineages** (`interpreter.py`): two skip sets — failure lineage (`parent_failed`, fail-closed) vs benign branch lineage (`parents_skipped`). A merge after an if/else runs once off the taken arm; skips only when *every* parent skipped. This is the load-bearing compositional change.
- **Multi-case `flow.branch`** + 9 operators (`control_flow.py`): `cases:[{label,logical_operator,conditions}]`, first-match-wins, `default_label`; ops incl. `not_in/not_contains/starts_with/ends_with/empty/is_null/…`, all fail-closed.
- **Per-step error strategies + retry** (`step_execution.py`): `on_error: fail|branch|default` (+`default_output`), `retry:{max≤5,interval_ms≤60_000}`. Absorbed failures → status `exception`, checkpointed `ok`, surfaced as run `exceptions_count` (honest partial success, projection-safe).
- **Loop item error modes + windowed parallelism** (`loop_execution.py`): `on_item_error: fail|continue|drop`; `parallel:N` (1–10) runs capability-only iterations concurrently, N at a time (graphon's `parallel_nums`); control-bearing bodies fall back sequential; drain-then-stop on pause.
- **Approval branch handles** (`step_execution.resolve_pause_disposition`): a resumed paused step *reads* its checkpointed HITL request; an explicitly **rejected** or **timed-out** approval routes the `on_error` arm (`approval_rejected`/`approval_timeout`) instead of re-asking forever. **The consume CAS remains the sole execution authority — SEC-14 untouched; the gated verb never runs on a declined approval.**
- **`$inputs.<key>`** sugar: run inputs referenceable directly; a real step named `inputs` always wins.

### Draft lane (`boltrig/config/control_workflow*.py`, `93b3e07`)
- `control.workflow.draft.upsert` (LOW consequence, no hold) writes `__draft__:<id>` — reserved prefix, excluded from every runnable path in `library.py`, cannot shadow the shelf.
- `control.workflow.publish` (HIGH) copies the draft to the real id via the ordinary upsert path.
- Prefix is kernel-reserved (ordinary upsert rejects it). Both still flow through `kernel.invoke`; only the HITL gate differs by consequence.

### Chat-first Studio (`ui/src/panels/workflowCanvas/`)
The canvas is a **read-only projection**; the docked side panel chat is the only authoring channel (drawer/drag-drop/connect/save/undo removed).
- `useStudioChat.ts` — one conversation per workflow (sessionStorage), grounded first turn, activity trail, inline HITL cards.
- `BoltChatPanel.tsx` — inline Approve/Reject via the one respond path; **Preview** on an upsert hold renders the proposed definition as a canvas diff (`workflowDiff.ts`: added/removed/changed badges, removed ghosted).
- `NodeDetailModal.tsx` — inspect-only with "Ask in chat" (`@step` mention).

### SDK (`sdks/web`, **published 0.2.0**)
Adds `reason` on `workflow_step`, `exception` status + `exceptions_count` on run records. Published to GitHub Packages; both frontends consume it (console via pnpm; `apps/worker` via `file:`).

---

## 2. Production state — LIVE

Rolled to `boltrig-vm` (192.168.139.14) 2026-08-10 ~14:24. The VM compose builds **directly off the shared Mac checkout** (`/Users/williamlilley/Projects/boltrig`, OrbStack mount), overlay `docker-compose.vm.yml`.

- `boltrig-hatchet-worker-1` **serving** (`'boltrig-live' … waiting for tasks`) — the first time the durable lane has a serving process (closes the decision-0018 gap). Kernel/`/readyz` fully green, hatchet probe ok.
- No engine recreate → token safe. DB already at head `0067` → no migrations.

### Live validation — 3/4 DAG gates PASSED against the real engine
Run inside the VM (`test_hatchet_live.py`), production worker paused for a clean window:
- ✅ `test_live_invoke_reenters_the_chokepoint`
- ✅ `test_live_workflow_run_pauses_on_gated_step`
- ✅ `test_live_kill_restart_approve_resume` — **SIGKILL mid-run → durable resume → exactly-once** (the crown jewel)
- ❌ `test_live_ultracode_run_fans_out_agent_child_tasks` — needs an agent/model runtime the bare test env lacks; **ultracode lane's concern, not the DAG's.**

**How to re-run the live suite (from inside the VM — never from macOS against the live engine, the worker name `boltrig-live` would claim real tasks):**
```
orb -m boltrig-vm sh -c '
  NET=$(docker inspect boltrig-postgres-1 --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}{{end}}")
  docker run --rm -d --name pgfwd --network "$NET" -p 127.0.0.1:15432:5432 alpine/socat tcp-listen:5432,fork,reuseaddr tcp:postgres:5432
  PW=$(grep "^POSTGRES_PASSWORD=" .env | cut -d= -f2-); TOKEN=$(grep "^HATCHET_CLIENT_TOKEN=" .env | cut -d= -f2-)
  docker stop boltrig-hatchet-worker-1
  UV_PROJECT_ENVIRONMENT=/home/williamlilley/.venvs/boltrig-linux \
    HATCHET_CLIENT_TOKEN="$TOKEN" HATCHET_CLIENT_TLS_STRATEGY=none \
    BOLTRIG_TEST_DATABASE_URL="postgresql://boltrig:$PW@127.0.0.1:15432/boltrig" \
    uv run --extra durable pytest tests/integration/test_hatchet_live.py -q
  docker start boltrig-hatchet-worker-1; docker rm -f pgfwd'
```
Env gotchas that cost time (all now handled, recorded so you don't rediscover them):
- The shared `.venv` is **mac-built**; Linux uv needs `UV_PROJECT_ENVIRONMENT=~/.venvs/boltrig-linux` + `--extra durable`.
- `tests/conftest` strips `DATABASE_URL` for hermeticity; the **sanctioned kept var is `BOLTRIG_TEST_DATABASE_URL`** (the live tests now read it; the spawned worker re-injects it).
- The SDK resolves the token's broadcast name `hatchet-engine`; the VM's `/etc/hosts` has `127.0.0.1 hatchet-engine` (additive, removable).
- postgres publishes no host port → the temporary `alpine/socat` forward above.

---

## 3. Open items (ranked)

1. **Will's Studio session** — the one human validation left: open the Workflow Studio, author a workflow in the side panel → Preview diff → Approve inline → Run → watch `workflow_step` events (with reasons) stream and the record land with `exceptions_count`. Everything backing it is live; only a person can judge the UX loop.
2. **Ultracode live gate** — needs an agent/model runtime in the test env. Ultracode lane owns it; not blocking the DAG.
3. **Studio polish** (Phase D, plan `~/.claude/plans/serialized-scribbling-sparkle.md`): inspector showing registry-resolved contract (will-it-pause / adapter-vs-agent / grant check); live-run overlay inside the Studio view (reuse `WorkflowRunCanvas`/`useRunStream`); delete dead undo/redo plumbing (`useGraphHistory` + wiring); `npm pkg fix` in `sdks/web`; a health receipt for the `hatchet-worker` compose service.
4. **Hatchet child-run fan-out** (Phase E, large, design-first): iteration items as real engine child runs (`aio_run`, pattern in `fleet/hatchet_ultracode.py`) — true distributed parallelism beyond graphon parity. **Will's UX vision (anchor for the design):** children presented like *subagent runs in a chat transcript* — the orchestrator run reads as a chat in your own history, vertical-rail fan-out inside the horizontal-rail Hatchet workflow. Build on `SubRunPanel`. Design doc must settle: child input shape (snapshot + clone group + ctx envelope + parent run id), checkpoint coordination (children write own `(tenant,child_run_id,step)`; parent aggregates by deterministic ids), HITL-inside-a-child, `on_item_error` mapping.

---

## 4. Coordination / environment notes

**Both sessions reconciled as of end-of-day 2026-08-10 — nothing mid-flight either side.** `feat/console-polish` carries **23 commits** (this workflow work + the console/mobile second pass), `git status` clean, claim gate **0 unresolved**, worker browser suite 22/22, unit green. Ready to relay-push through the beelink (the M4 has no GitHub creds) to land PR #265; nothing of this lane needs to land first or separately.

- **Peer session** (`feat/console-polish`) owns `apps/worker` chat/Shell/familiar/mobile surfaces — lanes agreed; don't edit those. Their landed work: `b455da7` (mobile "Today"→respondHitl), `c847e24` (mobile settings), `280a7b4`+`d3644ae` (their handover). The e2e red they flagged was mine and is **fixed** (`ef703be`).
- **Claim gate: GREEN.** The earlier failure was the peer's untracked handover pointing at an out-of-tree preflight doc; they repointed it to `boltrig-familiar/…` and committed the file (`280a7b4`). Verified `unresolved=0` across 866 prose files.
- **Shared-tree fact:** `useMediaQuery` moved from `apps/worker/.../ChatView.tsx` to `apps/worker/src/useMediaQuery.ts`. No importers in this workflow lane (verified); flagged only for future apps/worker work.
- **Live-recipe correction (from the peer, for the *browser* Studio session, not the python recipe in §2):** `BOLTRIG_KERNEL_URL` must be set on the `vite preview` command, not just at build — `vite.config.ts` reads it for the preview proxy; omitting it silently serves the sign-in screen and fails specs on a missing sidebar (looks like a render crash).
- **DISK — this bit hard, twice.** The Mac Data volume hit **100% / 0 bytes** mid-session (both sessions independently). Symptom reads like a code fault: `Edit` fails with `ENOSPC …tmp`, `Bash` can't open its own output file, a full `vitest` run reports ~40 unrelated test *files* failing to collect (all pass individually after). Cause: Docker builds + repeated 6-min live-test runs inflate OrbStack's **sparse image on the Mac**; VM-internal `docker image/builder prune` frees the VM but the Mac image only shrinks on **`orb stop && orb start`** (compaction). Colima is the *active* docker context yet OrbStack runs the stack — `colima delete` reclaims a redundant VM. **Avoid Docker builds when the volume is tight;** remaining plan work (polish) is code+tests only.
- **Structure ratchet**: `interpreter.py` exemption pinned 393/275; new logic extracted into `step_execution.py`/`loop_execution.py` to stay under limits. Re-pin only downward.
- **Verification bar** (for C/D/E): existing suites byte-identical to the known macOS baseline (29 pre-existing codex-sandbox failures need the Linux VM); new behavior lands with tests in `tests/unit/test_workflow_parity.py`, `tests/security/`, or the e2e file.

---

## 5. Fast start for the next session
```
cd ~/Projects/boltrig && git log --oneline -8        # orient on the lineage above
uv run pytest tests/unit/test_workflow_parity.py tests/security/test_workflow_draft_lane.py \
              tests/integration/test_chat_first_authoring_e2e.py -q   # green in ~1s
```
Then pick item 1 (hand to Will) or item 3 (Studio polish — safe, no builds). Plan file: `~/.claude/plans/serialized-scribbling-sparkle.md`.
