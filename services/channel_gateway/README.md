# Boltrig channel gateway

The severed terminator for the **socket (persistent-connection)** channel class
(decision 0003, Phase 2): Slack Socket Mode, Telegram long-poll, Discord WS and
Signal, WhatsApp and the reference **generic** custom interface are shipped.
It is deliberately NOT part of the `boltrig` package: `boltrig/kernel` and
`boltrig/models` import nothing from here and it imports nothing from them
(SEC-28, machine-enforced). The only coupling is the wire protocol below.

## What it does

An async daemon supervising one platform adapter per configured channel:

1. **Inbound link** - an adapter hands each normalized platform message to the
   daemon, which POSTs it to the kernel's ONE intake route
   `POST /v1/channels/{channel_id}/inbound`, signed with the channel's
   connect-time secret under the same canonical-JSON HMAC scheme the webhook
   class uses (`x-boltrig-signature: t=<unix>,v1=<hex>`).
2. **Outbound link** - a pump claims the kernel's durable channel outbox
   (`POST /v1/channels/gateway/outbox/claim` with the
   `x-boltrig-mcp-token` run-scoped token header), delivers each message through
   the channel's adapter, then settles it with `.../ack` (terminal) or
   `.../fail` (kernel-side backoff retry, terminal `failed` at the attempt cap).

Adapters run under a lifecycle supervisor: a start failure or crash retries
with exponential backoff. With no static `CHANNEL_GATEWAY_CHANNELS` snapshot,
the daemon pulls its token-scoped desired state from
`GET /v1/channels/gateway/reconcile`, applies add/change/remove diffs, and posts
secret-free observations to `POST /v1/channels/gateway/heartbeat`. Reconcile
first atomically claims or renews a 45-second durable lease for each channel.
Only that owner receives resolved provider credentials or may heartbeat, claim
outbox rows, redeem call media, or append call state. A standby receives only
safe desired-state metadata and stops any adapter it no longer owns.
`GET /health` is liveness, `GET /ready` is token/adapter convergence, and
`GET /status` reports bounded observations (never secrets).

## Boundaries (decision 0003, binding conditions 2 + 7)

- **No policy, no grants, no credential authority.** The gateway can only
  (a) push signed intake and (b) pump its own outbox. It cannot invoke a verb.
- **Memory-only resolved channel credentials.** The run-scoped token
  arrives through exactly one configured token source. In canonical mode the
  kernel resolves Worker-authored secret-store references only after the
  authenticated gateway wins the durable channel lease; material stays in
  daemon memory and is never logged. `CHANNEL_GATEWAY_CHANNELS` remains a
  development/test compatibility fallback and is rejected in production.
  An author mints the show-once token in Worker (the underlying route is
  `POST /v1/channels/gateway/session`). It is TTL-bounded. A changed valid
  `CHANNEL_GATEWAY_TOKEN_FILE` is hot-loaded after a 401; an environment token
  requires restart.
- **One owner per channel.** Election is atomic in the kernel store and keyed by
  tenant plus channel. The lease owner is the private MCP token lease id, never
  a browser-visible bearer. Worker may show the safe gateway label and lease
  expiry, but that is bounded ownership evidence—not process liveness or
  provider certification.
- **Egress restricted** to the kernel intake + the platform endpoints, both in
  code (`egress.py`, allow-listed hosts) and at the container network layer
  (see the `Dockerfile` header and the compose entry).

## Configuration (env at spawn)

