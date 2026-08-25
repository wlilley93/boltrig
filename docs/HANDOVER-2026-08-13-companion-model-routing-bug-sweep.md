# Handover — companion plugins, model routing, and the 2026-08-13 bug sweep

This handover closes the scoped Boltrig sweep requested as:

> Check the new plugin system, ensure the public build ships Familiar and
> Jarvis, ensure Settings work, and fix the bugs required for the system to
> behave as intended.

The scoped implementation is locally green. The public Worker ships exactly
**Familiar and Jarvis**. Model choices are server-resolved, tenant-scoped and
governed. Text, vision and realtime voice route selection is represented
without putting provider secrets in the browser. The current visual evidence
is bound to the final Worker source.

This is **not** a production-deployment receipt. No remote host, provider or
production database was mutated during this final sweep.

## Checkout state — read this before touching Git

- Repository: `/Users/williamlilley/Projects/boltrig`
- Branch: `feat/console-target`
- HEAD when this handover was written: `781346d1abd7`
- Relation to the last fetched `origin/main`: 42 commits ahead, 3 behind.
- The shared checkout is extremely dirty: before this handover was added it
  contained **288 modified tracked files and 247 untracked files**.

Those files include work from several sessions and scopes. Do not run a broad
`git add`, reset, clean, checkout, rebase, formatter or mechanical rewrite.
Resolve ownership file by file. This handover is deliberately uncommitted with
the rest of the current tree.

The HEAD commit itself is camera work:

```text
781346d camera: correct PTZ units to arc-seconds and stop trusting GET_LEN
```

The companion/model/settings work described here primarily lives in the dirty
working tree after that commit.

## Outcome

### Public companion set

The stock browser and desktop product registers only these two bodies:

| id | label | truth source |
| --- | --- | --- |
| `familiar` | Familiar | Its own private renderer state; it does not read the machine phenotype |
| `jarvis` | Jarvis | Measured machine phenotype, budgets and bounded turn activity |

The stock build does not glob companion directories. A bundler glob would emit
every matched private companion as a production chunk even if registration was
behind a development branch. Built-ins are registered explicitly in
`apps/worker/src/components/characters.ts`.

No Maya, personal companion, personal prompt, private diary, face data or other
character is part of the public product. The public-product gate enforces the
distribution posture:

```sh
make public-product-validate
```

Current result: `public-product: PASS (BYO Bifrost; Familiar + Jarvis only)`.

### Character plugin contract

The extension contract now lives in the framework-agnostic web SDK:

- `sdks/web/src/characters.ts`
- `sdks/web/tests/character-contracts.test.ts`

Important properties:

- ids follow one bounded grammar and are unique;
- display names are unique case-insensitively;
- labels and blurbs reject unsafe/control text;
- the validated registration object is copied and frozen, so an add-in cannot
  mutate the registry after admission;
- a broken subscriber cannot make a committed registration look as though it
  failed or prevent healthy subscribers from being notified;
- an uninstalled persisted character id falls back to the stock default rather
  than taking down the Stage;
- the SDK has no React dependency; the Worker binds the generic contract to a
  `ReactNode` renderer.

This is a real code extension seam, but it is not yet a runtime marketplace or
remote package installer. A private distribution may explicitly import an
add-in and call `registerCharacter`. The public Worker intentionally imports no
third companion.

### Stage and phenotype ownership

`apps/worker/src/components/chat/useStagePhenotype.ts` now makes phenotype
polling selection- and visibility-aware.

- Familiar does not cause an idle phenotype request.
- Jarvis requests phenotype only while selected and while a consuming Stage is
  active.
- Voice uses the same selected character contract as Chat. It no longer draws a
  hard-coded Familiar body when Jarvis is selected.

The focused regressions are in:

- `apps/worker/tests/useStagePhenotype.test.tsx`
- `apps/worker/tests/voiceCall.test.tsx`
- `apps/worker/tests/characters.test.ts`

## Models and Settings

### One Models section, modality views

Settings retains one coherent **Models** section rather than three sibling
navigation entries. Within it, the current implementation exposes modality
views for text, vision and voice:

- `apps/worker/src/components/settings/ModelSettingsSection.tsx`
- `apps/worker/src/components/settings/ModelSettingsPanels.tsx`
- `apps/worker/src/components/settings/modelSettingsTypes.ts`
- `apps/worker/src/components/settings/model-settings.css`

This avoids three independent inventories drifting apart. All views operate on
the same governed model-endpoint records and modality declarations.

### Secrets stay server-side

The Models editor does not accept Bifrost or voice-provider API keys. The
browser selects an opaque governed route; the kernel resolves the tenant record
and Bifrost owns provider credentials and topology.

