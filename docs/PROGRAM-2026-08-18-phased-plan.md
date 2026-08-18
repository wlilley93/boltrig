# Boltrig programme plan, phased, 2026-08-18

What this is: the twenty-one handovers in `docs/` and their companion closure
notes, read end to end and reorganised into one ordered programme. It replaces
nothing. Each handover remains the record of its own session; this document only
says **what order the open work goes in, and what has to be true before the next
phase starts.**

It is derived from a tree state measured on 2026-08-18, and the measurements are
named where they matter. Anything measured will drift, so re-measure before
acting on a number: the derivation is given each time so you can.

## How to read the phases

A phase is a set of work that shares one exit gate. Phases are ordered by
**dependency, not by importance**. Phase 6 carries some of the largest product
ideas in the estate and sits late because it needs a landed trunk under it.

Three things cut across every phase and are collected at the end rather than
scattered through it:

- **The owner-gated lane.** Work that no session can finish because it needs a
  credential, a payment, a human ear, or an authorisation. It runs in parallel
  with everything and blocks phase exits where it is named.
- **Standing hazards.** Traps that have already cost real time more than once.
- **Standing gates.** Things permanently closed by design, which are not tasks.

---

## Phase 0 - Get the merge queue moving

**Why first:** four feature branches sit on top of `main`, one of them 54 commits
deep, and every later phase either edits those files or has to merge past them.
The trunk is the constraint.

Measured 2026-08-18 (`git rev-list --count origin/main..origin/<branch>`, and
`gh pr checks`):

| Branch | PR | Ahead of main | CI |
| --- | --- | --- | --- |
| `feat/onboarding-polish` | #283 | 1 | green |
| `feat/real-brand-mark` | #284 | 54 | **red** on `worker-build` |
| `feat/jarvis-arc-reactor` | #285 | 2 | green |
| `fix/worker-structural-floor` | none | 55 | not run |
| `capability-doctrine-001` | none | 56 | not run |
| `feat/brand-mark-opbox-blue` | none | 55 | not run |
| `feat/console-target` | none | 51 | not run |

`feat/onboarding-polish` is an **ancestor** of `feat/real-brand-mark`, so #283 is
contained in #284. `feat/jarvis-arc-reactor` is independent of both.

### 0.1 Turn #284 green

`fix/worker-structural-floor` is exactly `feat/real-brand-mark` plus one commit,
and that commit is the fix for the failing job. Merge it in.

The failing job runs `make worker-quality`, which depends on `make
worker-structure`. Seven canvas and shader files from the two newer bodies sat
over the structural floor, plus a stale ChatView ratchet. They were brought
**under** the floor rather than registered as debt, because
`apps/worker/scripts/check-structure.mjs` refuses to emit an approval that would
self-approve new debt, and every prior commit touching
`docs/refactoring/worker-structural-debt.json` lowers a ratchet rather than
adding a file.

One item in that change deserves a second reader and did not get one: ChatView is
recorded at a measured 1334/1253/102, which is a **raise** on the branch's own
1331, admitted by the provenance check because it is still below main's 1337.
Raising a ratchet normally needs governance review. Read it before merging.

### 0.2 The visual receipt is not a CI blocker

Worth stating because two handovers imply otherwise. The visual-evidence receipt
is a **local** gate: `make visual-evidence` is declared in the `Makefile` and run
by `.githooks/pre-push`, and no CI workflow runs it. The recapture is a
discipline item, not a merge blocker.

It is still owed. Any edit under `apps/worker/src` invalidates a source-bound
receipt by design, and `apps/worker/tests/visual/README.md` is explicit that the
fix is to re-run the capture lanes after the UI has stopped changing, never to
rewrite a digest. **The recapture belongs on the merged tree, once.**

### 0.3 Land the three PRs

#283 is subsumed by #284. #285 is two commits and independent. Merge order is a
convenience question, not a correctness one.

### 0.4 Arm the pre-push hook

`core.hooksPath` is unset in the beelink clone and `.git/hooks/` holds only
samples. The repo ships `.githooks/pre-push`, whose own last line is the install
step nobody ran. The `Makefile` help text says "or just push - the pre-push hook
runs it", which in this clone is false in the way that reads as reassurance
rather than as a gap.

It is **deliberately still off**: the hook runs the visual-evidence gate, which
fails by design for anyone with edits under `apps/worker/src`, so switching it on
while other sessions are mid-feature blocks their pushes too. Set it when the
tree is quiet, and set it **relative** (`.githooks`), because an absolute path
makes every linked worktree run one tree's hooks.

