# Boltrig Worker

The task-oriented Boltrig web/Tauri client from decision 0021. Its presentation
is derived in part from OpenWorker commit
`f96ad4c8e6865f0aec519681a3717b6bcdd81546`; see the repository
`THIRD_PARTY_NOTICES.md`.

Worker talks only to the Boltrig HTTP/event surface through
`@wlilley93/boltrig-web-sdk`. It intentionally contains no OpenWorker Python
server, aisuite loop, provider client, model key, local permission engine,
connector secret store, memory store, or scheduler.

## Development

Build the SDK once, install the frozen Worker dependencies, then run:

```sh
cd sdks/web && pnpm install --frozen-lockfile && pnpm build
cd ../../apps/worker && pnpm install --frozen-lockfile
BOLTRIG_KERNEL_URL=http://localhost:8000 pnpm dev
```

`pnpm tauri dev` opens the same build in the desktop shell. Desktop development
requires the same canonical origin in both build environments so the webview
and native transport cannot point at different servers:

```sh
VITE_API_BASE=https://dev.boltrig.io \
BOLTRIG_DESKTOP_API_ORIGIN=https://dev.boltrig.io \
pnpm tauri dev
```

The Tauri pre-build gate refuses a missing, non-canonical, insecure, or
mismatched pair. Cargo also invalidates its native build whenever the native
origin changes; otherwise an older origin can remain embedded in an apparently
fresh frontend build. Account sign-in is the front door in both browser and
desktop. After authenticated startup, a new
desktop automatically bootstraps its revocable computer key; there is no code
or handoff bundle to copy. Device sessions live in the OS keychain and are
bound to the exact configured API origin. An unreadable key, or a key belonging
to a different/revoked account, requires explicit replacement. The device key
belongs only to the background/local-computer boundary: interactive browser and
desktop requests continue to use the httpOnly user-session cookie. Artifact
materialisation accepts only bytes already
downloaded through the authorized artifact endpoint and always asks the user
for a destination. Cancelling that dialog writes nothing and does not start a
browser download. The main webview has no direct dialog permission, so the
selected native path stays outside it. Follow-up open and reveal actions use a
bounded, process-local opaque handle rather than a caller-supplied path.

The Worker is the only first-party browser surface:

```sh
docker compose up -d ui
# Worker: http://localhost:8082/
```

Set `BOLTRIG_DESKTOP_DOWNLOAD_URL` to a reviewed HTTPS distribution page when
building the web image if authenticated users should see **Download Boltrig
Desktop**. An empty, invalid, credential-bearing, or HTTP value renders an
honest unavailable state and never becomes a link.

For live voice, configure one enabled `voice` channel in Channels, issue its
show-once channel-scoped gateway token from the channel detail, place it in the
gateway's read-only `CHANNEL_GATEWAY_TOKEN_FILE`, and start both profiles:

```sh
docker compose --profile channels up -d ui channel-gateway
```

The kernel elects one durable gateway owner per channel before returning any
resolved provider credential. Worker shows the safe gateway label and lease
expiry as ownership evidence, never as process liveness or provider
certification. A changed token file is loaded after authorization refusal;
environment-token rotation requires restart. Token-file mounting is
deployment-owned rather than a browser filesystem operation.

Channel creation and configuration use the kernel's caller-scoped target
catalogue for the initial/default target and each exact thread route. The
self-onboarding editor is fixed to the Member ceiling and only offers
departments visible in the current author scope. The synchronized advanced JSON
preserves unrelated legacy policy fields, but cannot bypass the same governed
backend validation.

Worker asks for microphone permission only after the kernel creates a call.
It sends PCM over `/voice/v1/calls/{id}/media`; the bearer is delivered in the
first WebSocket frame rather than the URL. The gateway redeems it once, refreshes
xAI's function list from a separate caller-scoped MCP token, and returns
synthesized PCM. Call metadata, transcripts and normalized lifecycle/tool
events are durable; microphone and synthesized audio are neither stored nor
logged. Browser microphone access requires localhost or HTTPS.