There is a distinct **Account → Access** `AiKeyManagement` surface for the
older org/workspace/user provider-native credential hierarchy. Its password
input is intentionally uncontrolled, is cleared before the request is awaited,
and feeds a short-lived envelope-sealed proposal. The raw value is never
returned or audited. That surface is not wired to Bifrost administration and
must not be presented as Bifrost onboarding; all shipping cloud-agent lanes are
Codex routes, so a configured legacy key does not make an empty Bifrost
catalogue runnable.

For the supported route, “bring your own gateway” means configuring Bifrost's
server-side provider secret/admin surface and then authoring/selecting a
governed model route. Per-user Bifrost-provider onboarding remains a separate
security design: it needs tenant-bound provider-key lifecycle, virtual-key
binding, revocation and exact runtime admission rather than a browser-to-
provider call or a reuse of the legacy key form.

### Text and vision

Text and vision route authoring uses the server-owned Bifrost catalogue. The UI
uses exact model ids/names and does not invent availability.

For a single route selected for both text and vision, the chosen catalogue
model must advertise both modalities. It is not enough for it to appear in one
of the views. The client rejects a mismatched multimodal edit and the server
revalidates the governed route.

The canonical backend route validator is:

- `boltrig/config/capability_model_routes.py`

It handles both the legacy text/vision fields and the generic modality map,
rejects conflicts, resolves every selected endpoint in the caller's tenant,
requires active endpoints, and enforces the requested modality. The generic
map is authoritative; the legacy text/vision columns remain a compatibility
projection for existing readers.

### Per-agent model routes

Agent profiles now use a generic modality-to-endpoint map rather than growing a
new schema column for every modality. The UI is in:

- `apps/worker/src/components/agent/AgentModelRouting.tsx` (since removed: the routes a Hermes cell cannot serve were dropped)

The storage migration is:

- `migrations/versions/0073_agent_model_routes.py`

Approval context includes every selected endpoint. Changing a referenced
endpoint or its reference graph invalidates stale approval rather than applying
an operation against a different model graph than the reviewer saw.

The current modality vocabulary includes text, vision, STT, TTS and realtime.
That does not mean every modality has a complete runtime adapter. Text, vision
and realtime XAI voice are the paths closed in this sweep. STT/TTS selections
can be represented and preserved, but the public Models editor does not claim
Fish, ElevenLabs, Omnivoice or Whisper authoring/runtime support before those
kernel contracts exist.

### Voice

Voice route editing and call admission are deliberately narrow today:

- a route must be active;
- it must advertise the `realtime` modality;
- its provider family must be XAI (`xai`, `x.ai` or `grok`);
- endpoint/model ids are exact and immutable where required;
- call profile resolution is tenant-scoped and fails closed when an agent's
  selected route is unavailable.

The resolver is `boltrig/kernel/call_profiles.py`.

Do not broaden the UI to advertise Fish Audio, ElevenLabs, Omnivoice, local
Whisper or a generic “voice” toggle until STT and TTS have separate, executable
contracts. Speech-to-text and text-to-speech are opposite directions and must
not be silently interchangeable.

## Defects fixed in this sweep

1. **Mutable plugin registration** — callers could retain and alter an object
   after validation. The registry now stores a frozen copy.
2. **Subscriber failure ambiguity** — one listener exception could make
   registration throw after the change had committed and block other hosts.
   Listeners are isolated.
3. **Private-companion bundle leakage** — directory discovery could cause Vite
   to ship private bodies. The stock build explicitly registers only Familiar
   and Jarvis.
4. **Wrong Voice body** — Voice could show Familiar even when Jarvis was
   selected. It now renders through the common `StageBody` contract.
5. **Unnecessary phenotype traffic** — Familiar states could poll a source the
   character does not consume. Polling is now selected-character and
   visibility gated.
6. **Partial multimodal validation** — the editor could accept a model that
   supported only one selected modality. All selected modalities are checked.
7. **Generic/legacy route disagreement** — conflicting text or vision bindings
   now fail closed, while generic-only writes populate the compatibility view.
8. **Incomplete approval graph** — per-agent modality selections are included
   in exact approval context.
9. **PostgreSQL JSONB double encoding** — route maps were passed to asyncpg as
   JSON strings and could be stored as JSON strings instead of objects. The
   store now passes the dictionary to the configured JSON codec.
10. **Legacy PostgreSQL route references** — old double-encoded rows could be
    missed or misclassified. Exact values are decoded safely; malformed legacy
    strings do not create false references.
11. **False route references** — reference lookup now checks exact JSON object
    values rather than matching modality keys or substrings.
12. **Voice route overclaim** — a generic realtime-looking endpoint is no
    longer enough; the current call path admits only the executable XAI family.

## Verification recorded at closure

The final scoped tree produced:

- Worker: **81 files / 725 tests passed**;
- Worker typecheck: passed;
- Worker production build: passed;
- web SDK: **68 tests passed**, build/typecheck passed;
- Python with disposable real PostgreSQL: **3,770 passed, 160 skipped**;
- final PostgreSQL reference-query delta: focused real-Postgres regressions
  passed after that full run;