### 0.5 The dependabot backlog

Fifteen open dependabot PRs, #267 to #289, the oldest from 2026-08-16. Several
are majors that will fail on their own diffs rather than on a stale base: openai
2 to 3, pylance 0.36 to 10, golang 1.27rc2, python 3.12 to 3.14. Triage in two
piles: the minor-patch groups, which should merge on a rebase, and the majors,
which each need their own decision. When taking a fix, upgrade the named package
only, never a blanket upgrade. A security fix whose diff is four hundred
unrelated bumps is one nobody reviews.

**Exit gate for Phase 0:** #283, #284 and #285 merged; `git log --oneline
--branches --not --remotes` reads 0; the visual receipt recaptured once on the
merged tree; the minor-patch dependabot group cleared.

---

## Phase 1 - One schema head, one capability doctrine

**Why here:** two long-lived branches have forked the migration chain, and one of
them contains a design that overlaps work planned elsewhere. Both problems get
worse with every commit. Neither can be deferred past Phase 2, which edits the
same credential resolution path.

### 1.1 The dual Alembic head

Measured 2026-08-18 by listing `migrations/versions/` on each remote branch. Both
branches leave `0076_typed_memory_ledger`, and both claim 0077 and 0078:

```text
feat/real-brand-mark       0076 -> 0077_trajectory
                                -> 0078_scoped_integration_connections

capability-doctrine-001    0076 -> 0077_audit_outbox
                                -> 0078_capability_presentation_fields
                                -> 0079_capability_routing_shard
                                -> 0080_probe_tool_count_bound