| Variable | Meaning |
| --- | --- |
| `BOLTRIG_KERNEL_URL` | kernel base URL (default `http://localhost:8000`) |
| `CHANNEL_GATEWAY_TOKEN` | restart-only run-scoped token; mutually exclusive with `CHANNEL_GATEWAY_TOKEN_FILE` |
| `CHANNEL_GATEWAY_TOKEN_FILE` | path to a read-only mounted token file; a changed valid value hot-loads after authorization refusal |
| `CHANNEL_GATEWAY_CHANNELS` | development/test-only static JSON compatibility; rejected in production |
| `CHANNEL_GATEWAY_EGRESS_ALLOW` | comma-separated allow-listed hosts (kernel + platforms) |
| `CHANNEL_GATEWAY_POLL_SECONDS` | idle outbox poll cadence (default `2`) |
| `CHANNEL_GATEWAY_RECONCILE_SECONDS` | desired-state pull/heartbeat cadence (default `10`) |
| `CHANNEL_GATEWAY_MAX_BROWSER_CALLS` | maximum simultaneous isolated browser voice sessions per gateway (default `8`, minimum `1`) |

Development-only static compatibility example (the reference generic adapter
on localhost):

```json
[{"channel_id": "ch_demo", "platform": "generic", "secret": "whsec_...",
  "config": {"listen_host": "127.0.0.1", "listen_port": 9090}}]
```

Canonical operation leaves `CHANNEL_GATEWAY_CHANNELS` empty. An admin authors
the channel in Worker using write-only reference names and mints a gateway
session for the explicit channel ids. Prefer placing that short-lived token in
a read-only mounted file. Token placement remains an operator/deployment
action: this implementation does not invent autonomous workload identity or a
second token-minting authority. The MCP token registry is currently local to
the kernel process, so a multi-replica deployment must keep gateway calls on
the API replica that minted the token (or run one API replica) until a reviewed
shared token registry or workload-identity contract is accepted. Signal and
WhatsApp device/account linking also remain external pairing actions; their
observed state is `needs_action` until the gateway can prove more than
adapter/process readiness.

## The generic custom interface (reference adapter)

Newline-delimited JSON over a localhost TCP listener:

- **inbound**: a peer writes `{"id": "m1", "sender": "U-1", "text": "hi"}\n`;
  the daemon signs and POSTs it to the kernel intake. `id` is the delivery id
  used for durable replay dedup; a message without one cannot be deduped.
- **outbound**: `deliver(payload)` writes
  `{"type": "outbound", "text": ..., "target": ...}` to every connected peer.
  With no connected peer, delivery fails and the kernel retries with backoff.

`clients/custom_surface.py` is a dependency-free (stdlib-only) reference
client for this seam - custom apps, the desktop familiar addon, or the
hey-nabu box can embed it or mimic it line for line. Note the listener binds
`listen_host` (`127.0.0.1` by default): an off-box surface needs
`listen_host: 0.0.0.0` plus network-level controls - the seam carries no
authentication of its own.

## Platform adapters

