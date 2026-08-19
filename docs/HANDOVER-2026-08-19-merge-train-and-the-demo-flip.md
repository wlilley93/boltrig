# Handover 2026-08-19: the merge train to zero, the demo flip, and the model path

Session: the boltrig pen-holder (beelink). Companion sessions: the opbox
pen-holder (`merge-build-deploy-opbox-demo`), which owns everything said here
about opbox's side. Everything below is measured unless marked otherwise.

## 1. The merge train reached zero and stayed there

`main` closed the day at `1c8d4f40` with **0 open PRs**. Landed today, in
order: #303, #304, #305, #302, #297 (morning); #307, #306, #308 (evening);
#309, #310; then #311, #312, #313 (dependabot, refreshed against current main
before merging - their greens were 3 hours and 5 merges stale), #314, #315.
All merge commits, none squashed. `salvage/pre-push-memory-guard` was deleted
only after sha256 byte-equivalence of all three guard files against main and
an archive-coverage count proving `archive/console-target` holds the rest.

**#314 raised the desktop-package CI ceiling 60 -> 120 minutes.** Four
cold-cache runs were killed at 60 today (the #306-#308 batch, #309 linux at
1h0m23s, #310 macos) while warm-cache reruns pass in 6-12 minutes. The next
cold run will finally measure its true duration instead of truncating at the
limit; revisit the number when it does.

**#309 restored the full 196-provider onboarding catalogue** (non-native
providers bind as OpenAI-compatible custom providers; a non-native id with no
published endpoint now REQUIRES a base URL instead of erroring). **#310 landed
ADR 0039 and the companion-runtime programme doc.** **#315 appended the
gate-self-service finding** (below) to the ADR.

## 2. The demo kernel-chat flip, and what its gate taught us

Step 1 (per-user provisioning) is DONE: 10 `user_invitations` accepted
17:37 UTC, 9 new users created, 10 per-user `opbox-chat` PATs minted on the
beelink kernel. Demo runs the kchat frontend image with `OPBOX_KERNEL_CHAT=1`
baked (opbox side, verified there).

**The finding (now in ADR 0039):** the ten HITL approvals were answered ~0.2s
after creation by the `opbox-demo-admin` PAT itself - subject Will, requests
in Will's own scope, `sole_author_exemption: true`. A human-approval gate plus
a standing identity-bearing credential is not a human-approval gate for any
holder of that credential, and `hitl_responses.respondent` records the person,
not the machine. Will ratified the batch afterwards (direct question, 20:05).
Retirement sequence adopted: (a) live per-user chat proof, (b) opbox re-points
register-time auto-provisioning + backfill off the standing PAT (register
route would otherwise silently 401 every NEW sign-up), (c) revoke
`opbox-demo-admin` by name with Will's explicit yes.

**The live proof has NOT landed.** Will's ~20:55 UTC demo chat produced
nothing kernel-side (store-wide: execution_root_runs 0, conversations 7,
work_items 92 - all unchanged since 16:53). Prime suspect is client bundle
caching (`NEXT_PUBLIC_USE_KERNEL_CHAT` is build-time inlined; his browser
likely held the pre-kchat bundle). Remedy: hard refresh, resend. The one-shot
confirmation script is staged beelink-side at the session scratchpad
(`confirm-live-proof.sh <timestamp>`), reads subject attribution by joining
`execution_root_runs.requested_by_user_id` to `users.email`.

## 3. The "hello spawned a subagent" bug: fingerprint found, discriminator designed

From the 16:53 pre-flip hello, already sitting in the store: conversation
`ae4a915a` (origin=user, Will) and **89ms later** work_items row `5aa98da7`
with `source='chat'`, `intent='hello'`, `depth=0`, `status='failed'`. A plain
greeting became a WorkItem. Two hypotheses, not yet discriminated:

- **H1**: every chat turn mints a work item (routing predicate fires on
  everything) - the bug as reported.
- **H2**: the degraded path - `model_endpoint_unavailable` parks the failed
  message as a work item, and with a working model none would appear.

Every hello ever observed (including Will's original sighting) ran against a
kernel with no working model, so all evidence to date fits both. The
discriminator is one hello against a working model, reading work_items.

## 4. The model path: fixed to one named missing link

Why no model has ever answered on the beelink stack (execution_root_runs = 0
EVER), measured link by link tonight:

- Kernel gateway env: SET (`http://bifrost:8080/v1`).
- Kernel default choice: `standard` -> `ollama/qwen3vl-abliterated:34ba10f8b5e0`
  (digest-pinned tag from before the M1 model was rebuilt; M1 now serves
  `:latest` at digest fc97729dc472).
- **FIXED tonight**: tag aliased on the M1 via `POST /api/copy`
  (`:latest` -> `:34ba10f8b5e0`, same digest). Bifrost then completed a chat
  round trip through the pinned tag: `"OK"` back from the M1 (measured).
- `allow_own_ai_keys: false` on this kernel - BYO keys are not the path; the
  kernel-configured default choice is.
- **THE ONE REMAINING LINK**: the kernel's catalogue check
  (`fleet/bifrost_model_catalogue.py`) requires each `GET /v1/models` row to
  carry `architecture.input_modalities` (OpenRouter-style schema) including
  `"text"`. The pinned bifrost returns bare `{id, name}` for provider-derived
  models, so the default choice reports `text_capability_not_advertised` and
  chat dies at endpoint resolution. This is structural for ollama-backed
  models on this kernel+bifrost pairing, not a config slip.

Candidate fixes, none started: teach bifrost's config to carry model metadata
(if the pinned build supports it); relax/enrich kernel-side (catalogue policy
could merge `endpoint.modalities`, which the store already holds, for
gateway-listed models); or a metadata-enriching shim (last resort, more glue
to rot). Whoever picks this up: the whole chain below the catalogue check is
proven live, so this one link is the difference between the demo answering
and not. It is also the gate on the H1/H2 discriminator above.

## 5. Also decided/queued today (not started, deliberately)

- **Agents surface**: Will, verbatim - "Agents surface will be the boltrig ui,
  where the logo and all ui says opbox agents (with the boltrig logo and logo
  text)." Recorded in ADR 0039; mechanism proposed (wordmark rides addon
  activation); sequenced after the four docking items.
- **ONE-AI-SURFACE** (opbox spec): boltrig owes a light-mode token export, the
  mark as a consumable asset, and one stable agent-plane URL.
- **Seam items 2-4** (ADR 0039): de-register the opbox kernel `/mcp` door +
  retire `opbox_key_`; re-probe the frontend door (~698 rows, not 633); cap by
  profile. Item 1 (health fix) merged as #306.
- **Tier-split runtime decision** (PROGRAM doc section 2) - Will's call.