```

Merging them produces two heads and `alembic upgrade head` refuses.

**The earlier reasoning for who re-parents no longer holds on its stated
grounds.** `docs/HANDOVER-2026-08-18-per-user-integration-credentials.md` argued
that `capability-doctrine-001` should re-parent because it was local and
unpushed. It is now on origin, 56 commits ahead of main. The conclusion is
probably still right, since it has no PR where the other branch has #284 and is
one merge from landing, but it is now a judgement about landing order rather than
about which side is private, and the branch has grown from two migrations to
four.

Concretely: set `0077_audit_outbox`'s `down_revision` to
`0078_scoped_integration_connections`, renumber its four files, and update
`EXPECTED_ALEMBIC_HEAD` in `boltrig/api/readiness.py`. That constant is a strict
equality check, so a merge that leaves it naming the wrong revision makes
readiness report **unhealthy** rather than failing loudly.

`boltrig/store/schema.sql` was edited on both sides and will conflict textually.
`make migration-parity` is the check that the merged result is coherent: it
compares the Alembic head against `schema.sql` on a disposable Postgres and runs
in seconds.

### 1.2 Pick one capability doctrine

Two designs are solving the same problem from opposite ends and only one can
land:

- The plan recorded in this repository: pass the provider as a variable in the
  call input, and let the model see which adapters are loaded under a verb.
- `capability-doctrine-001`: a second binding table plus a router consulted when
  the invoked name is not a stored verb.

Scouting for the first turned up the obstacle both are aimed at.
`KernelRegistry._register_spec` in `boltrig/kernel/registry.py` is
last-write-wins for adapter-over-adapter and silently discards the losers, so
nothing records that several adapters claimed one verb.

**This is a genuine first-impression architectural fork and it goes to the court,
not to a session's preference.** The plan in this repository predates the branch.
Read the branch before doing any provider-selection work here.

### 1.3 The extraction that has to come first

`boltrig/kernel/credentials.py` sits at 399 of its 400-line ceiling. Whatever
Phase 1 or Phase 2 adds there has to be preceded by an extraction. Plan for it
rather than discovering it under a red gate.

**Exit gate for Phase 1:** one Alembic head; `make migration-parity` green on the
merged result; the capability doctrine decided on the record, and the losing
design's plan withdrawn rather than left to be rediscovered.

---

## Phase 2 - Finish per-user integration credentials

The feature landed on `feat/real-brand-mark`: an org has one shared connection
per integration, any member may connect their own, resolution runs own then org
then the environment binding, gated by an org flag that defaults off. With the
flag off a user row is skipped entirely, so revoking the policy is sufficient on
its own and turning it back on restores the personal credential with no row
surgery. The scope is sealed into the credential and compared on read.

It is a working feature that **the `member` role cannot reach**, plus three named
gaps. Each is its own path, not a hole widened in the existing one.

1. **A member-facing seam.** `member` is excluded from the author roles and
   denied `control.*` by the workspace ceiling in `boltrig/identity/rbac.py`, so
   the feature currently serves author roles only. A member-facing story needs a
   non-`control.*` self-service surface of its own. This is the largest of the
   four and the one that decides whether the feature is finished.
2. **Org-admin offboarding.** Revoke fails closed: only the owner may revoke a
   user-scoped connection, so when someone leaves, an admin cannot disconnect
   their personal credential.
3. **Per-connection health.** Health is per-adapter today, so a member whose own
   token was revoked upstream still reads "Connected" because the org's token
   keeps the adapter healthy. Per-connection health means probing with that
   specific credential.
4. **The workspace level, deliberately deferred.** A workspace row needs a live
   membership re-check at resolve time, and the connect path sets no workspace on
   the principal context. The level constraint means adding it later costs a
   migration. That is a recorded choice, not an oversight. Do not treat it as
   Phase 2 scope unless something forces it.

Two traps from that build are worth carrying forward because they generalise:

- **A backfill against a force-RLS table silently updates zero rows** during a
  migration, and a `SELECT count(*)` self-check cannot detect it, because it
  reads 0 for the same reason. Row security has to be switched off as the first
  statement of the upgrade.
- **The sealed-scope check tolerates a missing level deliberately.** Every
  credential sealed before the field existed sits inside an envelope no migration
  can reach, so a strict comparison would raise on every dispatch for every
  existing tenant. That is an outage, not a fence.

**Exit gate for Phase 2:** a member can connect their own credential through a
seam that is not `control.*`; an admin can offboard a departed member's
connection; health answers per connection.

---

## Phase 3 - Make the character bundle format real

`docs/SPEC-character-bundle.md` was written against a richly-specified private
character, and building the character who has *least* was the test of whether it
had smuggled in assumptions. It had. Four flaws are recorded and **must be
decided before any large asset consolidation happens against the format**;
consolidating first bakes the assumptions in.

1. **`prompts` cannot be required.** Neither shipped character has prompts. They
   are **bodies, not personas**. The missing axis is that a character has a body
   and *optionally* a voice or persona.
2. **`blurb` is required by the registry and absent from the spec's required
   list.** `sdks/web/src/characters.ts` throws on a missing or unsafe blurb, so a
   bundle carrying only the spec's required triple cannot be installed.
3. **"A character with only prompts and a fallback voice id is a valid character"
   is false in this registry.** A render function is mandatory, so a bundle with
   no visual has no body and cannot be staged. Either the registry gains a
   bodiless character that falls back to the default stage, or the spec stops
   claiming it.
4. **"Phenotype" is doing two jobs.** Split it: does this character *read* the
   host's measured affective state, which is a consumption declaration, versus
   does it *have* an appearance state of its own that travels.

Then two structural decisions:

- **Restate "a bundle ships configuration, never executable code" as "no
  host-privileged code".** A fragment shader is a program. The rule survives only
  because GLSL is a pure function of its uniforms inside a sandboxed pipeline
  with no filesystem, network or camera, but it can still hang a GPU. Read
  literally, the current wording makes shader characters illegal.
- **A character's inner life is code, not data.** The wandering mood baseline,
  the ambient gesture envelope, the aperture timing and the per-mode composition
  numbers all live in the renderer. The manifest can only *name* the model. **A
  second shader character cannot bring a different inner life as configuration
  today.** This is the largest remaining gap in the format, and it is a design
  task rather than a schema edit.

One constraint resolves a standing question by force: bundle assets live inside
`apps/worker/src`, because the Worker Dockerfile copies only the SDK source, the
Worker source and three token files. A repo-root bundle directory would simply
not exist in the shipped image.

Sequencing inside the phase: decide the four flaws, restate the code rule, design
the inner-life seam, express the remaining shipped character as a bundle, then
consolidate the private character's assets under one root and write her manifest.
**Both, not either:** the manifest is the contract, the root is what makes her
copyable without archaeology.

**Exit gate for Phase 3:** the schema matches the registry it must pass; two
shipped characters and one private character all load from bundles; a second
shader character could bring its own inner life with no core edit.

---

## Phase 4 - The service-ownership split

The load-bearing line of the whole companion architecture, and the largest single
piece of outstanding structural work:

| | owner |
| --- | --- |
| camerad, presence, observer, vigil | **Boltrig services** |
| STT, TTS, the voice runtime | **Boltrig services** |
| kernel, agents, tools, automations | **Boltrig** |
| camera observations, settings, enrolled face | **Boltrig kernel** |
| anchor images, LoRAs, clips, prompts, voice ids, declared keys | **the character** |
| phenotype and emotion state | **the character** |
| *when and how* the camera and automations are used | **the character** |

The test when something is ambiguous: **if installing a second character would
duplicate it, it is infrastructure.** Two companions do not each need a camera
daemon; they do each need their own face.

Today those four daemons run as one private character's launchd jobs. They become
first-class Boltrig services with UI toggles, and their observations and settings
persist to the kernel. Boltrig ships its own camerad: the user turns it on and
picks the device, and a character declares it *would like* the camera and is
refused honestly when it is off. Consent, retention and device choice are
questions about the user's hardware, so they cannot sit in a plugin someone might
install without reading.

Three items ride along:

- **The presence bridge is interim.** The unauthenticated exposure it was blocked
  behind is closed, and the bridge shipped as a pull over the cable. It is marked
  interim in its own document. Phase 4 is what replaces it.
- **A presence gate that runs off the sensor's box is spoofable**, and that is
  inherent rather than a bug in the transport: whoever controls the consuming box
  controls the verdict path. File it. It was identified and deliberately not
  filed because it was downstream of a decision that had not been taken yet. It
  has been taken.
- **Durability of the out-of-repo daemons.** A repoint that lives only in a
  working tree is one checkout away from silently reverting to a retired
  endpoint, and it was flagged as the single biggest durability risk of its
  session. Verify rather than assume it has since been committed. Three scheduled
  jobs also point at a model host that moved; repoint or disable them.

**Exit gate for Phase 4:** the four daemons run as Boltrig services with kernel
persistence and UI toggles; the interim presence pull is retired; nothing
load-bearing outside the repo is uncommitted.

---

## Phase 5 - Voice, from working to contracted

Speech is Boltrig infrastructure, not a companion's. A local voice stack runs
behind an OpenAI-shaped endpoint, so a self-hosted voice is one *route type*
among several rather than the architecture. That is settled. What is not:

1. **Client-side barge-in in the Worker.** An energy or VAD gate at 20 to 50 ms,
   not the streaming recogniser's speech-start signal, which was measured at
   1.746 s for speech beginning about 0.3 s in because it waits for a decoded
   token. Interrupt on energy and let the transcript follow.
2. **Route playback through the page's audio graph.** Echo cancellation in the
   webview can only cancel audio the webview itself played. A native playback
   path leaves the canceller with no reference and echo returns in full. This
   constrains the barge-in design and is not negotiable.
3. **Separate STT and TTS contracts.** The modality vocabulary already includes
   speech-to-text and text-to-speech, but representing a selection is not the
   same as running one. Voice route admission today is narrow on purpose:
   `boltrig/kernel/call_profiles.py` admits one provider family for realtime.
   **Do not broaden the Settings surface to advertise other voice providers until
   those verbs, route capabilities, quotas and receipts exist.** Speech-to-text
   and text-to-speech are opposite directions and must never be silently
   interchangeable.
4. **Re-measure the local TTS throughput.** It is quoted three ways across the
   estate, at 11.6x, 9.83x and 7.72x realtime, and no run has settled it. Three
   numbers for one property means nobody can plan capacity against any of them.

Two items in this phase are owner-gated and appear again below: the voice
container swap on the dev deployment, and one character's register audio.

**Exit gate for Phase 5:** barge-in interrupts on energy through the page's audio
graph; STT and TTS have executable contracts, and the Settings surface tells the
truth about which providers those contracts reach; one measured throughput
figure.

---

## Phase 6 - Workflow DAG and the Studio

The engine covers the compositional core: OR-join and skip lineages, multi-case
branching with fail-closed operators, per-step error strategies and retry, loop
item error modes and windowed parallelism, approval branch handles that route a
rejection or timeout instead of re-asking forever, and the draft lane split by
consequence. It is durable on the engine, governed at the one dispatch
chokepoint, and serving. Three of four live gates passed, including kill,
restart, approve and resume, which is exactly-once across a kill mid-run.

What remains is one human validation, one polish set, and one large design.

1. **The Studio session.** The only remaining human validation: author a workflow
   in the side panel, preview the diff, approve inline, run it, and watch the
   step events stream and the record land. Everything backing it is live; only a
   person can judge the loop. Owner-gated.
2. **Studio polish.** An inspector showing the registry-resolved contract (will
   it pause, adapter versus agent, grant check); a live-run overlay inside the
   Studio view; deleting the dead undo and redo plumbing left by the read-only
   pivot; a health receipt for the durable worker service.
3. **Child-run fan-out.** Design-first and large: iteration items as real engine
   child runs, presented like subagent runs in a chat transcript, so the
   orchestrator run reads as a chat in your own history. The design has to settle
   the child input shape, checkpoint coordination, approvals inside a child, and
   how item-error modes map. Build on the existing sub-run panel.
4. **The ultracode live gate** needs an agent runtime the bare test environment
   lacks. It belongs to that lane, not to the DAG.

**Exit gate for Phase 6:** the authoring loop validated by a person; polish
landed; the fan-out design recorded and approved before any of it is built.

---

## Phase 7 - Design authority and the remaining surfaces

Everything here is real, and none of it blocks the others.

- **The visual receipts are evidence, not sign-off.** The current metrics read
  `not_assessed`, six route reviews are unsigned with no authority, and the proof
  matrix records passing, failing and vacuous proof kinds without converting any
  of them into acceptance. The outstanding authority gap is not a UI regression:
  the frame ledger omits one screen's node at full depth. Obtain the authentic
  full-depth response if a parity claim is ever to be made, and **never fabricate
  a frame digest, a verdict or a sign-off.**
- **The design register carries records at `proposed`**, and removing the
  contrast floor needs a warrant rather than an edit.
- **Boltrig Mobile is 2 of 5 screens**, with one of the remaining three still
  falling through to the console surface at phone width. One further design in
  the same export is untouched.
- **There is no browser smoke test in the repo.** Retiring the old harness
  deleted the only one. It is recorded as OWED, not waived, in
  `docs/refactoring/order-binding-exemptions.json`, with an expiry earlier than
  the usual year end so it gets revisited. This is the cheapest large win in the
  phase: everything else here is judgement, and this is a gap.
- **The desktop app's single-pass shader path has never been run** on the host it
  exists for, though a parity test protects it.

**Exit gate for Phase 7:** a browser smoke test exists again; the mobile surface
is complete or explicitly descoped; any parity claim rests on an authentic frame
response, or no claim is made.

---

## Phase 8 - Production release

This phase is a checklist and its items are mostly independent. It is last
because every one of them binds a specific artifact, and the artifact keeps
changing until Phases 0 through 6 stop moving it.

**Desktop.** The installed development app is ad-hoc signed, which is why macOS
re-prompts for the keychain item on every rebuild. Automation must never type
that password. A distributable release needs the protected signing workflow,
Apple notarisation, the updater key and the configured HTTPS origins. Stable
signing is what removes the prompt churn; it is not a workaround.

**Credentials and seats.** Rotate the development mail credential. It was pasted
into a chat, so it is compromised by definition, and it must not be copied into
production. Replace the disposable second author seat with a real independent
administrator: governed deactivation correctly refuses to leave the tenant with
one author, and the answer is another person, not a bypass.

**Migrations.** Rehearse the whole unreleased chain in a disposable copy before
any deployment. Two facts make this sharper than it sounds: the kernel image does
**not** ship the migrations directory or its config, so an image that expects a
head cannot reach it, and a pinned-but-unapplied image in a compose override is a
loaded gun that fires on the next unrelated restart.

**Readiness.** `healthy` in a container listing does not mean the kernel is
serving. Only the readiness endpoint knows about the schema head, and a stack has
already served 503 for forty minutes while reporting healthy throughout.

**Deployment mechanics.** The static deploy procedure now verifies a pristine
candidate, copies only absent prior asset files into it with no-overwrite
semantics, records a compatibility-tree digest and swaps atomically. That shape
exists because an atomic swap removed a hashed chunk an already-open session then
requested, and the page painted nothing. Keep both halves: the additive retention
and the error boundary that reloads once per exact failure fingerprint. The full
procedure is in `docs/DEPLOYMENT.md`.

**Host hygiene.** A production host has already hit zero bytes free mid-roll.
This needs a standing answer, a scheduled image prune with an age filter plus a
disk alarm, not another manual sweep.

**Acceptance.** One disposable bring-your-own-provider onboarding, end to end,
confirming the gateway reports ready, the personal default survives a hard
refresh, and a runtime receipt names the exact model.

**Exit gate for Phase 8:** a signed, notarised desktop artifact; one rehearsed
migration path; the development credential rotated; two real administrators; a
standing disk job.

---

## The owner-gated lane

None of these can be closed by a session. They run in parallel, and they block
the phase exits where they are named.

| Item | Blocks | What is needed |
| --- | --- | --- |
| Voice-provider API credit | one character's register audio, Phase 5 | the provider answers 402 on every model including the free tier, with the key authenticating, so it is a billing state. All 48 lines are written and committed; with credit it is three commands, an audition and a clone. |
| The voice container swap on the dev deployment | Phase 5 | the replacement image is built and on the box with all four voices, ffmpeg and the chain; three of four voices 404 until it is swapped in. Authorisation to swap. |
| The Studio authoring session | Phase 6 exit | a person driving the loop and judging it. |
| The distillation approval | the distillation lane | one approval in the console. The requesting credential cannot approve itself, by design. |
| Judging a cloned voice by ear | the private character's voice | speaker similarity is the weakest metric of the chosen model while its accuracy is best in class, so the numbers point the opposite way to every question already settled. No further benchmarking resolves it. |
| Pushing, publishing and deploying | Phases 0 and 8 | outward-facing actions. |

---

## Standing hazards

These have each cost real time more than once. They are not phase work; they are
how to work.

**Several sessions share this repository.** At the time of writing there are
worktrees on at least four branches, with uncommitted work in two of them. A
worktree that is clean is not a worktree you own: one swept clean and an hour
later held 661 insertions of another session's staged work. Stage by explicit
path, never all-paths, and check immediately before writing rather than once at
the start. `git log --oneline --branches --not --remotes | wc -l` should read 0;
if it does not, someone's work exists on one disk only.

**A stash scoped by pathspec still carries the whole index**, so applying it
elsewhere brings the other session's staged changes with it.

**`/tmp` on the beelink is tmpfs, which means it is RAM.** A worktree registered
there held 72 MB of RAM on an 18 GB machine and would have vanished on reboot,
leaving a stale registration that still claims its branch and refuses a forced
branch move. Use `/var/tmp`.

**Two worker tests are flaky under a loaded box** and have each failed once and
passed once in the same tree. Neither is caused by the changes they appear under.
Do not read a single red run of either as a regression.

**Never test a published service from its own host.** It returns 000 and looks
broken. Test from a peer.

**A negative from a bare `which` over SSH is a fact about PATH, not about the
machine.** Three gaps were once declared from one such reading, and two of them
never existed.

**Check the artifact, not the endpoint.** Health endpoints return 200 from the
old tree too. Grep the served page for the hash the build just produced.

**A pointer that stores a fact will go stale silently.** `docs/HANDOVER.md` named
one document as current through sixteen later ones across eleven dates. It now
derives the list instead. Prefer derivation over storage for anything that
changes.

**A bounded search is a claim about where you looked, not a fact about the
corpus.** Search by the full identifier, never by the short form that appears
only in prose citing it.

---

## Standing gates, which are not tasks

**Hosted Codex production admission is closed, fail-closed, and cannot be opened
by this programme.** `docs/CODEX-PRODUCTION-ADMISSION.md` records seven blockers.
Five are implemented in a quarantined pre-thread receipt. Two are not available
at all in the pinned runtime version: it has no sufficient pre-thread method for
naming the effective provider, and it cannot self-attest the complete effective
schema surface. Those are upstream limits. Production readiness is `False` in
`boltrig/fleet/infrastructure/codex_agent_runtime.py` and in the runtime config,
and neither an environment variable nor a successful local probe overrides them.

This is a release gate on the server-side cells that serve browser chat. It is
not a statement that the kernel, the Worker or the desktop-local agent cannot
run.

**The distribution posture is an invariant, not a fixture choice.** The public
product ships two named characters and no browser-side provider secret. Directory
globbing for characters is banned, because a bundler glob emits every matched
private character as a production chunk even when registration sits behind a
branch. `apps/worker/src/characterPlugins.ts`, the Worker package manifest and
the top-level manifest are public graph and must not be edited to register a
private character.

**The structure ratchet is never raised.** When a renderer went over, the fix was
extraction on a real seam, and the ratchet then *required lowering*. Re-pin only
downward.

---

## Where the reasoning lives

This document is the order. The reasoning for each item is in the session that
found it, and those documents are the record. Read them for the why, not this
one. Sorted newest first:

```sh
ls docs/HANDOVER-*.md | sort -r
```

The creative and visual north star is separately maintained in
`docs/design/CREATIVE-HANDOVER.md`. The release-axis ledger is
`docs/PATH-TO-10.md`, and its counts are deliberately not repeated here, for the
same reason it stopped repeating its own.
