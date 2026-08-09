# HANDOVER 2026-08-09 - sleep distillation is live to its first approval

State of the world at handover, for whoever picks up the pen (probably the
owner, whose click is the next act).

## What is running

- **Sidecar**: `app.boltrig.distill` (launchd, native for Metal), loopback on
  :8930, `~/opbox-dev/run-distill-sidecar.sh`, mlx venv at
  `~/opbox-dev/mlx-venv`, state under `~/.local/state/boltrig-distill`.
  `curl localhost:8930/health` -> `{"status": "ok", "mlx": true}`. The
  7B base (`mlx-community/Qwen2.5-7B-Instruct-4bit`) is in the HF cache.
- **Kernel** (boltrig-vm): rebuilt from `feat/sleep-distillation`, logs
  `distill subsystem enabled (base_pin=...Qwen2.5-7B-Instruct-4bit@main)`.
  The deployment `manifest.yaml` (gitignored) carries the `distill:` section -
  register lane only; no `serve_url`, so the craft gate refuses typed until an
  `mlx_lm.server` is stood up.

## What already happened, on the record

- First real corpus through the chokepoint: **32 records** from 89
  conversations / 180 messages, **4 deduped**, **erasure watermark
  2026-08-05** (42 erasures honoured), signals **100% clean_run** - no
  human-anchored signal exists in this tenant's history yet, and the
  composition receipt says so.
- `distill.night` (register, target `local-sensitive`, no auto-promote)
  parked **pending_human** - the high-consequence gate, working as decision
  0023 requires for the first cutover.

## The next acts are the owner's (by design, not omission)

1. **Approve HITL `15041c1105e24377aa4c2adc582a2a74`** (distill.night) in the
   console. SEC-14 stops the requesting credential approving itself; the
   sole-author exemption admits the owner's session. On approval the durable
   pause resumes: corpus rebuild -> 7B register LoRA train (the adapter
   timeout is 1800s; training runs under the sidecar's one-at-a-time lock) ->
   held-out likelihood + entropy guard -> a gate receipt either way. NO
   promotion happens.
2. HITL `e2df849d6ce841f49b04886c18be7c66` (`control.model_endpoint.upsert`
   for `register-candidate`) is OPTIONAL - the night gates against
   `local-sensitive`; approve it only when a dedicated candidate endpoint is
   wanted. Remember upsert re-defaults `is_active=True`: follow with
   `control.model_endpoint.retire` immediately (DIS-5).
3. **Schedule** (after one approved night reads well):
   `control.workflow.upsert` the definition in
   `libraries/workflows/sleep-distillation-craft.yaml` (register variant:
   change `adapter_kind`), then `control.workflow.schedule
   {workflow_id, cron: "0 4 * * 0", timezone: "Asia/Dubai"}` - from the
   owner's session; a schedule made by a service principal parks as
   `needs_action` and never runs.

## Watch out for

- The corpus is 100% `clean_run` - the weakest signal tier. HITL approvals
  and eval passes upgrade replay weight x3/x2 the moment they exist; the
  composition receipt on every build shows the mix drifting. **Authoring
  EvalCase rows is still the highest-leverage open work** - the craft lane
  cannot run at all without them.
- Two unused PATs (`distill-runbook`, `distill-runbook-2`) exist revoked-not:
  their secrets were never captured anywhere and they expire 2026-08-16;
  revoke from the console at leisure. `distill-runbook-3` is revoked.
- The register gate's entropy guard is STRICT (both `/loglik` and
  `/diversity` must answer): a sidecar outage holds the night rather than
  waiving DIS-9.

## Where everything is written down

- Ruling: `docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md`
- Plan + runbook: `docs/proposals/sleep-distillation.md`
- Next lane needing a ruling: `docs/proposals/notes-before-weights.md`
- Invariants: DIS-1..9 in `tests/invariants.yaml`
- Branch: `feat/sleep-distillation` (not pushed)