Every adapter below follows the reference Slack port (`slack_adapter.py`):
tokens arrive via `config` at spawn and are never logged, every dial is
egress-checked first, and inbound normalises to
`{"id", "sender", "text", "thread"}` where `thread` is a COMPLETE deliver
target (the kernel's reply route uses it verbatim as the outbound `target`).
Common config keys: `egress_allow` (default: `CHANNEL_GATEWAY_EGRESS_ALLOW`)
and `api_base`/`http_url` overrides for tests.

### Slack (`slack_adapter.py`) - reference port

- **Tokens**: `app_token` (xapp, Socket Mode) + `bot_token` (xoxb, postMessage).
- **Egress allow**: `slack.com`.
- **Boundary**: Socket-Mode-only - no HTTP interactions endpoint, so no v0
  request-signing surface; the authenticated WSS is the platform boundary.

### Telegram (`telegram_adapter.py`)

- **Token**: `bot_token` (Bot API, from BotFather).
- **Egress allow**: `api.telegram.org`.
- **Transport honesty**: Bot API long-poll (`getUpdates` with an offset
  cursor) - Telegram bots have no socket; the poll loop with reconnect/backoff
  is owned by the adapter exactly like the socket adapters' receive loops.
  `update_id` is the stable delivery id.
- **Thread shape**: `chat_id`, or `chat_id:message_thread_id` for forum-topic
  messages so replies land back in the topic.

### Discord (`discord_adapter.py`)

- **Token**: `bot_token` (bot must have the MESSAGE CONTENT privileged intent
  enabled in the developer portal; the adapter requests intents
  GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT).
- **Egress allow**: `discord.com`, `discord.gg` (suffix match covers
  `gateway.discord.gg` and regional resume hosts).
- **Boundary**: gateway-only - no HTTP interactions endpoint, so no Ed25519
  signature surface (same call as Slack Socket Mode; no pynacl dependency).
  Identify/heartbeat-with-seq/resume lifecycle lives inside the adapter.
- **Thread shape**: the channel id (Discord threads are channels).

### Signal (`signal_adapter.py`)

- **Config**: `http_url` (the signal-cli daemon; in compose
  `http://signal-cli:8080`) + `account` (the registered E.164 number,
  connect-time injected, never logged). The account KEYS never leave the
  signal-cli container.
- **Sibling service**: the compose `signal-cli` service
  (`bbernhard/signal-cli-rest-api`, json-rpc mode, profile `channels`) -
  register/link the account into its named volume first.
- **Egress allow**: `signal-cli` (the daemon host only).
- **Shape**: inbound envelopes over SSE (`/api/v1/events`), outbound via
  JSON-RPC `send` (`/api/v1/rpc`); the envelope timestamp is the delivery id.
- **Thread shape**: the sender's number for a DM, `group:<id>` for a group.

### Voice (`xai_voice_adapter.py`) - xAI Realtime speech-to-speech

- **Token**: `api_key` (an xAI console key, connect-time injected, never
  logged) plus the standard run-scoped kernel token for its tool path.
- **Egress allow**: `api.x.ai` (the one host it dials:
  `wss://api.x.ai/v1/realtime`).
- **Transport**: a held-open OpenAI-Realtime-compatible WSS with server VAD
  and barge-in; session bootstrap uses the nested `audio.input.format` schema
  (xAI silently ignores the legacy flat fields).
- **Tools are kernel-owned (SEC-183, fail-closed)**: `session.tools` is built
  ONLY from `tools/list` over the run-scoped MCP token (already grant-scoped
  kernel-side), every entry a client-side `type: "function"`; each function
  call is dispatched back through `POST /v1/mcp` `tools/call` - the unchanged
  chokepoint. A config that injects ANY tool list (above all xAI's
  server-side `web_search` / `x_search` / remote `mcp`, which execute outside
  the chokepoint) is REJECTED at adapter init.
- **Local audio seam**: no sound card is hardcoded. `config["audio"]` takes a
  `LocalAudio` implementation (`read_frame` / `write_frame` / `interrupt`);
  the default `NullAudio` makes it a transcript-only surface. For browser
  calls, `/v1/calls/{id}/media` accepts the one-time bearer in its first
  WebSocket frame and creates an isolated provider adapter plus bounded
  `BrowserAudio` bridge for that call; PCM remains in memory. A custom real
  device - or the hey-nabu box - can still inject its own audio implementation,
  but that configured physical-device channel is not a browser-media target.
- **Concurrent-call isolation**: provider dialogue, caller-scoped kernel-token
  view, tool map, pending HITL work, usage meter and PCM queues are all
  call-id keyed and never shared with the static channel or another browser
  caller. `CHANNEL_GATEWAY_MAX_BROWSER_CALLS` bounds the pool; overflow closes
  the new WebSocket with `4429` and never evicts an active call. `/status`
  reports only the active count and configured capacity.
- **Call authority**: the daemon-wide gateway token has no verb grants. Media
  redemption is tenant/channel bounded and returns a separate short-lived MCP
  token derived from the authenticated call owner's grant snapshot; the adapter
  refreshes `session.tools` from that token before the browser is marked ready.
- **Durability**: transcript, tool-name/result-status and lifecycle events are
  normalized into the kernel call store. Raw input/output PCM is never submitted
  to that route and the kernel event projection drops any non-allowlisted field.
- **Exact-call HITL**: every browser call has a server-minted run id. If
  `tools/call` returns `pending_human`, the adapter withholds the provider's
  `function_call_output` and emits the request id; the ordinary dispatcher has
  already sealed the canonical verb/params in its existing held-call record.
  Approval replays that seal exactly once through the dispatcher. A
  content-free outcome event lets the gateway resume the same in-memory
  provider call id. A gateway/provider disconnect does not prevent the approved
  action from resuming server-side, but there is then no old provider socket to
  narrate into; the durable call events remain the source of truth.
- **Usage and estimated cost**: the gateway records only PCM byte counts,
  provider-reported input/output token counts, and tool-call counts as
  normalized `usage` events. `GET /v1/calls/{id}/usage` returns a complete
  owner-scoped aggregate. Optional channel config keys
  `input_audio_micros_per_minute`, `output_audio_micros_per_minute`, and
  `tool_call_micros` produce an `estimated` micro-cost tagged by the required
  operational label `pricing_revision`; with zero/absent rates the cost is
  explicitly `unpriced`. This is observability, not a provider-invoice
  reconciliation or a hard voice-budget gate.
- **Shape**: a completed transcript becomes
  `{"id": <item_id>, "sender": <configured speaker>, "text", "thread"}`; the
  speaker is bound kernel-side to a Principal like any platform user.
  Outbound `channel.send` text is spoken back through the live session.

Credentialed xAI staging, invoice reconciliation, and hard per-call/daily
voice budget enforcement remain acceptance gaps. The fake-provider suite proves
tool/HITL correlation and metering arithmetic without claiming those live seams.

## Automation webhooks (machine sources: CI, monitoring)

A machine source - a CI pipeline, a monitoring alertmanager, a cron-adjacent
internal tool - does NOT come through this gateway (the gateway terminates the
socket class only). It registers as a **`webhook`-platform channel**, which the
kernel terminates in-process, and fires a workflow deterministically through
channel addressing. The whole path is the governed one: signature-verified
intake, kernel-authoritative identity, the one chokepoint.

1. **Register the channel** (admin) with the signing secret as a REFERENCE, so
   the DB never holds the material (SEC-04/05):

   ```bash
   curl -X POST $KERNEL/v1/channels -H "Authorization: Bearer $ADMIN" \
     -d '{"platform": "webhook", "name": "ci-deploy",
          "signing_secret_ref": "ci-deploy-hmac"}'
   # -> {"channel": "ch_...", "inbound_url": "/v1/channels/ch_.../inbound"}
   ```

   `signing_secret_ref` names an entry behind the kernel's SecretStore seam;
   ingress resolves it kernel-side at verify time.

2. **Bind the machine sender** (admin) so its platform id resolves to a
   governed principal - identity is the binding row, never the payload:

   ```bash
   curl -X POST $KERNEL/v1/channels/ch_.../bindings -H "Authorization: Bearer $ADMIN" \
     -d '{"external_user_id": "ci-bot", "subject": "ci-deploy-bot", "role": "member"}'
   ```

   Keep the role at `member`: automation operates but can never configure or
   administer (`control.*` is denied by the member grant ceiling).

3. **Map a route to a `workflow:` target** so a message pins the workflow it
   fires (SEC-178). The target is routing data, never authority - every step of
   the workflow is still chokepoint-checked against the bound sender's grants:

   ```bash
   curl -X PATCH $KERNEL/v1/channels/ch_... -H "Authorization: Bearer $ADMIN" \
     -d '{"config": {"sender_field": "sender",
          "addressing": {"routes": {"deploy-prod": "workflow:wf-deploy"}}}}'
   ```

   The source then POSTs `{"sender": "ci-bot", "chat": "deploy-prod",
   "text": "...", "id": "<stable delivery id>"}` to the inbound URL, signed
   under the same `x-boltrig-signature: t=<unix>,v1=<hex>` canonical-JSON HMAC
   scheme. The intake work item carries `target: "workflow:wf-deploy"`; the
   pump honors it before any chief-of-staff routing and triggers the workflow
   through the durable path (checkpointed, engine-owned task). An UNKNOWN
   workflow id fails closed: the item parks AWAITING_HUMAN with an escalation
   filed - it never falls through to inferred routing. A completion notice
   returns to the originating thread via the reply route (SEC-179).

**Cron is deliberately NOT a gateway/webhook source.** Scheduled automation is
internal in origin, so it never traverses an external-signature ingress at
all: the governed control verbs `POST /v1/workflows/{id}/schedule` and
`.../trigger` (admin-authored, approval-bound, audited) are the only way a
schedule is registered or a run fired. What a scheduled run SAYS still egresses
through the durable channel outbox like any other notification - the boundary
is about where authority enters, not where results leave.

## Run it

```bash
pip install --require-hashes -r requirements.txt
CHANNEL_GATEWAY_TOKEN_FILE=/run/secrets/boltrig-channel-gateway-token \
  uvicorn app:app --host 0.0.0.0 --port 8091
# or
docker build -t boltrig-channel-gateway . && docker run -p 8091:8091 boltrig-channel-gateway
```

`requirements.in` is the small direct-dependency source (identical pins to the
pi_sidecar); `requirements.txt` is the complete hash-locked graph generated
with CPython 3.12 - regenerate with the command at the top of that file.

## Porting a real platform

See `ADDING_A_PLATFORM.md`.

## WhatsApp (Baileys bridge)

WhatsApp is terminated by a sibling Node process (`whatsapp_bridge/`, derived
from the MIT-licensed Hermes bridge, Copyright (c) 2025 Nous Research - see
its `LICENSE.md`): the Baileys SDK is a Node library, so it runs in its own
image (condition 9) and the `whatsapp` adapter talks to it over loopback HTTP.
Neither side owns policy - the Hermes allowlist/self-chat logic was stripped;
who-may-talk is the kernel's binding rows.

Worker-authored channel provider config:

```json
[{"channel_id": "ch_wa", "platform": "whatsapp", "secret": "whsec_...",
  "config": {"bridge_base": "http://127.0.0.1:3000",
             "listen_host": "127.0.0.1", "listen_port": 3001}}]
```

- `bridge_base` - the bridge's base URL; the ONLY host the adapter dials
  (`POST /send`), so `CHANNEL_GATEWAY_EGRESS_ALLOW` needs just the kernel host
  + the bridge host (`127.0.0.1` co-located, `whatsapp-bridge` in compose).
- `listen_host`/`listen_port` - the adapter's inbound listener the bridge
  pushes to; point the bridge at it with `--adapter-url`/`ADAPTER_URL`
  (`http://127.0.0.1:3001/inbound` co-located; in compose set
  `listen_host: "0.0.0.0"` and `ADAPTER_URL=http://channel-gateway:3001/inbound`).
- Normalisation: Baileys message `key.id` is the delivery id (durable dedup),
  the JID user part (phone or LID number) is the binding `external_user_id`,
  and the chat JID is the reply thread - group messages carry the group JID.

Pairing (QR, one-off; creds persist in the bridge's `--session` dir - mount it
and treat it like a credential):

```bash
cd services/channel_gateway/whatsapp_bridge && npm ci
node bridge.js --pair-only --session /data   # scan the QR: WhatsApp > Linked devices
node bridge.js --port 3000 --session /data --adapter-url http://127.0.0.1:3001/inbound
```

Bridge env/args: `--port` (3000), `--host` (127.0.0.1; `0.0.0.0` only inside a
private container network), `--session` (creds dir), `--adapter-url` /
`ADAPTER_URL`, `--pair-only`, `WA_ACCEPTED_HOSTS` (extra Host-header aliases),
`WHATSAPP_DEBUG`, `WHATSAPP_SEND_TIMEOUT_MS`. Follow-ons: native media, edit,
typing indicators (captions already arrive as text).