- invariants: **407/407**, 1,658 bound tests, debt 0;
- architecture: passed across 216 Python files;
- structure gate: passed;
- public-product gate: passed;
- VDS ledger gate: passed;
- visual manifest: **22/22 passed**;
- `git diff --check`: passed;
- scoped Ruff: passed.

Useful commands from the repository root:

```sh
pnpm --dir apps/worker test
pnpm --dir apps/worker typecheck
pnpm --dir apps/worker build
pnpm --dir sdks/web test
make test                       # starts disposable pgvector/PostgreSQL if needed
make invariants
make architecture
make structure
make public-product-validate
make vds-ledgers
git diff --check
```

Do not interpret skipped live-service tests as provider evidence. The full run
did not exercise credentialed Bifrost/XAI calls, live Hatchet, Cognee, or the
production Codex admission path.

## Visual evidence and authority

The final governed seven-state capture and the additive chat-direction capture
are bound to this Worker/visual source digest:

```text
abf7be9a1711d3423cd925604f32192b9c528eaa2e59477a22b7f036b80abf83
```

All eight screenshots were byte-identical to the previous current renders.
The current metrics remain `not_assessed`; the capture is evidence, not design
sign-off.

Key artifacts:

- `docs/design/evidence/2026-08-11-console-parity/current/`
- `docs/design/evidence/2026-08-11-chat-ui-direction/current/`
- `docs/design/evidence/2026-08-11-console-parity/README.md`

The fresh capture invalidated the prior proof matrix; the current matrix was
then rebuilt from a new 15-proof manual run and binds the current capture,
metrics and route manifest. The receipts remain `not_assessed`, the six reviews
remain unsigned `no_authority`, and there is still no sign-off or conformity
claim. The matrix records two passing, six failing and seven vacuous proof kinds
without converting any of those states into design acceptance.

The outstanding authority gap is not a UI regression: the depth-three Figma
frame ledger omits New chat / SCR-0007 (node `13:2`). No full-depth frame
response, sign-off, conformity verdict or new frame digest was fabricated.

Any edit under `apps/worker/src` or `apps/worker/tests/visual` invalidates the
current source-bound receipt. After the UI is stable, follow
`apps/worker/tests/visual/README.md`; do not hand-edit a digest.

## Current local development server

A Vite process was still listening when this handover was written:

```text
http://127.0.0.1:1420
PID 41028
node .../vite.js --host 127.0.0.1 --port 1420
```

Both `/` and the deterministic `chat-run` fixture returned HTTP 200. The
fixture URL is:

```text
http://127.0.0.1:1420/tests/visual/parity.html?state=chat-run&theme=dark#/chat/run-thread
```

This proves the local frontend server is serving. It does not prove a live
kernel, provider credential, authenticated production flow, or
`dev.boltrig.io`. No remote server was deployed in this closure.

## Deliberate limits and next work

1. **Live integration acceptance** — run credentialed, non-effectful Bifrost
   catalogue/text/vision tests and a bounded XAI realtime call in a controlled
   environment. Record cost and tear down credentials afterward.
2. **BYO credential onboarding** — design a kernel-owned credential flow if
   ordinary users must add keys without an operator. Never send raw keys to the
   Worker or persist them in model endpoints.
3. **STT and TTS contracts** — define separate verbs, route capabilities,
   quotas and receipts before enabling Fish/ElevenLabs/Omnivoice/Whisper in
   Settings.
4. **Runtime plugin lifecycle** — if install/uninstall without rebuilding is a
   product requirement, design a signed package/allowlist lifecycle. The
   current SDK contract is compile-time/import-time registration.
5. **Migration and release** — apply/rehearse migration `0073` with the rest of
   the unreleased migration chain in a disposable copy before any deployment.
6. **Production** — commit and review the owned changes, make the branch
   current with protected main, run the complete release gate on the exact
   commit, then produce signed/attested artifacts. Do not deploy this dirty
   checkout.
7. **Visual authority** — obtain the authentic full-depth Figma node response
   including `13:2` if an actual parity/sign-off claim is required.

## Safe continuation order

For the next session:

1. Read this file and `git status` before editing.
2. Identify which of the 535 pre-handover dirty paths belong to the change being
   continued; do not mass-stage them.
3. Run the focused test for the file being changed before a full gate.
4. If Worker source changes, leave VDS evidence alone until source stabilises,
   then recapture through the documented harness.
5. Treat Familiar/Jarvis-only and browser-secret absence as public-product
   invariants, not temporary fixture choices.
6. Keep unsupported voice providers visibly unavailable rather than inventing
   a successful configuration path.

The scoped plugin/settings/model-routing implementation is ready for review and
integration. Production readiness still depends on clean Git provenance,
release evidence, migrations and live external-service acceptance.