Browser Worker probes the existing authenticated settings route, supports first-party login, second-factor
challenge, first-time authenticator enrollment, invite acceptance and forced
password rotation. Its forgot/reset-password views use the non-enumerating,
single-use kernel recovery flow; delivery remains fail-closed until the
deployment injects a reviewed notifier. Session authority stays in the httpOnly
cookie. Enrollment secrets and one-time recovery codes are held only in component
memory for their one display; they are never persisted by Worker.

## Capability honesty

This beta implements the Worker shell, conversation SSE/replay and lifecycle,
all HITL response kinds, model-profile selection, structured tool/subagent
rendering, canonical artifact downloads, realtime browser voice with typed
unavailable fallback, and caller-scoped Home/Operate projections. Runs, work,
agent profiles, skills, capability bindings, model endpoints, workflows and
schedules, adapters/MCP, channels, evaluations, Knowledge, Memory, account,
sealed AI keys, organisation/workspace administration, audit, cost and budgets
all use canonical Boltrig routes. The detailed coverage and remaining gates live
in `docs/WORKER-PARITY.md`.

Worker can create and edit workflow DAG dependencies, parameters, versions and
intent tags through `control.workflow.upsert`, manage schedules, execute or
queue runs and inspect durable run history. It also manages authenticated
webhook and verified-channel trigger bindings, including enable/disable,
show-once webhook-secret rotation and delivery receipts. Approved secret-bearing
actions remain server-discoverable after navigation so Worker can explicitly
finalize them without persisting the bearer. It can generate an inert adapter,
inspect its source and request reviewed activation, but never treats generation
as certification. Adapter activate/deactivate/delete and integration revocation
now retain secret-free exact requester-owned inputs, invalidate stale intent and
replay only their original SDK method after approval; the backend remains
authoritative and the UI never infers completion from an Inbox decision. The
run inspection, configuration history and forensic diagnostics are part of the
Worker surface; unavailable capabilities are shown as such rather than handed
to a second client.

The kernel defines device enrollment completion, Ed25519 verifier bootstrap,
opaque root registration, canonical signed exact-action leases, atomic
single-use claiming, session rotation, revocation and bounded receipts. Worker
uses the owner routes for enrollment and opaque-root/device administration.
Its local-action panel polls an owner-scoped, authority-free lease projection
to recover durable terminal status and allowlisted receipt summaries after a
navigation or remount. Exact retry inputs, staged writes and recovered read bytes
stay in renderer memory only—never browser storage. A renderer reload therefore
loses a pending retry and JS-held read bytes; a native-process restart can also
lose not-yet-retrieved read bytes even though their durable receipt remains
visible.
File and command actions remain unavailable until the ordinary dispatcher
bindings and the Tauri device agent's pinned-verifier, polling, safe
root-relative I/O/argv execution and settlement acceptance are all green.
Command execution is still root-opt-in and every invocation must bind the exact
approved argv (or write content digest) plus `root_id + relative_path`.

The forty-entry integration catalogue remains non-connectable preview metadata
unless a tenant-authoritative row says a connector is certified and publishes a
supported auth contract. Clean boots now reconcile reviewed definitions for
Jira, Runpod and xAI Voice; connectability still requires that tenant's adapter
registration, activation and acceptable health. Canonical server rows always
override preview metadata.
Realtime voice has isolated, bounded concurrent call sessions and explicit
capacity refusal, but still needs credentialed xAI staging and Tauri acceptance
before it clears the production gate.
Codex-native collaboration remains admission-disabled for production. Its exact
pinned binary, stable-V1 wire namespace, lifetime/depth/thread and effort
ceilings, cancellation/tree-drain checks and durable descendant-event
projection are implemented, but a real model-backed spawn/cleanup acceptance,
bearer revocation, production cell-config protection and durable preflight
evidence still gate admission. Boltrig-owned fleet subagents are live and
rendered now. Worker shows unavailable, uncertified and degraded states and is
not the production root-route cutover while those gates remain.
