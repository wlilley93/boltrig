# SPEC-17: The channel gateway, messaging bridges and calls

    area              17 The channel gateway, messaging bridges and calls
    id-block          BT-REQ-1700 .. BT-REQ-1799
    referent commit   19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
    tree              /var/tmp/claude/claude-1011/-home-jellytot/f7f5f72e-a248-4744-a573-952de9fdf71f/scratchpad/bt-spec
    author-agent      brownfield-spec area 17
    date              2026-08-24

## Bound of this reading

Read in full, line by line:

- `services/channel_gateway/`: `app.py` (884), `adapters.py` (155), `egress.py` (77),
  `kernel_client.py` (223), `browser_audio.py` (137), `whatsapp_adapter.py` (229),
  `slack_adapter.py` (294), `xai_voice_adapter.py` (985), `README.md` (354),
  `ADDING_A_PLATFORM.md` (106), `Dockerfile`, `whatsapp_bridge/Dockerfile`.
- `boltrig/kernel/`: `channel_inbound_routes.py` (231), `channel_principal.py` (102),
  `channel_policy.py` (128), `channel_routes.py` (620), `channel_gateway_routes.py` (27),
  `channel_gateway_auth.py` (24), `channel_gateway_session_routes.py` (137),
  `channel_gateway_reconcile_routes.py` (179), `channel_gateway_specs.py` (138),
  `channel_gateway_outbox_routes.py` (151), `channel_notify.py` (167),
  `channel_addressing_runtime.py` (49), `channel_workflow_trigger_bridge.py` (42),
  `channel_pair_finalization.py` (74), `channel_inventory_routes.py` (204),
  `call_routes.py` (340), `call_gateway_routes.py` (283), `call_route_support.py` (153),
  `call_profiles.py` (82), `call_transcript.py` (49), `realtime_call_bridge.py` (87),
  `conversation_account_routes.py` (197), `conversation_live_routes.py` (237),
  `conversation_list_views.py` (49).
- Outside the owned tree, because half of every contract here lives there:
  `boltrig/adapters/builtin/inbound_webhook.py` (391),
  `boltrig/adapters/builtin/channel_send.py` (224), `boltrig/store/channel_outbox.py` (386),
  `boltrig/store/channel_dedup.py` (69), `boltrig/store/channel_gateway_state.py` (224),
  `boltrig/models/channel_providers.py` (237), `boltrig/config/control_channel_ops.py` (378),
  `boltrig/config/control_channel_approval.py` (169),
  `boltrig/config/channel_addressing.py` (288), `boltrig/work/channel_provenance.py` (146),
  `boltrig/models/channels.py`, `boltrig/models/realtime_calls.py`.

Sampled systematically, not read line by line: `telegram_adapter.py` (267),
`discord_adapter.py` (381) and `signal_adapter.py` (281) were read as module docstring
plus every top level definition, then in depth on the inbound normaliser, the
verification-boundary statement and `deliver`; `clients/custom_surface.py` (121) was
read to its class contract; `whatsapp_bridge/bridge.js` (371) was read at the Host
header guard, the `/send` handler and the listen block; `boltrig/kernel/mcp.py` was
read only at the run-token lifecycle; `boltrig/fleet/pump.py` and
`boltrig/fleet/authority.py` only at the workflow-target, terminal-notify and
ceiling-intersection sites; `boltrig/store/realtime_calls.py` only at
`claim_realtime_call_media` and `append_realtime_call_event`;
`boltrig/store/schema.sql` and `rls.sql` only at the channel/call tables.

NOT read, and therefore not claimed on: the Worker browser voice client
(`apps/worker/src/**`), the web SDK, the pinned dependency graphs
(`services/channel_gateway/requirements.txt`, `whatsapp_bridge/package-lock.json`),
and every test body (test NAMES are cited as evidence; their assertions were not
re-derived).

---

## 2. Purpose

This subsystem is Boltrig's one message edge. It terminates external messaging
channels in two transport classes, turns a verified external sender into a governed
Principal through kernel-owned binding rows, and hands the resulting message to the
same chokepoint every other caller uses. It also owns the outbound side of that edge
(a durable per-channel outbox pumped by a severed daemon) and the realtime voice call
surface built on the same channel machinery.

The ruling that governs it is explicit that the split is a process split and not an
authority split: [`docs/decisions/0003-channel-gateway-ruling.md:28`](../../../docs/decisions/0003-channel-gateway-ruling.md) `"The invariant is ONE DISPATCHER, not one process."`

## 3. Boundaries

**What the kernel side owns.** The `channel` noun and its governed lifecycle verbs;
the single signed intake route; principal resolution from binding rows; pairing and
self-onboarding; the opt-in chat allowlist and thread ceilings; addressing resolution;
the durable dedup markers; the durable outbox and its claim/ack/fail state machine;
the gateway session mint, the per-channel owner lease, desired-state reconciliation
and heartbeat; the realtime call store, media-token mint and gateway call links; and
the conversation read/queue/account routes.

**What the severed gateway owns.** Exactly one thing per adapter: the platform
connection. [`services/channel_gateway/adapters.py:4`](../../../services/channel_gateway/adapters.py) `"... - see ADDING_A_PLATFORM.md). An adapter"` and its
contract line: [`services/channel_gateway/adapters.py:5`](../../../services/channel_gateway/adapters.py) `"owns exactly one thing: the PLATFORM connection. It never sees policy, grants,"`

**Forbidden imports, and by what rule.** The gateway is deliberately outside the
`boltrig` package and imports nothing from it, machine-enforced as SEC-28:
[`services/channel_gateway/app.py:22`](../../../services/channel_gateway/app.py) `"SEVERED: this service is deliberately NOT part of the ``boltrig`` package and"`
The consequence is a deliberate duplication: the canonical-JSON HMAC is re-implemented
locally rather than imported,
[`services/channel_gateway/kernel_client.py:3`](../../../services/channel_gateway/kernel_client.py) `"A SEVERED client: this module must NOT import ``boltrig.*`` (SEC-28), so the"`
The reciprocal rule is that the messaging SDKs never enter the kernel image
([`docs/decisions/0003-channel-gateway-ruling.md:55`](../../../docs/decisions/0003-channel-gateway-ruling.md) `"do NOT import the messaging SDKs into the kernel image"`),
which is why WhatsApp's Baileys SDK runs as a third process
([`services/channel_gateway/README.md:318`](../../../services/channel_gateway/README.md) `"image (condition 9) and the `whatsapp` adapter talks to it over loopback HTTP."`).

**The seam between them is four HTTP contracts, not a library.**

| link | route | authenticated by |
| --- | --- | --- |
| inbound intake | `POST /v1/channels/{channel_id}/inbound` | the channel's signing secret, canonical-JSON HMAC |
| desired state | `GET /v1/channels/gateway/reconcile`, `POST /v1/channels/gateway/heartbeat` | `x-boltrig-mcp-token` run token plus the per-channel owner lease |
| outbox | `POST /v1/channels/gateway/outbox/claim`, `.../{id}/ack`, `.../{id}/fail` | the same run token plus the owner lease |
| calls | `POST /v1/calls/gateway/claim`, `.../{id}/events`, `.../{id}/state`, `GET .../{id}/hitl/{request_id}` | the same run token plus the owner lease on the call's channel |

The README states the daemon can only do two of these and cannot invoke a verb:
[`services/channel_gateway/README.md:40`](../../../services/channel_gateway/README.md) `"(a) push signed intake and (b) pump its own outbox. It cannot invoke a verb."`
That is true of the daemon-wide token, whose grant set is empty
([`boltrig/kernel/channel_gateway_session_routes.py:51`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"GrantSet(),"`),
and it is NOT true of the voice adapter during a browser call: after media redemption
the adapter holds a second, caller-scoped MCP token and calls `POST /v1/mcp`
`tools/call` with it ([`services/channel_gateway/xai_voice_adapter.py:761`](../../../services/channel_gateway/xai_voice_adapter.py) `"response = await self._kernel.mcp_call("`).
Authority still comes from the call owner's grant snapshot, not from the gateway, but
the sentence in the README is narrower than the shipped code.

## 4. Objects and contracts

### 4.1 Provider table (the one authority for platform shape)

[`boltrig/models/channel_providers.py:29`](../../../boltrig/models/channel_providers.py) `"CHANNEL_PROVIDERS: dict[str, ChannelProvider] = {"`

| id | transport | credential keys | provider config keys | activation |
| --- | --- | --- | --- | --- |
| `webhook` | webhook | `signing` | none | automatic |
| `msteams` | webhook | `signing` | none | automatic |
| `slack` | socket | `signing`, `app_token`, `bot_token` | none | automatic |
| `telegram` | socket | `signing`, `bot_token` | none | automatic |
| `discord` | socket | `signing`, `bot_token` | none | automatic |
| `signal` | socket | `signing` | `account` (required) | `external_pairing` |
| `whatsapp` | socket | `signing` | none | `external_pairing` |
| `generic` | socket | `signing` | none | `deployment_managed` |
| `voice` | socket | `signing`, `api_key` | `model`, `voice`, `instructions`, `speaker`, `thread`, pricing keys | automatic |

`msteams` is labelled honestly as a signed webhook, not a Graph connection:
[`boltrig/models/channel_providers.py:34`](../../../boltrig/models/channel_providers.py) `"\"msteams\", \"Teams-labelled signed webhook\", \"webhook\", (\"signing\",)"`
`transport` is derived from the platform, never authored:
[`boltrig/models/channel_providers.py:95`](../../../boltrig/models/channel_providers.py) `"def transport_for(platform: str) -> str:"`
An unknown platform id fails closed:
[`boltrig/models/channel_providers.py:88`](../../../boltrig/models/channel_providers.py) `Return a supported provider, failing closed for unknown platform ids.`

Browser-visible `config` is filtered at authoring time against a forbidden-fragment
list applied at any depth, which is what stops a JSON textarea smuggling a token or a
deployment URL into the DB row:
[`boltrig/models/channel_providers.py:80`](../../../boltrig/models/channel_providers.py) `"_FORBIDDEN_CONFIG_FRAGMENTS = ("`

### 4.2 `Channel`

[`boltrig/models/channels.py:34`](../../../boltrig/models/channels.py) `"class Channel:"`
Fields: `id`, `tenant_id`, `platform`, `name`, `transport`, `credential_ref`, `config`,
`unpaired_behavior` (`reject | ignore | pair`), `enabled`, `created_at`. The credential
is a reference only: [`boltrig/models/channels.py:42`](../../../boltrig/models/channels.py) `"# SEC-04: a reference into the secret store (webhook signing secret, bot token,"`

`config` is policy-as-data and carries, all optional: `sender_field`, `allowed_chats`,
`thread_ceilings`, `self_onboard`, `addressing` (`default_target`, `routes`,
`thread_field`, `chat_field`), `outbound_url`, and `provider` (the validated
provider-config subset).

### 4.3 `ChannelBinding`, `ChannelPairing`

[`boltrig/models/channels.py:103`](../../../boltrig/models/channels.py) `"class ChannelBinding:"` maps one verified
`external_user_id` to one internal `subject` at one `role`, per channel per tenant.
[`boltrig/models/channels.py:177`](../../../boltrig/models/channels.py) `"class ChannelPairing:"` is the one-time
code: `code_hash` (sha256, never plaintext), `subject`, `role`, `status`
(`pending | consumed | expired`), `attempts`, `expires_at`.

### 4.4 `ChannelOutboxMessage` and `ChannelDeliveryReceipt`

[`boltrig/models/channels.py:119`](../../../boltrig/models/channels.py) `"class ChannelOutboxMessage:"` carries
`payload` (`text`, `target`, and for notifications `event` and `subject`), `status`
(`pending | in_flight | delivered | failed`), `attempts`, `lease_owner`,
`lease_expires_at`, `next_attempt_at`, `last_error`.
The caller-facing projection strips payload and lease entirely:
[`boltrig/models/channels.py:146`](../../../boltrig/models/channels.py) `"class ChannelDeliveryReceipt:"` with the
public status vocabulary `queued | in_flight | retryable | delivered | terminal_failed`
([`boltrig/store/channel_outbox.py:30`](../../../boltrig/store/channel_outbox.py) `"def _public_status(status: str, attempts: int) -> str:"`).

### 4.5 `ChannelGatewayLease` and `ChannelGatewayStatus`

[`boltrig/models/channels.py:86`](../../../boltrig/models/channels.py) `"class ChannelGatewayLease:"` is the ownership
fence. Its `owner_lease_id` is the MCP run token's lease id and is never projected:
[`boltrig/models/channels.py:89`](../../../boltrig/models/channels.py) `"``owner_lease_id`` is the opaque id of the short-lived MCP run token. It is"`
[`boltrig/models/channels.py:72`](../../../boltrig/models/channels.py) `"class ChannelGatewayStatus:"` is the last
observation, one row per (tenant, channel), with `desired_revision`,
`observed_revision`, `status` and `reason_code`.

Observed states are a closed set:
[`boltrig/kernel/channel_gateway_specs.py:12`](../../../boltrig/kernel/channel_gateway_specs.py) `"OBSERVED_STATES = frozenset("`
(`pending`, `provisioning`, `ready`, `degraded`, `needs_action`, `stopping`, `stopped`).

### 4.6 `ChannelSpec` (gateway side)

[`services/channel_gateway/app.py:104`](../../../services/channel_gateway/app.py) `"class ChannelSpec:"` is what the daemon
holds in memory per channel: `channel_id`, `platform`, `secret`, `config`, `revision`,
`activation`. The secret is the connect-time HMAC secret and never leaves the HMAC.

### 4.7 `PlatformAdapter`

[`services/channel_gateway/adapters.py:40`](../../../services/channel_gateway/adapters.py) `"class PlatformAdapter:"` with three
members: `start(on_message)`, `stop()`, `deliver(payload)`. Registration is data, not
daemon logic: [`services/channel_gateway/adapters.py:62`](../../../services/channel_gateway/adapters.py) `"def register_adapter(cls: type[PlatformAdapter]) -> type[PlatformAdapter]:"`
Adding a platform therefore changes no daemon code; `app.py` imports each port module
purely so the class self-registers
([`services/channel_gateway/app.py:62`](../../../services/channel_gateway/app.py) `"# Platform ports register themselves on import (data, not daemon logic - see"`).

The normalised inbound shape every port must produce is `{"id", "sender", "text",
"thread"}`, where `thread` is a COMPLETE deliver target and not a fragment:
[`services/channel_gateway/ADDING_A_PLATFORM.md:56`](../../../services/channel_gateway/ADDING_A_PLATFORM.md) `"Telegram port): the kernel stamps it on the work item's `reply_route`, and"`

Per-platform thread grammar, as shipped:

| platform | delivery id | thread / deliver target |
| --- | --- | --- |
| slack | `payload.event_id` | `channel` or `channel:thread_ts` ([`services/channel_gateway/slack_adapter.py:236`](../../../services/channel_gateway/slack_adapter.py) `reply_target = f"{channel}:{thread_ts}" if thread_ts else channel`) |
| telegram | `update_id` | `chat_id` or `chat_id:message_thread_id` ([`services/channel_gateway/telegram_adapter.py:226`](../../../services/channel_gateway/telegram_adapter.py) `thread = f"{chat_id}:{topic_id}" if topic_id is not None else str(chat_id)`) |
| discord | message `id` | the channel id ([`services/channel_gateway/discord_adapter.py:312`](../../../services/channel_gateway/discord_adapter.py) `"thread": str(data["channel_id"]),`) |
| signal | envelope `timestamp` | sender number, or `group:<id>` ([`services/channel_gateway/signal_adapter.py:234`](../../../services/channel_gateway/signal_adapter.py) `thread = f"group:{group_id}" if group_id else str(sender)`) |
| whatsapp | Baileys `key.id` | the chat JID ([`services/channel_gateway/whatsapp_adapter.py:195`](../../../services/channel_gateway/whatsapp_adapter.py) `"thread": chat_id,`) |
| voice | provider `item_id` | the configured constant `thread` ([`services/channel_gateway/xai_voice_adapter.py:589`](../../../services/channel_gateway/xai_voice_adapter.py) `"thread": self._thread,`) |
| generic | caller-supplied `id` | absent unless the peer sends one |

### 4.8 `RealtimeCallSession` and `RealtimeCallEvent`

[`boltrig/models/realtime_calls.py:44`](../../../boltrig/models/realtime_calls.py) `"class RealtimeCallSession:"` with statuses
`creating | joining | active | reconnecting | held | ended | realtime_unavailable |
failed` ([`boltrig/models/realtime_calls.py:18`](../../../boltrig/models/realtime_calls.py) `"CALL_STATUSES: tuple[str, ...] = ("`).
`tool_context` is the server-authored grant snapshot used later to mint the caller's
MCP token and is never returned to a client
([`boltrig/models/realtime_calls.py:52`](../../../boltrig/models/realtime_calls.py) `"# Server-authored snapshot used only to mint the short-lived MCP token the"`).
`media_token_hash` holds only a digest
([`boltrig/models/realtime_calls.py:62`](../../../boltrig/models/realtime_calls.py) `"# Only a digest is persisted. The bearer is returned once to the browser."`).

Event types are a closed set of ten:
[`boltrig/models/realtime_calls.py:29`](../../../boltrig/models/realtime_calls.py) `"CALL_EVENT_TYPES: tuple[str, ...] = ("`

---

## 5. Control flow

### 5.1 Inbound: the one intake route

Both transport classes end at `POST /v1/channels/{channel_id}/inbound`
([`boltrig/kernel/channel_inbound_routes.py:224`](../../../boltrig/kernel/channel_inbound_routes.py) `"/v1/channels/{channel_id}/inbound",`).
The route takes NO principal dependency: it is authenticated by the channel's own
signature, and the tenant is discovered from the channel row.

1. **Resolve the channel by its unguessable id.**
   [`boltrig/kernel/channel_inbound_routes.py:33`](../../../boltrig/kernel/channel_inbound_routes.py) `"channel = await kernel.store.get_channel_by_id(channel_id)"`
   This is a deliberately cross-tenant read: the `channels` table is RLS-excluded
   ([`boltrig/store/channels.py:89`](../../../boltrig/store/channels.py) `"# cross-tenant inbound lookup by the unguessable id (channels is RLS-excluded)"`).
   **Failure branch:** unknown, disabled, or a transport outside `{webhook, socket}`
   returns 404 `unknown_channel`
   ([`boltrig/kernel/channel_inbound_routes.py:34`](../../../boltrig/kernel/channel_inbound_routes.py) `"if channel is None or not channel.enabled or channel.transport not in ("`).

2. **Resolve the signing secret.** The credential ref is read and resolved through the
   SecretStore seam. Two shapes are honoured: the current
   `channel_credentials_v1` bundle (`refs.signing`) and a legacy inline row
   ([`boltrig/kernel/channel_routes.py:74`](../../../boltrig/kernel/channel_routes.py) `"async def _channel_secret(kernel, ref: dict | None) -> str | None:"`).
   **Failure branch, and this is the load-bearing one for the ingest posture:** no
   resolvable secret returns 503 `channel_misconfigured` and the message is NOT
   ingested ([`boltrig/kernel/channel_inbound_routes.py:82`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"error": "channel_misconfigured"}, status_code=503)`).
   There is no unsigned intake path.

3. **Verify the signature over the right bytes.** The raw request body is taken from
   Starlette's cache and passed through
   ([`boltrig/kernel/channel_inbound_routes.py:89`](../../../boltrig/kernel/channel_inbound_routes.py) `"raw_body = await request.body()"`),
   then `verify_and_normalise` decides the scheme by header NAME:
   [`boltrig/adapters/builtin/inbound_webhook.py:277`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if header_name == _BOLTRIG_SIGNATURE_HEADER:"`
   - `x-boltrig-signature`: HMAC over `t + "." + canonical_json(payload)`. A signed
     request with no timestamp is refused outright
     ([`boltrig/adapters/builtin/inbound_webhook.py:283`](../../../boltrig/adapters/builtin/inbound_webhook.py) `raise WebhookAuthError("signed webhook is missing its timestamp (replay protection)")`).
   - `x-hub-signature-256`, `x-signature-256`, `x-signature`, `stripe-signature`:
     HMAC over the RAW wire bytes, with the timestamp bound in only when the platform
     supplied one ([`boltrig/adapters/builtin/inbound_webhook.py:300`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"signed = signed_content(ts, raw_body) if ts is not None else raw_body"`).
     Missing raw bytes fail closed
     ([`boltrig/adapters/builtin/inbound_webhook.py:294`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if raw_body is None:"`).
   The compare is constant time
   ([`boltrig/adapters/builtin/inbound_webhook.py:304`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if not hmac.compare_digest(signature_hex, expected):"`)
   and a bound timestamp outside the 300 second window is refused even when the
   signature is genuine
   ([`boltrig/adapters/builtin/inbound_webhook.py:310`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if replay_window_seconds > 0 and ts is not None:"`).
   **Failure branches:** `WebhookAuthError` gives 401 `signature`
   ([`boltrig/kernel/channel_inbound_routes.py:92`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"status": "denied", "reason": "signature"}, status_code=401)`);
   `WebhookValidationError` gives 400.

4. **Bind the tenant for RLS.** Only after verification.
   [`boltrig/kernel/channel_inbound_routes.py:41`](../../../boltrig/kernel/channel_inbound_routes.py) `"set_current_tenant(channel.tenant_id)"`

5. **Extract the sender from the configured field.**
   [`boltrig/kernel/channel_inbound_routes.py:42`](../../../boltrig/kernel/channel_inbound_routes.py) `sender = str(body.get(channel.config.get("sender_field", "sender")) or "").strip()`
   **Failure branch:** empty sender returns 400 `no sender`.

6. **Apply the opt-in chat allowlist.** Absent key preserves legacy behaviour; a
   present key switches the channel into allowlist mode and anything unrecognised
   fails closed ([`boltrig/kernel/channel_policy.py:37`](../../../boltrig/kernel/channel_policy.py) `if "allowed_chats" not in config:`).
   **Failure branch:** 403 `chat_not_allowed`
   ([`boltrig/kernel/channel_inbound_routes.py:49`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"status": "denied", "reason": "chat_not_allowed"}, status_code=403)`).

7. **Resolve the sender to a Principal.**
   [`boltrig/kernel/channel_principal.py:68`](../../../boltrig/kernel/channel_principal.py) `"binding = await store.get_channel_binding("`
   No binding returns `None`
   ([`boltrig/kernel/channel_principal.py:71`](../../../boltrig/kernel/channel_principal.py) `"if binding is None:"`).
   A binding whose recorded role is not one of `superadmin | admin | member` also
   returns `None` ([`boltrig/kernel/channel_principal.py:73`](../../../boltrig/kernel/channel_principal.py) `"role = binding.role if binding.role in CHANNEL_TIERS else DEFAULT_ROLE"`).
   The ceiling is the workspace-role ceiling for that tier and never the wildcard
   ([`boltrig/kernel/channel_principal.py:76`](../../../boltrig/kernel/channel_principal.py) `"ceiling = WORKSPACE_ROLE_CEILINGS[_TIER_CEILING_ROLE[role]]"`).
   When the bound subject has a user record that record is authoritative: a
   deactivated user kills the channel identity
   ([`boltrig/kernel/channel_principal.py:79`](../../../boltrig/kernel/channel_principal.py) `if user.status != "active":`)
   and an active user's current grants intersect the tier ceiling DOWN
   ([`boltrig/kernel/channel_principal.py:81`](../../../boltrig/kernel/channel_principal.py) `"grants = current_grants_for_user(user).intersect(ceiling)"`).
   A bare subject with no user record gets the tier ceiling alone
   ([`boltrig/kernel/channel_principal.py:86`](../../../boltrig/kernel/channel_principal.py) `"grants = ceiling"`).

8. **Unbound sender: pairing, then self-onboarding, then `unpaired_behavior`.**
   With `unpaired_behavior == "pair"` and a `pairing_code` in the body, the code is
   consumed ([`boltrig/kernel/channel_inbound_routes.py:101`](../../../boltrig/kernel/channel_inbound_routes.py) `if principal is None and channel.unpaired_behavior == "pair":`).
   Otherwise self-onboarding is attempted
   ([`boltrig/kernel/channel_inbound_routes.py:107`](../../../boltrig/kernel/channel_inbound_routes.py) `"principal = await _self_onboard(kernel, channel, sender)"`).
   **Failure branches:** `ignore` returns 200 `ignored`
   ([`boltrig/kernel/channel_inbound_routes.py:113`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"status": "ignored"})`);
   anything else returns 403 `sender not paired`
   ([`boltrig/kernel/channel_inbound_routes.py:115`](../../../boltrig/kernel/channel_inbound_routes.py) `"status": "denied", "reason": "sender not paired"},`);
   an onboarding rate-limit trip returns 429.

9. **Intake rate limit, two axes.** 120/minute per channel and 30/minute per
   (channel, sender), both enforced BEFORE any work item exists
   ([`boltrig/kernel/channel_routes.py:60`](../../../boltrig/kernel/channel_routes.py) `INBOUND_RL_PER_CHANNEL = RateLimit(per="minute", max=120, scope="verb")`).
   **Failure branch:** 429 with a `Retry-After` header when the limiter supplies one.
   Note the ORDER: this step runs AFTER principal resolution
   ([`boltrig/kernel/channel_inbound_routes.py:53`](../../../boltrig/kernel/channel_inbound_routes.py) `"throttled = await _enforce_intake_rate(kernel, channel, sender)"`),
   so a signed message from an unbound sender is refused without ever touching the
   intake counters. See RISKS.

10. **Durable replay dedup.**
    [`boltrig/kernel/channel_inbound_routes.py:57`](../../../boltrig/kernel/channel_inbound_routes.py) `"if delivery and await is_duplicate_delivery("`
    The delivery id is the payload's own id if present, else the signature hex, else a
    content hash ([`boltrig/adapters/builtin/inbound_webhook.py:377`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"delivery = external_id_str or signature_hex"`).
    The authority is the store row, atomic record-and-check
    ([`boltrig/store/channel_dedup.py:44`](../../../boltrig/store/channel_dedup.py) `"ON CONFLICT (tenant_id, channel_id, delivery_id) DO NOTHING"`),
    with the process-local set only a first-tier cache
    ([`boltrig/adapters/builtin/inbound_webhook.py:165`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"async def is_duplicate_delivery("`).
    **Failure branch:** a replay returns 200 `duplicate` and mints nothing.

11. **Resolve addressing and the reply route.**
    [`boltrig/kernel/channel_addressing_runtime.py:20`](../../../boltrig/kernel/channel_addressing_runtime.py) `"async def resolve_channel_addressing(kernel, channel, body: dict) -> tuple[str, dict]:"`
    Order: an explicit body `target` that passes the slug regex
    ([`boltrig/kernel/channel_addressing_runtime.py:34`](../../../boltrig/kernel/channel_addressing_runtime.py) `target = _clean_target(body.get("target"))`),
    then the channel's `addressing.routes[thread]`, then `addressing.default_target`,
    then the tenant's authored intake default, then `system:unassigned`
    ([`boltrig/kernel/channel_addressing_runtime.py:9`](../../../boltrig/kernel/channel_addressing_runtime.py) `UNASSIGNED_TARGET = "system:unassigned"`).
    The thread is read from `addressing.thread_field` first, else the fixed field list
    ([`boltrig/kernel/channel_addressing_runtime.py:10`](../../../boltrig/kernel/channel_addressing_runtime.py) `_TARGET_FIELDS = ("chat", "thread", "channel", "chat_id", "thread_id")`).

12. **Apply the opt-in thread ceiling to the live principal.**
    [`boltrig/kernel/channel_inbound_routes.py:161`](../../../boltrig/kernel/channel_inbound_routes.py) `"principal = replace(principal, grants=principal.grants.intersect(ceiling))"`
    Malformed ceiling data collapses to the empty grant set, never a wildcard
    ([`boltrig/kernel/channel_policy.py:70`](../../../boltrig/kernel/channel_policy.py) `"return GrantSet.of([])"`).

13. **Terminal branches before a work item is created.**
    [`boltrig/kernel/channel_workflow_trigger_bridge.py:8`](../../../boltrig/kernel/channel_workflow_trigger_bridge.py) `"async def bound_event_response("`
    runs, in order: (a) the channel-native HITL reply, (b) channel-bound workflow
    trigger delivery. Either short-circuits intake.
    - HITL: `/approve <id>`, `/deny <id>`, `/answer <id> <text>` parse explicitly
      ([`boltrig/kernel/channel_routes.py:117`](../../../boltrig/kernel/channel_routes.py) `"def _parse_hitl_command(text: str) -> tuple[str, str, str] | None:"`);
      a plain reply answers only when EXACTLY ONE pending request addressed to that
      subject exists in that thread AND it is a QUESTION
      ([`boltrig/kernel/channel_routes.py:192`](../../../boltrig/kernel/channel_routes.py) `"if req is None or req.type != HITLType.QUESTION:"`).
      A SECURE question is refused with 403
      ([`boltrig/kernel/channel_routes.py:208`](../../../boltrig/kernel/channel_routes.py) `"status": "denied", "reason": "secure questions use secure input"},`).
      Authorisation is the SAME `hitl_http` path the API uses, so a non-approver gets
      the same denial. A socket-class channel also gets an outbox confirmation
      ([`boltrig/kernel/channel_routes.py:237`](../../../boltrig/kernel/channel_routes.py) `if ch.transport == "socket":`).
    - Workflow triggers: every enabled `source='channel'` trigger for this channel is
      delivered under the sender's principal, capped at 32 triggers and a 256 KiB event
      ([`boltrig/kernel/workflow_trigger_delivery.py:271`](../../../boltrig/kernel/workflow_trigger_delivery.py) `"triggers = await kernel.store.list_channel_workflow_triggers("`).

14. **Mint the governed work item.**
    `normalise(body, source=channel.platform, tenant_id=channel.tenant_id)`, then
    `on_behalf_of`, `target`, `reply_route`, provenance, the creator ceiling and the
    thread ceiling are stamped
    ([`boltrig/kernel/channel_inbound_routes.py:189`](../../../boltrig/kernel/channel_inbound_routes.py) `"stamp_creator_ceiling(item, principal.grants)"`),
    the item is persisted
    ([`boltrig/kernel/channel_inbound_routes.py:191`](../../../boltrig/kernel/channel_inbound_routes.py) `"await kernel.store.create_work_item(item)"`),
    an audit row is written under verb `channel.inbound`, and the route answers 202
    with the work item id
    ([`boltrig/kernel/channel_inbound_routes.py:193`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"status": "ok", "work_item": item.id}, status_code=202)`).

15. **Provenance is kernel-authored and overwrites any caller value.**
    [`boltrig/work/channel_provenance.py:64`](../../../boltrig/work/channel_provenance.py) `"item.constraints.pop(CHANNEL_MESSAGE_PROVENANCE_KEY, None)"`
    The public projection drops every raw provider identifier
    ([`boltrig/work/channel_provenance.py:95`](../../../boltrig/work/channel_provenance.py) `"def public_channel_provenance(item: WorkItem) -> dict[str, Any] | None:"`)
    and the prompt fragment is wrapped as untrusted
    ([`boltrig/work/channel_provenance.py:134`](../../../boltrig/work/channel_provenance.py) `"return wrap_untrusted("`).

16. **Execution re-applies the ceilings.** The pump intersects both the thread ceiling
    and the creator ceiling again at context construction, so a later edit of the work
    item cannot widen authority
    ([`boltrig/fleet/authority.py:107`](../../../boltrig/fleet/authority.py) `"for ceiling in (ceiling_from_item(item), creator_ceiling_from_item(item)):"`).
    A `workflow:<id>` target is honoured before any routing, and an unknown workflow
    parks AWAITING_HUMAN rather than falling through
    ([`boltrig/fleet/pump.py:354`](../../../boltrig/fleet/pump.py) `"Honor a"`).

### 5.2 Inbound: the socket class reaches the same route

The gateway adapter hands a normalised dict to the daemon, which builds the intake
body, adds `message_provenance` as signed transport data, and POSTs it signed
([`services/channel_gateway/app.py:246`](../../../services/channel_gateway/app.py) `"async def _on_message(self, spec: ChannelSpec, message: dict[str, Any]) -> None:"`).
The signature is the same Stripe-style header, computed locally
([`services/channel_gateway/kernel_client.py:38`](../../../services/channel_gateway/kernel_client.py) `"def signature_header(secret: str, payload: dict[str, Any], *, ts: int | None = None) -> str:"`).
**Failure branches:** a transport failure logs and DROPS the message
([`services/channel_gateway/app.py:273`](../../../services/channel_gateway/app.py) `log.warning("intake POST failed for channel %s (%s)", spec.channel_id, exc)`);
a >=400 answer logs the status only, never the body or the secret.

### 5.3 Pairing and self-onboarding

**Pairing.** An admin mints a one-time code through the governed control verb
([`boltrig/kernel/channel_routes.py:496`](../../../boltrig/kernel/channel_routes.py) `"# HITL-gated by being admin-only: an admin author issuing the code IS the"`).
The code is `secrets.token_urlsafe(6)[:8].upper()`
([`boltrig/config/control_channel_ops.py:251`](../../../boltrig/config/control_channel_ops.py) `"return secrets.token_urlsafe(6)[:8].upper()"`),
stored only as sha256
([`boltrig/config/control_channel_ops.py:279`](../../../boltrig/config/control_channel_ops.py) `code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),`),
TTL clamped to 1..60 minutes, and returned exactly once
([`boltrig/kernel/channel_routes.py:532`](../../../boltrig/kernel/channel_routes.py) `"status_code=201)  # code returned ONCE, never again"`).
A principal may not mint a binding above its own rank
([`boltrig/kernel/channel_routes.py:381`](../../../boltrig/kernel/channel_routes.py) `"status": "denied", "reason": "cannot bind a role ranked above your own"},`).
Consumption enforces expiry, a constant-time compare, an attempts cap of 5 that flips
the row to expired, and a single-use CAS
([`boltrig/kernel/channel_routes.py:343`](../../../boltrig/kernel/channel_routes.py) `"if not await kernel.store.consume_channel_pairing(channel.tenant_id, pairing.id):"`).
A pending code can be re-discovered by its own requester, but the CODE is never
re-shown ([`boltrig/kernel/channel_pair_finalization.py:56`](../../../boltrig/kernel/channel_pair_finalization.py) `"async def discover_pair_finalizations("`).

**Self-onboarding.** Opt-in per channel, member role only
([`boltrig/kernel/channel_routes.py:281`](../../../boltrig/kernel/channel_routes.py) `"if role not in SELF_ONBOARD_ROLES:"`),
never over an existing binding
([`boltrig/kernel/channel_routes.py:286`](../../../boltrig/kernel/channel_routes.py) `"# A binding EXISTS but resolved to no principal (an unknown tier, or a"`),
rate-limited at 5/minute per channel before anything is minted
([`boltrig/kernel/channel_routes.py:66`](../../../boltrig/kernel/channel_routes.py) `ONBOARD_RL_PER_CHANNEL = RateLimit(per="minute", max=5, scope="verb")`),
and it binds a synthetic subject with no user record
([`boltrig/kernel/channel_principal.py:31`](../../../boltrig/kernel/channel_principal.py) `"def self_onboard_subject(platform: str, external_user_id: str) -> str:"`).

### 5.4 Outbound: channel.send to platform

1. `channel.send` is an ordinary verb through the chokepoint, `consequence="high"`
   ([`boltrig/adapters/builtin/channel_send.py:190`](../../../boltrig/adapters/builtin/channel_send.py) `consequence="high",  # outbound: HITL by default (SEC-39)`),
   rate-limited 60/minute per tenant.
2. The approver-only `comment` param is stripped before the deliver seam
   ([`boltrig/adapters/builtin/channel_send.py:209`](../../../boltrig/adapters/builtin/channel_send.py) `delivery = await self._deliver(ch, params["text"], params.get("target"))`).
3. Delivery branches, in this order:
   - a dev-mode diversion posts to the stack's own loopback intake and reports
     `diverted`, never `sent`
     ([`boltrig/adapters/builtin/channel_send.py:66`](../../../boltrig/adapters/builtin/channel_send.py) `"if diversion is not None:"`);
   - a configured `outbound_url` gets an IP-pinned POST under the manifest
     NetworkConfig ([`boltrig/adapters/builtin/channel_send.py:91`](../../../boltrig/adapters/builtin/channel_send.py) `outbound_url = (channel.config or {}).get("outbound_url")`);
   - a socket channel enqueues one durable outbox row
     ([`boltrig/adapters/builtin/channel_send.py:108`](../../../boltrig/adapters/builtin/channel_send.py) `if channel.transport == "socket":`);
   - anything else returns `queued` with no consumer at all
     ([`boltrig/adapters/builtin/channel_send.py:119`](../../../boltrig/adapters/builtin/channel_send.py) `return {"status": "queued", "transport": channel.transport}`).
   **Failure branch:** an egress refusal or transport error becomes an INVALID adapter
   failure, so the verb fails rather than silently dropping.
4. The gateway pump claims a batch (limit clamped 1..50, lease clamped 1..300 s)
   ([`boltrig/kernel/channel_gateway_outbox_routes.py:11`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"MAX_CLAIM_BATCH = 50"`),
   restricted to channels this token owns
   ([`boltrig/kernel/channel_gateway_outbox_routes.py:39`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"active_channels = await _owned_channels(kernel, token, lease)"`).
   The claim is an atomic pending -> in_flight batch with `FOR UPDATE SKIP LOCKED`,
   oldest first, `attempts` incremented per claim
   ([`boltrig/store/channel_outbox.py:220`](../../../boltrig/store/channel_outbox.py) `"ORDER BY created_at LIMIT $5 FOR UPDATE SKIP LOCKED"`).
5. The daemon delivers through the channel's adapter and settles
   ([`services/channel_gateway/app.py:630`](../../../services/channel_gateway/app.py) `"async def _settle(self, message: dict[str, Any]) -> None:"`).
   **Failure branch:** no live adapter for the channel is itself a delivery failure
   ([`services/channel_gateway/app.py:634`](../../../services/channel_gateway/app.py) `raise KernelLinkError("no live adapter for this channel")`).
6. Ack and fail are compare-and-swapped on the lease owner
   ([`boltrig/store/channel_outbox.py:234`](../../../boltrig/store/channel_outbox.py) `AND lease_owner=$3 RETURNING id`),
   returning 409 `not_claimed` to a stale claimer. A fail under the cap re-queues
   behind `backoff_seconds * min(2^(attempts-1), 64)`; at 8 attempts the row is
   terminally `failed`
   ([`boltrig/store/channel_outbox.py:247`](../../../boltrig/store/channel_outbox.py) `"SET status = CASE WHEN attempts >= $5 THEN 'failed' ELSE 'pending' END,"`).
   **Failure branch on the daemon side:** an ack that fails in transit is simply logged;
   the lease lapses and the row is redelivered, so the contract is at-least-once
   ([`services/channel_gateway/app.py:646`](../../../services/channel_gateway/app.py) `"# the lease will lapse and a later claim redelivers (at-least-once)"`).
7. A terminal `failed` row can be requeued only by an author, only through the
   approval-bound control verb, and only against an exact `updated_at` snapshot
   ([`boltrig/store/channel_outbox.py:179`](../../../boltrig/store/channel_outbox.py) `"SET status='pending', attempts=0, next_attempt_at=NULL,"`).

### 5.5 The notification round trip

`notify_work_item_result` is called by the pump at every terminal state
([`boltrig/fleet/pump.py:649`](../../../boltrig/fleet/pump.py) `"await notify_work_item_result(self._store, item)"`),
and is a no-op without a human origin or a reply route
([`boltrig/kernel/channel_notify.py:161`](../../../boltrig/kernel/channel_notify.py) `if not getattr(item, "on_behalf_of", None) or not getattr(item, "reply_route", None):`).
Delivery is doubly gated: a `notification_prefs` row must match the event
([`boltrig/kernel/channel_notify.py:87`](../../../boltrig/kernel/channel_notify.py) `"if event_type not in NOTIFICATION_EVENT_IDS:"`),
the channel must be enabled and socket class
([`boltrig/kernel/channel_notify.py:101`](../../../boltrig/kernel/channel_notify.py) `if not ch.enabled or not route_matches or ch.transport != "socket":`),
and the recipient must have a binding on it
([`boltrig/kernel/channel_notify.py:108`](../../../boltrig/kernel/channel_notify.py) `"binding = next((b for b in bindings if b.subject == member), None)"`).
When the notification concerns the originating channel it is addressed back to the
originating thread ([`boltrig/kernel/channel_notify.py:113`](../../../boltrig/kernel/channel_notify.py) `target = source_route.get("thread")  # reply in the origin thread`).
A team-scoped pref names a department and fans out to every ACTIVE member
([`boltrig/kernel/channel_notify.py:66`](../../../boltrig/kernel/channel_notify.py) `if user.status == "active" and pref.scope_ref in departments:`).
An unreachable user is an honest delivery gap, not an error.

### 5.6 Gateway bring-up, ownership and reconciliation

1. **Mint a session.** An author POSTs `/v1/channels/gateway/session` with an explicit
   channel id list. Every id must be an enabled socket channel
   ([`boltrig/kernel/channel_gateway_session_routes.py:94`](../../../boltrig/kernel/channel_gateway_session_routes.py) `if channel is None or not channel.enabled or channel.transport != "socket":`).
   The token carries an EMPTY grant set and the marker `channel_gateway: True`
   ([`boltrig/kernel/channel_gateway_session_routes.py:51`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"GrantSet(),"`),
   is show-once, and declares that no provider credentials ride the response
   ([`boltrig/kernel/channel_gateway_session_routes.py:84`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"provider_credentials_included": False,`).
   **Failure branches:** non-author 403; empty channel list 400; a bad `gateway_id`
   400; any TTL or token-layer error collapses to a fixed reason so an internal
   argument name cannot leak
   ([`boltrig/kernel/channel_gateway_session_routes.py:67`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"return JSONResponse("`).
2. **Authenticate every gateway link.** One header, one registry, one marker check,
   then the tenant is bound for RLS
   ([`boltrig/kernel/channel_gateway_auth.py:16`](../../../boltrig/kernel/channel_gateway_auth.py) `if token is None or not (token.extra or {}).get("channel_gateway"):`).
3. **Elect one owner per channel.** `GET /reconcile` atomically claims or renews a
   45 second lease keyed (tenant, channel)
   ([`boltrig/kernel/channel_gateway_reconcile_routes.py:31`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `"lease = await kernel.store.claim_channel_gateway_lease("`).
   The claim is an upsert whose WHERE clause admits only the same owner or an expired
   lease ([`boltrig/store/channel_gateway_state.py:100`](../../../boltrig/store/channel_gateway_state.py) `"channel_gateway_leases.owner_lease_id=EXCLUDED.owner_lease_id"`).
   **Failure branch:** losing the election returns a standby spec with no credential
   material at all ([`boltrig/kernel/channel_gateway_reconcile_routes.py:38`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `"if lease is None:"`).
4. **Resolve provider credentials for the owner only.**
   [`boltrig/kernel/channel_gateway_specs.py:57`](../../../boltrig/kernel/channel_gateway_specs.py) `"async def resolved_gateway_spec(kernel, channel) -> dict:"`
   Every declared credential key must resolve or the spec becomes `needs_action`
   ([`boltrig/kernel/channel_gateway_specs.py:85`](../../../boltrig/kernel/channel_gateway_specs.py) `"if any(not values.get(key) for key in provider.credential_keys):"`),
   so a half-resolved provider never starts. The `signing` value becomes the spec's
   `secret`, every other key is merged into the adapter `config`
   ([`boltrig/kernel/channel_gateway_specs.py:93`](../../../boltrig/kernel/channel_gateway_specs.py) `"secret": values["signing"],`).
5. **Diff and apply on the daemon.** Channels that vanished are stopped, changed
   revisions restart their adapter, unchanged ones are left alone
   ([`services/channel_gateway/app.py:296`](../../../services/channel_gateway/app.py) `"async def _reconcile_once(self) -> None:"`).
   Adapters run under a supervisor whose start failures retry from 1 s doubling to 30 s
   ([`services/channel_gateway/app.py:408`](../../../services/channel_gateway/app.py) `"async def _run_adapter(self, spec: ChannelSpec) -> None:"`).
6. **Heartbeat.** Observations are validated shape-first (known channel, closed state
   set, 64-hex revision, bounded reason code)
   ([`boltrig/kernel/channel_gateway_reconcile_routes.py:146`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `or not re.fullmatch(r"[a-f0-9]{64}", revision)`)
   and then fenced on the lease
   ([`boltrig/kernel/channel_gateway_reconcile_routes.py:113`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `return "fenced"`).
   A channel whose activation is `external_pairing` reports `needs_action` even when
   its adapter started, because adapter readiness is not device linking
   ([`services/channel_gateway/app.py:457`](../../../services/channel_gateway/app.py) `"reason_code": "external_pairing_not_proven",`).
7. **Convergence is only claimed when the revisions match.** The console view reports
   `awaiting_gateway` whenever observed and desired differ
   ([`boltrig/kernel/channel_inventory_routes.py:109`](../../../boltrig/kernel/channel_inventory_routes.py) `"status": observed.status if converged else "awaiting_gateway",`)
   and is explicit that a lease is not liveness
   ([`boltrig/kernel/channel_inventory_routes.py:137`](../../../boltrig/kernel/channel_inventory_routes.py) `"proves_process_liveness": False,`).

### 5.7 Calls

1. **Create.** `POST /v1/calls` resolves the requested agent/model profiles
   ([`boltrig/kernel/call_profiles.py:9`](../../../boltrig/kernel/call_profiles.py) `"async def resolve_call_profiles(kernel, principal, body: dict):"`),
   binds or creates a conversation owned by the caller, refuses a second concurrent
   call on the same conversation with 409
   ([`boltrig/kernel/call_routes.py:93`](../../../boltrig/kernel/call_routes.py) `"\"status\": \"error\", \"reason\": \"call_already_active\","`),
   and snapshots the caller's permitted verbs into `tool_context`
   ([`boltrig/kernel/call_routes.py:59`](../../../boltrig/kernel/call_routes.py) `"concrete = canonical_concrete_verbs(tuple("`).
   **Failure branches:** an unresolvable profile returns 409 with a typed reason; no
   enabled `voice` socket channel returns a `realtime_unavailable` call plus the text
   conversation to continue in
   ([`boltrig/kernel/call_routes.py:125`](../../../boltrig/kernel/call_routes.py) `status="realtime_unavailable",`).
2. **Mint the media bearer.** 90 second TTL, digest at rest
   ([`boltrig/kernel/call_route_support.py:19`](../../../boltrig/kernel/call_route_support.py) `"MEDIA_TOKEN_TTL_SECONDS = 90"`),
   returned once with the WebSocket URL
   ([`boltrig/kernel/call_route_support.py:59`](../../../boltrig/kernel/call_route_support.py) `base = os.environ.get("BOLTRIG_CALL_WEBSOCKET_BASE", "/voice/v1/calls").rstrip("/")`).
3. **The browser connects to the gateway and authenticates in the first frame.**
   [`services/channel_gateway/app.py:800`](../../../services/channel_gateway/app.py) `"async def browser_call_media(websocket: WebSocket, call_id: str) -> None:"`
   The bearer travels in a message, not the URL, to keep it out of proxy access logs.
   **Failure branches:** a non-`authenticate` first frame, a missing token or a refused
   redemption closes with 4401; pool exhaustion closes with 4429 and evicts nothing
   ([`services/channel_gateway/app.py:826`](../../../services/channel_gateway/app.py) `"await websocket.close(code=4429)"`);
   a provider fault closes with 1013 and never echoes the bearer.
4. **Redeem.** The gateway calls `/v1/calls/gateway/claim`. Channel scope AND the owner
   lease are both required before the bearer is even compared
   ([`boltrig/kernel/call_gateway_routes.py:96`](../../../boltrig/kernel/call_gateway_routes.py) `"if not await _owns_call_channel(kernel, gateway, pending_call):"`),
   and a wrong channel, a standby gateway and a bad bearer are deliberately
   indistinguishable at that boundary. The claim itself is a single-use CAS that clears
   the digest ([`boltrig/store/realtime_calls.py:156`](../../../boltrig/store/realtime_calls.py) `"SET status='active', media_token_hash=NULL,"`).
   Only then is a caller-scoped MCP token minted from the stored snapshot
   ([`boltrig/kernel/call_gateway_routes.py:109`](../../../boltrig/kernel/call_gateway_routes.py) `"tool_token = kernel.mcp.issue_run_token("`).
5. **Activate the provider session with the caller's token.** The adapter forks a
   token view, closes any existing socket and opens a fresh one so no cross-caller
   dialogue survives ([`services/channel_gateway/xai_voice_adapter.py:387`](../../../services/channel_gateway/xai_voice_adapter.py) `"# A fresh provider socket is a hard cross-user conversation boundary."`).
   `session.tools` is built ONLY from `tools/list` over that token
   ([`services/channel_gateway/xai_voice_adapter.py:465`](../../../services/channel_gateway/xai_voice_adapter.py) `"async def _discover_tools(self) -> list[dict[str, Any]]:"`),
   and any config-supplied tool list is rejected before a socket opens
   ([`services/channel_gateway/xai_voice_adapter.py:251`](../../../services/channel_gateway/xai_voice_adapter.py) `"_reject_config_tools(config)  # fail closed BEFORE anything else"`).
6. **Every provider function call re-enters the chokepoint.**
   [`services/channel_gateway/xai_voice_adapter.py:752`](../../../services/channel_gateway/xai_voice_adapter.py) `"async def _call_kernel_tool("`
   An unknown tool name or a missing `call_id` is dropped
   ([`services/channel_gateway/xai_voice_adapter.py:694`](../../../services/channel_gateway/xai_voice_adapter.py) `"if not call_id or verb is None:"`);
   malformed arguments degrade to `{}` rather than failing the session.
7. **HITL.** A `pending_human` result withholds the provider's `function_call_output`,
   emits a durable `hitl` event and starts a poll on
   `GET /v1/calls/gateway/{call}/hitl/{request}`
   ([`services/channel_gateway/xai_voice_adapter.py:792`](../../../services/channel_gateway/xai_voice_adapter.py) `"async def _await_hitl_resolution("`).
   The authority stays entirely in the ordinary held-write replay; the call bridge only
   projects a content-free observation
   ([`boltrig/kernel/realtime_call_bridge.py:18`](../../../boltrig/kernel/realtime_call_bridge.py) `"async def project_realtime_hitl_outcome("`),
   and that projection is best-effort by construction
   ([`boltrig/kernel/realtime_call_bridge.py:28`](../../../boltrig/kernel/realtime_call_bridge.py) `"except Exception:  # noqa: BLE001 - dispatcher outcome already stands"`).
   The kernel refuses a gateway-authored `hitl` event that is not `pending`
   ([`boltrig/kernel/call_gateway_routes.py:169`](../../../boltrig/kernel/call_gateway_routes.py) `if event_type == "hitl" and (`).
8. **Events.** Every gateway-authored event is filtered to an allowlist of type and
   field before it is stored
   ([`boltrig/kernel/call_route_support.py:69`](../../../boltrig/kernel/call_route_support.py) `"def safe_gateway_payload(event_type: str, raw: object) -> dict | None:"`),
   transcript text is truncated to 8000 characters, usage counters must be
   non-negative ints under 10^15, and the whole payload must serialise under 32 KB.
   A final transcript is projected once into the conversation under a deterministic id
   ([`boltrig/kernel/call_transcript.py:11`](../../../boltrig/kernel/call_transcript.py) `"async def project_call_transcript(kernel, call, event) -> None:"`).
   **Failure branch:** an unknown event type or an unsafe payload is 400 and nothing is
   written.
9. **Typed mid-call text is bounded twice.** The adapter applies a per-generation
   limiter ([`services/channel_gateway/xai_voice_adapter.py:639`](../../../services/channel_gateway/xai_voice_adapter.py) `"def _admit_typed_text(self, text: str) -> bool:"`)
   and the kernel applies the durable, reconnect-stable one
   ([`boltrig/kernel/call_gateway_routes.py:57`](../../../boltrig/kernel/call_gateway_routes.py) `"async def _typed_text_admitted(kernel, call, payload: dict) -> bool:"`).
   The durable check FAILS CLOSED when the bounded event read cannot prove the whole
   history ([`boltrig/kernel/call_gateway_routes.py:66`](../../../boltrig/kernel/call_gateway_routes.py) `"if len(events) >= _TYPED_TEXT_HISTORY_LIMIT:"`).
   The transcript event is persisted BEFORE any provider work, which makes the kernel's
   ended-call refusal the admission authority
   ([`services/channel_gateway/xai_voice_adapter.py:619`](../../../services/channel_gateway/xai_voice_adapter.py) `"if not await self._emit_event("`).
10. **Reconnect and end.** `POST /v1/calls/{id}/media-token` rotates the bearer and
    moves the call to `reconnecting`; a call that is ended, failed or unavailable is
    refused 409 ([`boltrig/kernel/call_routes.py:213`](../../../boltrig/kernel/call_routes.py) `if call.status in {"ended", "failed", "realtime_unavailable"} or not call.channel_id:`).
    `POST /v1/calls/{id}/end` clears the bearer, writes an `ended` event and audits.

---

## 6. Data

### 6.1 Tables

| table | key | notes |
| --- | --- | --- |
| `channels` | `id` (global) | [`boltrig/store/schema.sql:971`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channels ("`; RLS-EXCLUDED by design |
| `channel_bindings` | `(tenant_id, id)` + unique `(tenant_id, channel_id, external_user_id)` | [`boltrig/store/schema.sql:1031`](../../../boltrig/store/schema.sql) `"CREATE UNIQUE INDEX IF NOT EXISTS channel_bindings_sender_idx"` |
| `channel_pairings` | `(tenant_id, id)`, index on `code_hash` | [`boltrig/store/schema.sql:1036`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channel_pairings ("` |
| `channel_deliveries` | `(tenant_id, channel_id, delivery_id)` + expiry index | [`boltrig/store/schema.sql:1056`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channel_deliveries ("` |
| `channel_outbox` | `(tenant_id, id)` + claim index `(tenant, channel, status, created_at)` | [`boltrig/store/schema.sql:1202`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channel_outbox ("` |
| `channel_gateway_status` | `(tenant_id, channel_id)` | [`boltrig/store/schema.sql:989`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channel_gateway_status ("` |
| `channel_gateway_leases` | `(tenant_id, channel_id)` + expiry index | [`boltrig/store/schema.sql:1005`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS channel_gateway_leases ("` |
| `realtime_calls` | `(tenant_id, id)`, owner index, partial media-claim index | [`boltrig/store/schema.sql:1223`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS realtime_calls ("` |
| `realtime_call_events` | `(tenant_id, id)`, FK `(tenant_id, call_id)` | [`boltrig/store/schema.sql:1253`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS realtime_call_events ("` |
| `notification_prefs` | `(tenant_id, id)` | [`boltrig/store/schema.sql:941`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS notification_prefs ("` |

Every child table FKs `channels(id) ON DELETE CASCADE`, so `channel.disconnect` takes
bindings, pairings, dedup markers, outbox rows, leases and observations with it.
`realtime_calls.channel_id` is `ON DELETE SET NULL` instead, so an in-flight call
survives the channel row's removal as a record.

### 6.2 RLS posture

Everything in this area is inside the tenant fence EXCEPT `channels` itself, and that
exclusion is documented rather than accidental:
[`boltrig/store/rls.sql:64`](../../../boltrig/store/rls.sql) `"channels table is EXCLUDED for the same reason (decision 0003): the inbound"`
The scoped set names the binding, pairing, observation and lease tables
([`boltrig/store/rls.sql:108`](../../../boltrig/store/rls.sql) `"'channel_bindings','channel_pairings','channel_gateway_status',"`),
the dedup and outbox tables
([`boltrig/store/rls.sql:120`](../../../boltrig/store/rls.sql) `"'channel_deliveries','channel_outbox',"`)
and the call tables
([`boltrig/store/rls.sql:123`](../../../boltrig/store/rls.sql) `"'realtime_calls','realtime_call_events',"`).
The RLS-parity gate treats `channels` as one of exactly three documented exclusions.

### 6.3 Migrations

`0035_channel_durability` created the dedup and outbox tables
([`migrations/versions/0035_channel_durability.py:30`](../../../migrations/versions/0035_channel_durability.py) `"CREATE TABLE IF NOT EXISTS channel_outbox ("`).
`0036_channel_addressing`, `0041_realtime_calls`, `0046_realtime_call_recovery`,
`0053_channel_gateway_reconciliation` and `0062_channel_gateway_owner_leases` carry the
rest of the area's schema forward.

### 6.4 Retention and encryption

- Dedup markers are TTL-bounded and swept opportunistically on every write
  ([`boltrig/store/channel_dedup.py:37`](../../../boltrig/store/channel_dedup.py) `"DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()"`).
  Nothing sweeps `channel_outbox`, `channel_gateway_status` or `realtime_call_events`.
- Credential material never rests in these tables. `channels.credential_ref` names a
  row in `credential_refs`, which is envelope-sealed at the store seam.
- Pairing codes rest only as sha256; media bearers rest only as sha256
  ([`boltrig/kernel/call_route_support.py:25`](../../../boltrig/kernel/call_route_support.py) `"def token_digest(token: str) -> str:"`).
- Raw PCM is never submitted to the kernel: the gateway's bridge holds it in bounded
  in-memory queues only ([`services/channel_gateway/browser_audio.py:16`](../../../services/channel_gateway/browser_audio.py) `"_MAX_PCM_FRAME_BYTES = 64 * 1024"`),
  and the kernel's event allowlist has no audio field at all.
- Outbox `last_error` is truncated to 500 characters at the store
  ([`boltrig/store/channel_outbox.py:255`](../../../boltrig/store/channel_outbox.py) `tenant_id, message_id, worker_id, (error or "")[:500],`)
  and to 200 by the daemon before it is sent
  ([`services/channel_gateway/app.py:638`](../../../services/channel_gateway/app.py) `await self._safe_fail(str(message.get("id")), f"{type(exc).__name__}: {exc}")`).

## 7. Configuration surface

### 7.1 Gateway daemon environment

| variable | default | what breaks if it is wrong |
| --- | --- | --- |
| `BOLTRIG_KERNEL_URL` | `http://localhost:8000` | egress-refused at boot, the daemon does not start ([`services/channel_gateway/app.py:696`](../../../services/channel_gateway/app.py) `raise RuntimeError(f"kernel URL egress-refused: {refusal}")`) |
| `CHANNEL_GATEWAY_TOKEN` | unset | restart-only token; a rotation needs a container restart |
| `CHANNEL_GATEWAY_TOKEN_FILE` | unset | hot-reloadable after a 401; both set at once is a hard boot error ([`services/channel_gateway/app.py:706`](../../../services/channel_gateway/app.py) `raise RuntimeError("configure exactly one gateway token source, not both")`) |
| `CHANNEL_GATEWAY_CHANNELS` | unset | a non-empty value in production is a hard boot error ([`services/channel_gateway/app.py:700`](../../../services/channel_gateway/app.py) `"static channel specs are disabled in production; use kernel "`); a malformed value is also a boot error, never a skipped channel |
| `CHANNEL_GATEWAY_EGRESS_ALLOW` | `kernel` in compose ([`docker-compose.yml:603`](../../../docker-compose.yml) `"CHANNEL_GATEWAY_EGRESS_ALLOW: ${CHANNEL_GATEWAY_EGRESS_ALLOW:-kernel}"`) | every platform dial is refused until the platform host is added |
| `CHANNEL_GATEWAY_POLL_SECONDS` | `2` | idle outbox poll cadence |
| `CHANNEL_GATEWAY_RECONCILE_SECONDS` | `10` | a value above 45 loses the owner lease between polls |
| `CHANNEL_GATEWAY_MAX_BROWSER_CALLS` | `8`, minimum 1 | a non-integer is a boot error; overflow closes new calls with 4429 |
| `BOLTRIG_PRODUCTION` / `BOLTRIG_ENV` / `ENV` / `APP_ENV` | unset | any of `1/true/yes/on/prod/production/staging` switches on the production posture ([`services/channel_gateway/app.py:667`](../../../services/channel_gateway/app.py) `"def _production() -> bool:"`) |

The token itself is shape-checked before use, so a truncated mount cannot become a
silent unauthenticated daemon
([`services/channel_gateway/app.py:84`](../../../services/channel_gateway/app.py) `_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,512}")`).

### 7.2 Kernel environment

`BOLTRIG_CALL_WEBSOCKET_BASE` (default `/voice/v1/calls`) is the only channel/call env
var read by the kernel in this area
([`boltrig/kernel/call_route_support.py:59`](../../../boltrig/kernel/call_route_support.py) `base = os.environ.get("BOLTRIG_CALL_WEBSOCKET_BASE", "/voice/v1/calls").rstrip("/")`).
Everything else is per-channel config authored through the control plane. Bounded
search for other reads: `rg -n "os.environ" boltrig/kernel/channel_*.py boltrig/kernel/call_*.py`
returns only that one site (2026-08-24, pinned tree).

### 7.3 Per-channel config keys the runtime actually reads

| key | read by | effect |
| --- | --- | --- |
| `sender_field` | intake | which body field is the external user id |
| `allowed_chats` | `chat_is_allowed` | presence switches the channel to allowlist mode |
| `thread_ceilings` | `thread_ceiling` | per-thread narrowing of the resolved grants |
| `self_onboard.role` / `.scope.departments` / `.welcome` | `_self_onboard` | opt-in stranger binding at member tier |
| `addressing.default_target` / `.routes` / `.thread_field` | `resolve_channel_addressing` | routing only |
| `addressing.chat_field` | `chat_id` only | allowlist keying only, NOT reply routing |
| `outbound_url` | `channel.send` | the webhook-class direct egress leg |
| `provider.*` | gateway reconcile | merged into the adapter config |

Only `addressing` and `self_onboard` are validated at the authoring seam
([`boltrig/config/channel_addressing.py:264`](../../../boltrig/config/channel_addressing.py) `"async def validate_channel_policy_config("`).
`allowed_chats`, `thread_ceilings` and `outbound_url` are accepted unvalidated and are
only checked at read time, where they fail closed. `provider_config` is validated
against the provider's declared key list
([`boltrig/models/channel_providers.py:133`](../../../boltrig/models/channel_providers.py) `"unknown = sorted(set(supplied_provider) - set(provider.provider_config_keys))"`).

### 7.4 Compose

The whole area is profile-gated and inert by default
([`docker-compose.yml:584`](../../../docker-compose.yml) `profiles: ["channels"]`).
The gateway sits on the `sandbox` network only, so it can reach the kernel intake but
not Postgres or Redis ([`docker-compose.yml:566`](../../../docker-compose.yml) `"channel-gateway:"`),
and its healthcheck consults `/ready`, not `/health`
([`docker-compose.yml:615`](../../../docker-compose.yml) `- python -c "import urllib.request; urllib.request.urlopen('http://localhost:8091/ready')" || exit 1`).
The signal sibling is a third-party image pinned by tag and digest
([`docker-compose.yml:638`](../../../docker-compose.yml) `"image: bbernhard/signal-cli-rest-api:0.99@sha256:96578363477d97cb1d8da303791b2ad686b374a255fce4d78c7c6f00ef56cba8"`).
The WhatsApp bridge binds the container interface and declares its own service alias
to its Host-header guard
([`docker-compose.yml:682`](../../../docker-compose.yml) `"WA_ACCEPTED_HOSTS: whatsapp-bridge"`).

## 8. PROCESS

### 8.1 Bring up a webhook channel (no gateway involved)

1. `POST /v1/channels` as an author with `platform: "webhook"` and
   `signing_secret_ref` naming a secret-store entry. The route returns the channel id
   and the inbound URL; the control verb is `consequence=high`, so in a normal posture
   it parks for approval first
   ([`boltrig/config/control_compat_specs.py:23`](../../../boltrig/config/control_compat_specs.py) `consequence: str = "high",`).
2. `POST /v1/channels/{id}/bindings` for each machine or human sender. Keep automation
   at `member`: the member ceiling denies `control.*`.
3. Optionally `PATCH /v1/channels/{id}` with
   `config.addressing.routes = {"<chat>": "workflow:<wf_id>"}` to pin a chat to a
   workflow. The recipe is in the gateway README
   ([`services/channel_gateway/README.md:239`](../../../services/channel_gateway/README.md) `"kernel terminates in-process, and fires a workflow deterministically through"`).
4. The source POSTs the signed body. Verify at the destination: a 202 with a
   `work_item` id is the only success.

### 8.2 Bring up a socket channel and its gateway

1. Author the channel with `credential_refs` only. A socket platform REFUSES plaintext
   ([`boltrig/config/control_channel_ops.py:100`](../../../boltrig/config/control_channel_ops.py) `"socket channels accept secret-store references only; plaintext is refused"`).
2. Complete any external pairing FIRST: register or link the signal-cli account into
   its named volume, or scan the WhatsApp QR with
   `node bridge.js --pair-only --session /data`
   ([`services/channel_gateway/README.md:346`](../../../services/channel_gateway/README.md) `"node bridge.js --pair-only --session /data   # scan the QR: WhatsApp > Linked devices"`).
3. Mint the gateway session: `POST /v1/channels/gateway/session` with the explicit
   channel ids. The token is shown once. Prefer writing it to a read-only mounted file.
4. `docker compose --profile channels up -d`.
5. Verify at the destination, in this order: `GET /ready` on the gateway must be 200
   (`token_ok`, `reconciliation_ok`, adapters converged); `GET /v1/channels` in the
   kernel must show the channel's `gateway.status` as the adapter's own observation and
   not `awaiting_gateway`; and only a real round trip proves delivery. The console is
   explicit that a lease is neither liveness nor provider certification
   ([`services/channel_gateway/README.md:53`](../../../services/channel_gateway/README.md) `"a browser-visible bearer. Worker may show the safe gateway label and lease"`).

### 8.3 Rotate a gateway token

Write the new token into the mounted file. The daemon reloads it only AFTER an
authorization refusal, and only if the value actually changed
([`services/channel_gateway/kernel_client.py:85`](../../../services/channel_gateway/kernel_client.py) `"def set_token(self, token: str) -> bool:"`).
With an env token, restart the container. There is no revoke: see RISKS.

### 8.4 Rotate a provider credential

`PATCH /v1/channels/{id}` with the new `credential_refs`. The kernel mints a FRESH
opaque credential ref id, writes the merged bundle and deletes the retired row
([`boltrig/config/control_channel_ops.py:222`](../../../boltrig/config/control_channel_ops.py) `channel.credential_ref = f"cred_{uuid.uuid4().hex[:16]}"`).
The desired revision changes as a consequence, so the owning gateway stops and restarts
that adapter on its next reconcile. Rotation is therefore a deliberate reconnect.

### 8.5 Diagnose a stuck delivery

1. `GET /v1/channels/{id}/deliveries` as an author. The projection is metadata only:
   `queued | in_flight | retryable | delivered | terminal_failed`, attempts,
   `next_attempt_at`, and a `safe_reason` that is never the provider's error text.
2. `terminal_failed` means the attempt cap was reached. Fix the channel first, then
   `POST /v1/channels/{id}/deliveries/{message_id}/retry` with the exact
   `expected_updated_at` you just read. A stale snapshot is a 409, and the approval is
   bound to the channel's configuration revision, so repairing the channel after
   approval invalidates that approval
   ([`boltrig/config/control_channel_approval.py:98`](../../../boltrig/config/control_channel_approval.py) `"if not expected_updated_at or expected_updated_at != observed_updated_at:"`).
3. `GET /status` on the gateway lists channels, live adapters and the last observation
   per channel. It contains no secrets, but it is also unauthenticated: see RISKS.

### 8.6 Diagnose a call

`GET /v1/calls/{id}` for status, `GET /v1/calls/{id}/events` for the normalised
transcript and tool/HITL/lifecycle events, `GET /v1/calls/{id}/usage` for the owner
aggregate. All three are owner-scoped: a non-owner gets 404, never 403
([`boltrig/kernel/call_routes.py:30`](../../../boltrig/kernel/call_routes.py) `"async def _owned_call(kernel, principal, call_id: str):"`).

### 8.7 Gates that bind this area

`make compose-validate` validates the channels profile explicitly, because that profile
owns credential-bearing named volumes the default profile never resolves
([`Makefile:274`](../../../Makefile) `"$(COMPOSE) --profile channels -f docker-compose.yml config --quiet"`).
The WhatsApp bridge's `package-lock.json` is a named exemption from the repo lockfile
policy ([`Makefile:399`](../../../Makefile) `"LOCKFILE_POLICY_EXEMPT := services/channel_gateway/whatsapp_bridge/package-lock.json"`).

### 8.8 Adding a platform

The port guide is the contract, and it is explicit that a port without BOTH legs of the
round-trip proof is scaffold
([`services/channel_gateway/ADDING_A_PLATFORM.md:106`](../../../services/channel_gateway/ADDING_A_PLATFORM.md) `"of that proof is scaffold, and the docs will say so."`).
The six binding rules are: no `boltrig.*` import; no policy or grants; secrets only via
config at spawn and never logged; every dial egress-checked; no new kernel route
([`services/channel_gateway/ADDING_A_PLATFORM.md:86`](../../../services/channel_gateway/ADDING_A_PLATFORM.md) `"5. **No new kernel route**: inbound goes to the ONE intake path, outbound rides"`);
and the SDK stays in the gateway image.

---

## 9. Failure modes and fail-open/fail-closed posture

### 9.1 The ingest posture, proven

**The kernel intake is fail-CLOSED.** The proof is a two-link chain, not an assertion.

1. `verify_and_normalise` skips the signature step when the secret is falsy. That is
   the documented library behaviour: [`boltrig/adapters/builtin/inbound_webhook.py:11`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"When no secret is configured the signature step is"`
   and the guard itself is `if secret:`
   ([`boltrig/adapters/builtin/inbound_webhook.py:349`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if secret:"`).
   Read alone, that is a fail-open library.
2. The channel intake never reaches that branch with a falsy secret, because it
   returns 503 first
   ([`boltrig/kernel/channel_inbound_routes.py:81`](../../../boltrig/kernel/channel_inbound_routes.py) `"if not secret:"`).
   The only caller of `verify_and_normalise` in the kernel is that route
   (bounded: `rg -n "verify_and_normalise" boltrig/ services/`, 2026-08-24, pinned tree,
   hits only `channel_inbound_routes.py` and the library's own definition).

So there is no unsigned channel ingress. Within the signed path the posture is:

| guard | direction | proof |
| --- | --- | --- |
| unknown / disabled channel | closed (404) | `channel is None or not channel.enabled` |
| unresolvable secret | closed (503) | `_channel_secret` returns None for a broken ref, and any exception in `fetch_material` is swallowed into None ([`boltrig/kernel/channel_routes.py:101`](../../../boltrig/kernel/channel_routes.py) `"except Exception:  # an unresolvable reference fails closed below"`) |
| missing signature header | closed (401) | `raise WebhookAuthError("signed webhook is missing its signature header")` |
| native scheme without a timestamp | closed (401) | refused before the HMAC is computed |
| platform scheme without raw bytes | closed (401) | `if raw_body is None:` |
| stale bound timestamp | closed (401) | 300 s window |
| replayed delivery id | closed (200 `duplicate`, nothing minted) | store record-and-check |
| unknown chat under `allowed_chats` | closed (403) | allowlist mode |
| malformed `allowed_chats` | closed (403) | a non-list, or any non-string entry, returns False |
| unbound sender | closed (403, or 200 `ignored` when configured) | `unpaired_behavior` |
| binding at an unknown tier | closed (None principal) | not in `CHANNEL_TIERS` |
| deactivated bound user | closed (None principal) | user status check |
| malformed `thread_ceilings` | closed (empty grant set) | never a wildcard |
| rate limit | closed (429, nothing minted) | enforced before `create_work_item` |
| unknown `workflow:` target | closed (parks AWAITING_HUMAN) | pump `_park` |

**One place is fail-OPEN by design and says so.** A platform signature with no
timestamp anywhere (GitHub's scheme) has no clock to check, so its only replay defence
is the 600 second dedup window
([`boltrig/adapters/builtin/inbound_webhook.py:309`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"its replay defence is the dedup, not the clock"`).
A captured GitHub-signed request replayed after that TTL mints a second work item.

### 9.2 Gateway-side postures

| guard | direction | proof |
| --- | --- | --- |
| malformed `CHANNEL_GATEWAY_CHANNELS` | closed (boot error) | [`services/channel_gateway/app.py:117`](../../../services/channel_gateway/app.py) `"def load_channel_specs(raw: str | None) -> list[ChannelSpec]:"` raises rather than skipping a channel |
| static specs in production | closed (boot error) | `_production()` |
| two token sources | closed (boot error) | mutually exclusive |
| malformed token file | closed (`ValueError`) | `_TOKEN_PATTERN` |
| kernel URL egress-refused | closed (boot error) | `build_daemon` raises |
| initial reconcile fails | closed for readiness | `reconcile_ok` starts False and is only set by a real authenticated answer ([`services/channel_gateway/app.py:187`](../../../services/channel_gateway/app.py) `"self.reconcile_ok = not self._owner_election_supported"`) |
| token expired mid-run | degraded, not silent | the pump idles 30 s rather than hot-looping ([`services/channel_gateway/app.py:604`](../../../services/channel_gateway/app.py) `"# mark ourselves degraded and idle instead of hot-looping."`) |
| adapter start failure | retry with backoff, observation `degraded` | 1 s doubling to 30 s |
| delivery failure | outbox `fail`, kernel backoff | at-least-once |
| ack lost in transit | at-least-once redelivery | the lease lapses |
| intake POST fails | OPEN LOSS: the message is dropped | `_on_message` logs and returns |
| egress guard on an allow-listed loopback host | deliberately permissive | [`services/channel_gateway/egress.py:64`](../../../services/channel_gateway/egress.py) `allowlisted = any(host_l == a or host_l.endswith("." + a) for a in allow)` |
| link-local / metadata target | closed even when allow-listed | [`services/channel_gateway/egress.py:35`](../../../services/channel_gateway/egress.py) `"return addr.is_link_local or addr.is_unspecified"` |
| DNS rebinding between check and connect | OPEN, documented residual | [`services/channel_gateway/egress.py:13`](../../../services/channel_gateway/egress.py) `"control stays the container/network egress restriction (see the Dockerfile"` |

The last row is stated in the module itself as a known residual: the `getaddrinfo`
answer is validated at check time while httpx re-resolves at connect time, and
connect-to-IP pinning is deliberately not carried by the severed service.

### 9.3 Adapter-side postures

- A malformed JSON line on the generic adapter is dropped, never fatal
  ([`services/channel_gateway/adapters.py:140`](../../../services/channel_gateway/adapters.py) `"continue  # a malformed line is dropped, never fatal"`),
  and a line without both `sender` and `text` is ignored
  ([`services/channel_gateway/adapters.py:144`](../../../services/channel_gateway/adapters.py) `and message.get("text") is not None`).
- Every port DROPS an event that lacks its stable delivery id rather than ingesting an
  undedupable message: Slack, Telegram, Discord, Signal all log and return; WhatsApp
  answers the bridge with 400
  ([`services/channel_gateway/whatsapp_adapter.py:185`](../../../services/channel_gateway/whatsapp_adapter.py) `return JSONResponse({"ok": False, "error": "incomplete event"}, status_code=400)`).
- Bot and self echoes are filtered in the adapter, which is loop prevention and not
  policy: WhatsApp's vendored bridge had the Hermes allowlist stripped precisely so
  who-may-talk stays a kernel binding row
  ([`services/channel_gateway/whatsapp_adapter.py:35`](../../../services/channel_gateway/whatsapp_adapter.py) `"Policy (condition 2): the adapter and bridge own NO who-may-talk decision -"`).
- A `deliver` with no connected peer raises rather than silently succeeding
  ([`services/channel_gateway/adapters.py:114`](../../../services/channel_gateway/adapters.py) `raise AdapterDeliveryError("no connected peer to deliver to")`).

### 9.4 Call postures

- The media claim is indistinguishable across three different refusals on purpose
  ([`boltrig/kernel/call_gateway_routes.py:97`](../../../boltrig/kernel/call_gateway_routes.py) `"# Keep a wrong channel, standby gateway and bad bearer"`).
- The durable typed-text budget fails CLOSED when it cannot read the whole history
  ([`boltrig/kernel/call_gateway_routes.py:32`](../../../boltrig/kernel/call_gateway_routes.py) `"_TYPED_TEXT_HISTORY_LIMIT = 500"`).
- The event sink is best-effort for observability but AUTHORITATIVE for typed text: the
  adapter refuses to inject text the kernel would not persist
  ([`services/channel_gateway/xai_voice_adapter.py:619`](../../../services/channel_gateway/xai_voice_adapter.py) `"if not await self._emit_event("`).
- The HITL bridge is explicitly best-effort and cannot change the resumed action
  ([`boltrig/kernel/realtime_call_bridge.py:29`](../../../boltrig/kernel/realtime_call_bridge.py) `log.warning("realtime held-call projection failed", exc_info=True)`).
- A config-injected tool list is refused at adapter init, before any socket opens
  ([`services/channel_gateway/xai_voice_adapter.py:130`](../../../services/channel_gateway/xai_voice_adapter.py) `"def _reject_config_tools(config: dict[str, Any]) -> None:"`).
- A browser call never re-enters the static channel binding, so one utterance cannot
  become both a call turn and a work item
  ([`services/channel_gateway/xai_voice_adapter.py:582`](../../../services/channel_gateway/xai_voice_adapter.py) `"if self._browser_call_active:"`).

## 10. What is proven

| invariant | what it binds here | a named test |
| --- | --- | --- |
| SEC-28 | the gateway imports no boltrig package code | `tests/security/test_severability.py::test_channel_gateway_imports_no_boltrig_package_code` |
| SEC-66 | replay defence and durable dedup | `tests/security/test_channel_inbound.py::test_webhook_replay_with_rewritten_timestamp_rejected` |
| SEC-175 | durable, atomic, tenant-scoped dedup plus the content-hash fallback | `tests/store/test_channel_durability.py::test_record_channel_delivery_is_atomic_and_tenant_scoped` |
| SEC-176 | single-winner outbox, CAS settle, backoff, terminal cap | `tests/store/test_channel_durability.py::test_outbox_fail_backs_off_then_terminates` |
| SEC-177 | no policy/grants/credential authority, show-once token, owner lease | `tests/security/test_channel_gateway_routes.py::test_only_owner_receives_resolved_secrets_heartbeat_and_outbox_work` |
| SEC-178 | addressing is routing data; workflow targets; unknown parks | `tests/security/test_channel_addressing.py::test_an_unknown_workflow_target_parks_for_a_human` |
| SEC-179 | notification round trip, inbound and outbound | `tests/security/test_channel_notifications.py::test_run_completion_returns_to_the_originating_thread` |
| SEC-180 | self-onboarding is member-only, rate-limited, never over a binding | `tests/security/test_channel_self_onboard.py::test_an_existing_binding_is_never_onboarded_over` |
| SEC-183 | voice tools are kernel-discovered only | `tests/security/test_channel_xai_voice_roundtrip.py::test_server_side_tool_config_is_rejected_at_init` |
| SEC-195 | opt-in allowlist and thread ceilings are narrowing-only | `tests/security/test_channel_policy.py::test_thread_ceiling_is_stamped_and_narrows_execution_authority` |
| SEC-67 | intake rate limits mint nothing | `tests/security/test_channel_inbound.py::test_inbound_intake_rate_limited_per_sender` |
| CHAN-PROV-01 | kernel-authored provenance, safe public projection | `tests/unit/test_channel_provenance.py::test_kernel_stamp_overwrites_forgery_and_public_view_omits_provider_ids` |
| SEC-WRK-03 | bounded browser media, isolated concurrent calls | `tests/security/test_channel_voice_concurrency.py::test_browser_voice_calls_are_isolated_bounded_and_released_exactly` |
| SEC-WRK-04 | exact-call HITL and content-free usage | `tests/security/test_realtime_call_routes.py::test_voice_hitl_answer_resumes_the_exact_sealed_call_and_projects_resolution` |
| SEC-WRK-11 | notification routes are server-declared and binding-gated | `tests/security/test_notification_surface.py::test_notification_write_rejects_unproduced_events_and_unverified_targets` |
| SEC-14 / SEC-39 | channel-native approve/deny runs the API's own eligibility | `tests/security/test_channel_hitl_replies.py::test_channel_approve_and_deny_use_the_api_eligibility` |

Every shipped port carries a two-leg round-trip proof against a test kernel:
`test_channel_gateway_roundtrip.py` (generic), `test_channel_slack_roundtrip.py`,
`test_channel_telegram_roundtrip.py`, `test_channel_discord_roundtrip.py`,
`test_channel_signal_roundtrip.py`, `test_channel_whatsapp_roundtrip.py`,
`test_channel_xai_voice_roundtrip.py`.

**What is NOT proven by any of these.** Live-platform verification, credentialed xAI
staging, invoice reconciliation and hard voice budgets are named acceptance gaps by the
subsystem's own documents
([`services/channel_gateway/README.md:229`](../../../services/channel_gateway/README.md) `"Credentialed xAI staging, invoice reconciliation, and hard whole-call"`),
and the ruling's own status note lists live-platform verification as an operator step
([`docs/decisions/0003-channel-gateway-ruling.md:90`](../../../docs/decisions/0003-channel-gateway-ruling.md) `"Remaining follow-ons: native media, team scopes beyond departments, live-platform"`).

## 11. RISKS

RISK (HIGH): the generic adapter's inbound seam has NO authentication of its own, and
its `sender` field selects which Principal the message acts as. Anything that can open
the TCP listener can impersonate any bound `external_user_id` on that channel.
[`services/channel_gateway/adapters.py:98`](../../../services/channel_gateway/adapters.py) `"self._server = await asyncio.start_server(self._handle_peer, self._host, self._port)"`
The README states the exposure plainly for the off-box case
([`services/channel_gateway/README.md:109`](../../../services/channel_gateway/README.md) `"`listen_host: 0.0.0.0` plus network-level controls - the seam carries no"`),
but the same is true on-box for any process that can reach the loopback port.

RISK (HIGH): the WhatsApp adapter's `POST /inbound` listener has no authentication
either, and compose points the bridge at it across the sandbox network.
[`services/channel_gateway/whatsapp_adapter.py:136`](../../../services/channel_gateway/whatsapp_adapter.py) `listener.post("/inbound")(self._handle_inbound)`
with [`docker-compose.yml:679`](../../../docker-compose.yml) `"ADAPTER_URL: ${WHATSAPP_ADAPTER_URL:-http://channel-gateway:3001/inbound}"`.
Any container on the `sandbox` network can post a forged WhatsApp message naming any
sender id. This is the one inbound path in the area that reaches the governed intake
without verifying authenticity at its own boundary.

RISK (HIGH): the WhatsApp bridge's `POST /send` is gated only by a Host header, which
is a DNS-rebinding defence and not authentication. Any container on the sandbox network
can send arbitrary WhatsApp messages as the linked account.
[`services/channel_gateway/whatsapp_bridge/bridge.js:309`](../../../services/channel_gateway/whatsapp_bridge/bridge.js) `"error: 'Invalid Host header. Bridge accepts loopback hosts only.',"`
The same is true of the signal-cli sibling, which exposes an unauthenticated JSON-RPC
send on the same network ([`docker-compose.yml:645`](../../../docker-compose.yml) `"expose:"`).

RISK (HIGH): the Worker edge proxies the ENTIRE gateway under `/voice/`, not just the
media WebSocket, so `/voice/status` returns the tenant's channel ids, live adapter set
and per-channel observations to any unauthenticated caller who can reach Worker.
[`apps/worker/nginx.conf:67`](../../../apps/worker/nginx.conf) `"location /voice/ {"`
and [`services/channel_gateway/app.py:869`](../../../services/channel_gateway/app.py) `"channels": sorted(daemon._specs),`.
Channel ids are the capability that stands in for the tenant fence on the RLS-excluded
`channels` table, so leaking them erodes a stated defence layer even though the intake
signature still gates ingest.

RISK (MEDIUM): a gateway session token cannot be revoked. `McpFace.revoke` exists but
no route, console action or control verb calls it for a gateway session; the only
bounds are the 3600 second TTL and the 45 second per-channel lease.
[`boltrig/kernel/mcp.py:130`](../../../boltrig/kernel/mcp.py) `"def revoke(self, token: str) -> None:"`
(bounded: `rg -n "mcp\.revoke|revoke\(token" boltrig/ tests/ apps/ sdks/`, 2026-08-24,
pinned tree: the only callers are three test files and the Codex runtime resolver).
SEC-177 nevertheless describes the token as "revocable".

RISK (MEDIUM): the MCP run-token registry is a process-local dict, so a kernel restart
silently invalidates every live gateway session and a multi-replica deployment breaks
unless every gateway call lands on the minting replica.
[`boltrig/kernel/mcp.py:79`](../../../boltrig/kernel/mcp.py) `"self._tokens: dict[str, RunToken] = {}"`
The README discloses it ([`services/channel_gateway/README.md:86`](../../../services/channel_gateway/README.md) `"second token-minting authority. The MCP token registry is currently local to"`)
but nothing in code or compose prevents the second replica.

RISK (MEDIUM): the gateway token's maximum TTL is one hour
([`boltrig/kernel/mcp.py:75`](../../../boltrig/kernel/mcp.py) `"MAX_RUN_TOKEN_TTL_SECONDS = 3600"`),
and the session mint defaults to exactly that. A gateway therefore needs an operator to
mint and place a fresh token at least hourly, forever; there is no renewal path, and an
env-token deployment additionally needs a container restart each time. Nothing in the
repo automates that, which makes continuous socket-channel operation an unattended-hours
problem rather than a deployment step.

RISK (MEDIUM): `allowed_chats` and the reply/thread ceiling can key on DIFFERENT body
fields for the same message. The allowlist consults `addressing.chat_field` first and
then a six-field order
([`boltrig/kernel/channel_policy.py:23`](../../../boltrig/kernel/channel_policy.py) `configured = addressing.get("chat_field") or addressing.get("thread_field")`),
while addressing consults only `addressing.thread_field` and a different five-field
order ([`boltrig/kernel/channel_addressing_runtime.py:24`](../../../boltrig/kernel/channel_addressing_runtime.py) `thread_field = addressing.get("thread_field")`).
A body carrying both `channel` and `chat_id`, or a channel configured with `chat_field`
but not `thread_field`, is allow-listed on one key and ceilinged on another.

RISK (MEDIUM): the per-message `target` is taken from the signed body and is NOT
validated against the addressing catalogue at intake, only shape-checked by a slug
regex ([`boltrig/kernel/channel_addressing_runtime.py:34`](../../../boltrig/kernel/channel_addressing_runtime.py) `target = _clean_target(body.get("target"))`).
Catalogue validation applies only to AUTHORED channel config
([`boltrig/config/channel_addressing.py:191`](../../../boltrig/config/channel_addressing.py) `"async def validate_channel_addressing_config("`).
A bound member-tier sender can therefore pin any named agent or any `workflow:<id>` on a
per-message basis. Authority is still the sender's grants, so this is a routing rather
than an authorisation defect, but it is a wider surface than the console exposes.

RISK (MEDIUM): the intake rate limiter runs AFTER sender resolution, so a signed message
from an unbound sender consumes a binding lookup, a self-onboard evaluation and a store
round trip without ever touching the per-channel counter
([`boltrig/kernel/channel_inbound_routes.py:53`](../../../boltrig/kernel/channel_inbound_routes.py) `"throttled = await _enforce_intake_rate(kernel, channel, sender)"`).
Only the 5/minute onboarding limiter bounds that path, and only when `self_onboard` is
configured.

RISK (MEDIUM): a socket channel whose adapter is flapping burns the outbox attempt cap
on rows it never had a connection for. `_settle` treats "no live adapter" as a delivery
failure ([`services/channel_gateway/app.py:634`](../../../services/channel_gateway/app.py) `raise KernelLinkError("no live adapter for this channel")`),
and with the shipped 5 second base and cap of 8
([`boltrig/kernel/channel_gateway_outbox_routes.py:13`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"OUTBOX_MAX_ATTEMPTS = 8"`)
a user's approval notice reaches terminal `failed` in about eleven minutes of adapter
downtime, after which recovery is an admin approval, not a retry.

RISK (MEDIUM): `_owned_channels` requires the owner lease to have at least
`lease_seconds` remaining ([`boltrig/kernel/channel_gateway_outbox_routes.py:70`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"minimum_remaining_seconds=outbox_lease,"`),
but the owner lease is only 45 seconds while the outbox lease is clamped to 300. A
client that asks for any lease above roughly 35 seconds silently claims nothing, with no
error and no observation. The shipped client asks for 30, so the coupling is invisible
until someone tunes it.

RISK (MEDIUM): the gateway drops an inbound message whose intake POST fails at the
transport level ([`services/channel_gateway/app.py:272`](../../../services/channel_gateway/app.py) `"except KernelLinkError as exc:"`).
There is no local spool and no retry, so a kernel restart during a burst loses those
messages entirely. Outbound is durable; inbound is not.

RISK (LOW): binding ROLE is trusted from the binding row without re-checking that the
subject still holds it, for a subject with no user record. A synthetic
`external:<platform>:<id>` subject keeps the member ceiling for as long as the row
exists; there is no expiry and no periodic re-attestation
([`boltrig/kernel/channel_principal.py:86`](../../../boltrig/kernel/channel_principal.py) `"grants = ceiling"`).

RISK (LOW): nothing prunes `channel_outbox`, `channel_gateway_status` or
`realtime_call_events`. Delivered and terminally failed rows accumulate for the life of
the tenant; only `channel_deliveries` is swept
([`boltrig/store/channel_dedup.py:37`](../../../boltrig/store/channel_dedup.py) `"DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()"`).

RISK (LOW): `_sole_pending_for` lists EVERY pending HITL request for the tenant and then
filters in Python, on every inbound channel message that carries text
([`boltrig/kernel/channel_routes.py:145`](../../../boltrig/kernel/channel_routes.py) `"async def _sole_pending_for(kernel, ch, subject: str, thread: str):"`).
On a tenant with a large pending queue every chat message pays that scan.

RISK (LOW): condition 4 of the ruling required Slack v0 and Discord Ed25519 verification
"at the correct byte/handshake boundary"
([`docs/decisions/0003-channel-gateway-ruling.md:50`](../../../docs/decisions/0003-channel-gateway-ruling.md) `4. Per-platform verification (Slack v0, Discord Ed25519, MS Graph validationToken/clientState) implemented at the correct byte/handshake boundary`).
Neither exists in the tree. The ports answer honestly that they expose no HTTP
interactions endpoint, so there is no surface for those schemes
([`services/channel_gateway/slack_adapter.py:12`](../../../services/channel_gateway/slack_adapter.py) `"The verification boundary (condition 4, an honest statement): this port is"`).
That is a defensible reading, but it means any future webhook-mode Slack or Discord port
lands on an unimplemented verifier.

## 12. OPEN QUESTIONS

1. **Does any deployment actually run two gateway replicas?** The lease makes a second
   replica safe for channel ownership, but the process-local MCP registry makes its
   token useless against a different API replica. Settled by reading the production
   compose overlays and the replica counts, which are outside the pinned tree.
2. **Is `/voice/` reachable unauthenticated in the shipped production edge, or does
   Caddy gate it upstream?** `deploy/Caddyfile.example` mentions the voice proxy only in
   a comment; the nginx image proxies the whole prefix. Settled by reading the live
   Caddy config for a deployed stack.
3. **What sweeps `channel_outbox` in a long-lived tenant?** No janitor was found.
   Bounded: `rg -n "channel_outbox" boltrig/` (2026-08-24, pinned tree) hits eleven
   files, all of which enqueue, claim, settle, retry or project rows; the only DELETE
   statement anywhere in the store layer for this family is the dedup sweep, and
   `purge_closed_conversations` does not reach the outbox. Settled by an operator
   statement or a retention job outside the tree.
4. **Is the one-hour gateway token TTL operated by hand today?** The README says token
   placement is an operator action and names no automation. Settled by the deployment
   runbook for a stack that actually runs the channels profile.
5. **Does `msteams` have any consumer?** It is a webhook-transport provider with a
   Teams label and no adapter of its own. Settled by finding a tenant with an `msteams`
   channel row, which cannot be done from the tree.
6. **Whether the `voice` channel's `speaker` config was ever bound to a real Principal
   in a shipped deployment.** The static (non-browser) voice path attributes every
   utterance to one configured external user id, which is only meaningful for a physical
   single-speaker box. Settled by a live channel row.

---

## 13. Requirements

One hundred rows, BT-REQ-1700 .. BT-REQ-1799. Status counts: 93 IMPLEMENTED,
5 IMPLEMENTED-UNTESTED, 1 SEAM, 1 SCAFFOLDED, 0 DEAD, 0 UNCERTAIN.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1700 | The channel gateway service lives outside the boltrig package and imports nothing from it. | IMPLEMENTED | [`services/channel_gateway/app.py:22`](../../../services/channel_gateway/app.py) `"SEVERED: this service is deliberately NOT part of the ``boltrig`` package and"` | SEC-28 |
| BT-REQ-1701 | Browser-authored channel config rejects secret-like and deployment-topology keys at any depth. | IMPLEMENTED | [`boltrig/models/channel_providers.py:80`](../../../boltrig/models/channel_providers.py) `"_FORBIDDEN_CONFIG_FRAGMENTS = ("` | - |
| BT-REQ-1702 | A socket-class channel refuses an inline plaintext signing secret and accepts references only. | IMPLEMENTED | [`boltrig/config/control_channel_ops.py:100`](../../../boltrig/config/control_channel_ops.py) `"socket channels accept secret-store references only; plaintext is refused"` | - |
| BT-REQ-1703 | Every control.channel verb defaults to high consequence. | IMPLEMENTED | [`boltrig/config/control_compat_specs.py:23`](../../../boltrig/config/control_compat_specs.py) `consequence: str = "high",` | SEC-39 |
| BT-REQ-1704 | A channel approval is bound to the channel's exact configuration revision. | IMPLEMENTED | [`boltrig/config/control_channel_approval.py:29`](../../../boltrig/config/control_channel_approval.py) `"def channel_configuration_revision(channel: Any) -> str:"` | - |
| BT-REQ-1705 | Both transport classes terminate at one signed intake route. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:224`](../../../boltrig/kernel/channel_inbound_routes.py) `"/v1/channels/{channel_id}/inbound",` | SEC-177 |
| BT-REQ-1706 | A channel whose signing secret does not resolve refuses intake with 503 and mints nothing. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:82`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"error": "channel_misconfigured"}, status_code=503)` | - |
| BT-REQ-1707 | A missing or mismatched signature is refused 401 before any tenant is bound. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:92`](../../../boltrig/kernel/channel_inbound_routes.py) `return JSONResponse({"status": "denied", "reason": "signature"}, status_code=401)` | SEC-01 |
| BT-REQ-1708 | Which bytes the intake HMAC covers is decided by the signature header name. | IMPLEMENTED | [`boltrig/adapters/builtin/inbound_webhook.py:277`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if header_name == _BOLTRIG_SIGNATURE_HEADER:"` | SEC-01 |
| BT-REQ-1709 | The boltrig-native scheme refuses a signed request that carries no timestamp. | IMPLEMENTED | [`boltrig/adapters/builtin/inbound_webhook.py:283`](../../../boltrig/adapters/builtin/inbound_webhook.py) `raise WebhookAuthError("signed webhook is missing its timestamp (replay protection)")` | SEC-66 |
| BT-REQ-1710 | A platform-signed request whose raw body is unavailable fails closed. | IMPLEMENTED | [`boltrig/adapters/builtin/inbound_webhook.py:294`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if raw_body is None:"` | SEC-01 |
| BT-REQ-1711 | A bound timestamp outside the 300 second replay window is refused despite a genuine signature. | IMPLEMENTED | [`boltrig/adapters/builtin/inbound_webhook.py:310`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"if replay_window_seconds > 0 and ts is not None:"` | SEC-66 |
| BT-REQ-1712 | Replay dedup is a durable atomic record-and-check keyed by tenant, channel and delivery id. | IMPLEMENTED | [`boltrig/store/channel_dedup.py:44`](../../../boltrig/store/channel_dedup.py) `"ON CONFLICT (tenant_id, channel_id, delivery_id) DO NOTHING"` | SEC-175 |
| BT-REQ-1713 | A message carrying no stable delivery id is deduped by content hash inside a shorter window. | IMPLEMENTED | [`boltrig/adapters/builtin/inbound_webhook.py:120`](../../../boltrig/adapters/builtin/inbound_webhook.py) `"_CONTENT_SEEN_TTL_SECONDS = 300"` | SEC-175 |
| BT-REQ-1714 | The tenant is bound for RLS only after the intake signature verifies. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:41`](../../../boltrig/kernel/channel_inbound_routes.py) `"set_current_tenant(channel.tenant_id)"` | SEC-08 |
| BT-REQ-1715 | Declaring allowed_chats switches the channel into allowlist mode and an unknown chat fails closed. | IMPLEMENTED | [`boltrig/kernel/channel_policy.py:37`](../../../boltrig/kernel/channel_policy.py) `if "allowed_chats" not in config:` | SEC-195 |
| BT-REQ-1716 | A verified sender becomes a Principal only through a tenant-scoped binding row. | IMPLEMENTED | [`boltrig/kernel/channel_principal.py:68`](../../../boltrig/kernel/channel_principal.py) `"binding = await store.get_channel_binding("` | K-13 |
| BT-REQ-1717 | A channel principal's ceiling is the recorded tier's workspace ceiling and never a wildcard. | IMPLEMENTED | [`boltrig/kernel/channel_principal.py:76`](../../../boltrig/kernel/channel_principal.py) `"ceiling = WORKSPACE_ROLE_CEILINGS[_TIER_CEILING_ROLE[role]]"` | SEC-34 |
| BT-REQ-1718 | A deactivated bound user's channel identity stops resolving immediately. | IMPLEMENTED | [`boltrig/kernel/channel_principal.py:79`](../../../boltrig/kernel/channel_principal.py) `if user.status != "active":` | SEC-34 |
| BT-REQ-1719 | A bound user's current grants intersect the tier ceiling downward. | IMPLEMENTED | [`boltrig/kernel/channel_principal.py:81`](../../../boltrig/kernel/channel_principal.py) `"grants = current_grants_for_user(user).intersect(ceiling)"` | SEC-34 |
| BT-REQ-1720 | An unbound sender is denied fail-closed unless the channel opts into ignore or pair. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:115`](../../../boltrig/kernel/channel_inbound_routes.py) `"status": "denied", "reason": "sender not paired"},` | K-13 |
| BT-REQ-1721 | A pairing code rests only as sha256 and is returned to its author exactly once. | IMPLEMENTED | [`boltrig/config/control_channel_ops.py:279`](../../../boltrig/config/control_channel_ops.py) `code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),` | SEC-05 |
| BT-REQ-1722 | Pairing consumption enforces expiry, a constant-time compare, an attempts cap of five and a single-use CAS. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:343`](../../../boltrig/kernel/channel_routes.py) `"if not await kernel.store.consume_channel_pairing(channel.tenant_id, pairing.id):"` | - |
| BT-REQ-1723 | No principal may bind an external sender to a role ranked above its own. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:381`](../../../boltrig/kernel/channel_routes.py) `"status": "denied", "reason": "cannot bind a role ranked above your own"},` | SEC-102 |
| BT-REQ-1724 | Self-serve onboarding is opt-in per channel and accepts only the member role. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:281`](../../../boltrig/kernel/channel_routes.py) `"if role not in SELF_ONBOARD_ROLES:"` | SEC-180 |
| BT-REQ-1725 | Self-serve onboarding never mints a fresh identity over an existing binding. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:286`](../../../boltrig/kernel/channel_routes.py) `"# A binding EXISTS but resolved to no principal (an unknown tier, or a"` | SEC-180 |
| BT-REQ-1726 | Self-serve onboarding is rate limited per channel before any binding is minted. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:66`](../../../boltrig/kernel/channel_routes.py) `ONBOARD_RL_PER_CHANNEL = RateLimit(per="minute", max=5, scope="verb")` | SEC-180 |
| BT-REQ-1727 | A self-onboarded sender acts as a deterministic synthetic subject with no user record. | IMPLEMENTED | [`boltrig/kernel/channel_principal.py:31`](../../../boltrig/kernel/channel_principal.py) `"def self_onboard_subject(platform: str, external_user_id: str) -> str:"` | SEC-180 |
| BT-REQ-1728 | Intake is rate limited per channel and per sender before any work item exists. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:60`](../../../boltrig/kernel/channel_routes.py) `INBOUND_RL_PER_CHANNEL = RateLimit(per="minute", max=120, scope="verb")` | SEC-67 |
| BT-REQ-1729 | A configured thread ceiling narrows the resolved principal at intake. | IMPLEMENTED | [`boltrig/kernel/channel_inbound_routes.py:161`](../../../boltrig/kernel/channel_inbound_routes.py) `"principal = replace(principal, grants=principal.grants.intersect(ceiling))"` | SEC-195 |
| BT-REQ-1730 | Malformed thread-ceiling policy data yields an empty grant set, never a wildcard. | IMPLEMENTED | [`boltrig/kernel/channel_policy.py:70`](../../../boltrig/kernel/channel_policy.py) `"return GrantSet.of([])"` | SEC-195 |
| BT-REQ-1731 | Both intake ceilings are re-intersected at execution so a later item edit cannot widen authority. | IMPLEMENTED | [`boltrig/fleet/authority.py:107`](../../../boltrig/fleet/authority.py) `"for ceiling in (ceiling_from_item(item), creator_ceiling_from_item(item)):"` | SEC-195 |
| BT-REQ-1732 | Channel addressing resolves one target in a fixed order and parks unassigned when nothing matches. | IMPLEMENTED | [`boltrig/kernel/channel_addressing_runtime.py:9`](../../../boltrig/kernel/channel_addressing_runtime.py) `UNASSIGNED_TARGET = "system:unassigned"` | SEC-178 |
| BT-REQ-1733 | A per-message target is taken from the signed body after a slug shape check only. | IMPLEMENTED | [`boltrig/kernel/channel_addressing_runtime.py:34`](../../../boltrig/kernel/channel_addressing_runtime.py) `target = _clean_target(body.get("target"))` | SEC-178 |
| BT-REQ-1734 | Authored channel addressing targets are validated against a caller-scoped catalogue. | IMPLEMENTED | [`boltrig/config/channel_addressing.py:191`](../../../boltrig/config/channel_addressing.py) `"async def validate_channel_addressing_config("` | SEC-178 |
| BT-REQ-1735 | A workflow target is honoured before agent routing and an unknown workflow parks for a human. | IMPLEMENTED | [`boltrig/fleet/pump.py:354`](../../../boltrig/fleet/pump.py) `"Honor a"` | SEC-178 |
| BT-REQ-1736 | A bound sender can answer a pending HITL request from the channel under the API's own eligibility. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:172`](../../../boltrig/kernel/channel_routes.py) `"async def _hitl_reply_response("` | SEC-179 |
| BT-REQ-1737 | A plain channel reply answers only a sole pending QUESTION addressed to that sender in that thread. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:192`](../../../boltrig/kernel/channel_routes.py) `"if req is None or req.type != HITLType.QUESTION:"` | SEC-179 |
| BT-REQ-1738 | A secure question can never be answered from a channel reply. | IMPLEMENTED | [`boltrig/kernel/channel_routes.py:208`](../../../boltrig/kernel/channel_routes.py) `"status": "denied", "reason": "secure questions use secure input"},` | SEC-181 |
| BT-REQ-1739 | Every accepted channel work item carries a kernel-authored provenance stamp that replaces any caller value. | IMPLEMENTED | [`boltrig/work/channel_provenance.py:64`](../../../boltrig/work/channel_provenance.py) `"item.constraints.pop(CHANNEL_MESSAGE_PROVENANCE_KEY, None)"` | CHAN-PROV-01 |
| BT-REQ-1740 | The public provenance projection omits every raw provider identifier. | IMPLEMENTED | [`boltrig/work/channel_provenance.py:96`](../../../boltrig/work/channel_provenance.py) `"Return the safe UI/API projection; never expose raw provider identities."` | CHAN-PROV-01 |
| BT-REQ-1741 | channel.send is a high-consequence verb dispatched through the ordinary chokepoint. | IMPLEMENTED | [`boltrig/adapters/builtin/channel_send.py:190`](../../../boltrig/adapters/builtin/channel_send.py) `consequence="high",  # outbound: HITL by default (SEC-39)` | SEC-39 |
| BT-REQ-1742 | The approver-only comment parameter never reaches the deliver seam. | IMPLEMENTED | [`boltrig/adapters/builtin/channel_send.py:209`](../../../boltrig/adapters/builtin/channel_send.py) `delivery = await self._deliver(ch, params["text"], params.get("target"))` | SEC-39 |
| BT-REQ-1743 | The webhook-class outbound leg is IP-pinned and bound by the manifest network posture. | IMPLEMENTED | [`boltrig/adapters/builtin/channel_send.py:95`](../../../boltrig/adapters/builtin/channel_send.py) `"# SSRF (H2/SEC-61): pin the connection to the vetted IP so httpx cannot"` | SEC-61 |
| BT-REQ-1744 | A socket-class send enqueues one durable outbox row whose payload carries no credential. | IMPLEMENTED | [`boltrig/adapters/builtin/channel_send.py:113`](../../../boltrig/adapters/builtin/channel_send.py) `"message = ChannelOutboxMessage("` | SEC-176 |
| BT-REQ-1745 | A webhook channel with no outbound_url returns queued with no consumer at all. | IMPLEMENTED-UNTESTED | [`boltrig/adapters/builtin/channel_send.py:119`](../../../boltrig/adapters/builtin/channel_send.py) `return {"status": "queued", "transport": channel.transport}` | - |
| BT-REQ-1746 | Outbox claim is an atomic single-winner leased batch taken oldest first. | IMPLEMENTED | [`boltrig/store/channel_outbox.py:220`](../../../boltrig/store/channel_outbox.py) `"ORDER BY created_at LIMIT $5 FOR UPDATE SKIP LOCKED"` | SEC-176 |
| BT-REQ-1747 | Outbox ack and fail are compare-and-swapped on the live lease owner. | IMPLEMENTED | [`boltrig/store/channel_outbox.py:234`](../../../boltrig/store/channel_outbox.py) `"AND lease_owner=$3 RETURNING id"` | SEC-176 |
| BT-REQ-1748 | A failed delivery retries behind exponential backoff and terminates at the attempt cap. | IMPLEMENTED | [`boltrig/store/channel_outbox.py:247`](../../../boltrig/store/channel_outbox.py) `"SET status = CASE WHEN attempts >= $5 THEN 'failed' ELSE 'pending' END,"` | SEC-176 |
| BT-REQ-1749 | A terminal failed delivery is requeued only through an approval-bound verb against an exact snapshot. | IMPLEMENTED | [`boltrig/config/control_channel_approval.py:98`](../../../boltrig/config/control_channel_approval.py) `"if not expected_updated_at or expected_updated_at != observed_updated_at:"` | - |
| BT-REQ-1750 | Delivery receipts carry metadata only and never payload, lease state or provider error text. | IMPLEMENTED | [`boltrig/config/control_channel_approval.py:14`](../../../boltrig/config/control_channel_approval.py) `"Public metadata-only delivery receipt; payload/lease data never enters."` | - |
| BT-REQ-1751 | A run-completion notice returns to the originating channel thread. | IMPLEMENTED | [`boltrig/kernel/channel_notify.py:113`](../../../boltrig/kernel/channel_notify.py) `target = source_route.get("thread")  # reply in the origin thread` | SEC-179 |
| BT-REQ-1752 | A notification is delivered only to a socket channel on which the recipient holds a binding. | IMPLEMENTED | [`boltrig/kernel/channel_notify.py:108`](../../../boltrig/kernel/channel_notify.py) `"binding = next((b for b in bindings if b.subject == member), None)"` | SEC-179 |
| BT-REQ-1753 | A team-scoped notification preference names a department and reaches active members only. | IMPLEMENTED | [`boltrig/kernel/channel_notify.py:66`](../../../boltrig/kernel/channel_notify.py) `if user.status == "active" and pref.scope_ref in departments:` | SEC-179 |
| BT-REQ-1754 | A gateway session token is author-minted, socket-channel-bounded and carries an empty grant set. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_session_routes.py:51`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"GrantSet(),"` | SEC-177 |
| BT-REQ-1755 | Every gateway link is authenticated by the run-token header plus an explicit channel_gateway marker. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_auth.py:16`](../../../boltrig/kernel/channel_gateway_auth.py) `if token is None or not (token.extra or {}).get("channel_gateway"):` | SEC-177 |
| BT-REQ-1756 | Exactly one gateway owns a channel, elected by a 45 second durable lease. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_specs.py:11`](../../../boltrig/kernel/channel_gateway_specs.py) `"GATEWAY_OWNER_LEASE_SECONDS = 45"` | SEC-177 |
| BT-REQ-1757 | Only the elected owner receives resolved provider credentials; a standby receives metadata only. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_reconcile_routes.py:38`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `"if lease is None:"` | SEC-177 |
| BT-REQ-1758 | A partially resolvable credential bundle yields needs_action rather than a partial spec. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/channel_gateway_specs.py:85`](../../../boltrig/kernel/channel_gateway_specs.py) `"if any(not values.get(key) for key in provider.credential_keys):"` | SEC-177 |
| BT-REQ-1759 | The desired-state revision handed to a gateway is a secret-free sha256 digest. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_specs.py:54`](../../../boltrig/kernel/channel_gateway_specs.py) `return hashlib.sha256(canonical.encode("utf-8")).hexdigest()` | SEC-177 |
| BT-REQ-1760 | Heartbeat observations are shape-validated and then fenced on the lease. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_reconcile_routes.py:113`](../../../boltrig/kernel/channel_gateway_reconcile_routes.py) `return "fenced"` | SEC-177 |
| BT-REQ-1761 | Outbox claims are restricted to enabled socket channels this token still owns. | IMPLEMENTED | [`boltrig/kernel/channel_gateway_outbox_routes.py:39`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"active_channels = await _owned_channels(kernel, token, lease)"` | SEC-177 |
| BT-REQ-1762 | The owner lease id is never projected to a browser. | IMPLEMENTED | [`boltrig/kernel/channel_inventory_routes.py:136`](../../../boltrig/kernel/channel_inventory_routes.py) `"owner_lease_id_disclosed": False,` | SEC-177 |
| BT-REQ-1763 | An owner lease is explicitly not a claim of process liveness or provider certification. | IMPLEMENTED | [`boltrig/kernel/channel_inventory_routes.py:137`](../../../boltrig/kernel/channel_inventory_routes.py) `"\"proves_process_liveness\": False,"` | SEC-177 |
| BT-REQ-1764 | A static channel snapshot is refused in a production posture. | IMPLEMENTED | [`services/channel_gateway/app.py:700`](../../../services/channel_gateway/app.py) `"static channel specs are disabled in production; use kernel "` | SEC-177 |
| BT-REQ-1765 | A rotated token file is hot-loaded only after an authorization refusal and only when the value changed. | IMPLEMENTED | [`services/channel_gateway/kernel_client.py:85`](../../../services/channel_gateway/kernel_client.py) `"def set_token(self, token: str) -> bool:"` | SEC-177 |
| BT-REQ-1766 | Gateway readiness is distinct from liveness and requires token, reconciliation and adapter convergence. | IMPLEMENTED | [`services/channel_gateway/app.py:765`](../../../services/channel_gateway/app.py) `"converged = all(channel_id in daemon._adapters for channel_id in daemon._specs)"` | SEC-177 |
| BT-REQ-1767 | The gateway egress guard refuses link-local and metadata addresses even for an allow-listed host. | IMPLEMENTED-UNTESTED | [`services/channel_gateway/egress.py:35`](../../../services/channel_gateway/egress.py) `"return addr.is_link_local or addr.is_unspecified"` | - |
| BT-REQ-1768 | Each port emits a complete deliver target as its thread value, used verbatim as the outbound target. | IMPLEMENTED | [`services/channel_gateway/slack_adapter.py:236`](../../../services/channel_gateway/slack_adapter.py) `reply_target = f"{channel}:{thread_ts}" if thread_ts else channel` | CHAN-PROV-01 |
| BT-REQ-1769 | An intake POST that fails at the transport level is logged and the inbound message is dropped. | IMPLEMENTED-UNTESTED | [`services/channel_gateway/app.py:272`](../../../services/channel_gateway/app.py) `"except KernelLinkError as exc:"` | - |
| BT-REQ-1770 | The generic adapter accepts any peer that can open its TCP listener; the seam has no authentication. | IMPLEMENTED | [`services/channel_gateway/adapters.py:98`](../../../services/channel_gateway/adapters.py) `"self._server = await asyncio.start_server(self._handle_peer, self._host, self._port)"` | - |
| BT-REQ-1771 | The WhatsApp adapter's inbound listener accepts any caller that can reach it. | IMPLEMENTED | [`services/channel_gateway/whatsapp_adapter.py:136`](../../../services/channel_gateway/whatsapp_adapter.py) `listener.post("/inbound")(self._handle_inbound)` | - |
| BT-REQ-1772 | The WhatsApp bridge gates its send endpoint on a Host header only, not on authentication. | IMPLEMENTED | [`services/channel_gateway/whatsapp_bridge/bridge.js:309`](../../../services/channel_gateway/whatsapp_bridge/bridge.js) `"error: 'Invalid Host header. Bridge accepts loopback hosts only.',"` | - |
| BT-REQ-1773 | Every shipped socket port treats its authenticated platform transport as the verification boundary and implements no per-request signature check. | IMPLEMENTED | [`services/channel_gateway/slack_adapter.py:12`](../../../services/channel_gateway/slack_adapter.py) `"The verification boundary (condition 4, an honest statement): this port is"` | - |
| BT-REQ-1774 | Slack v0 and Discord Ed25519 request verification are supplied by the platform's authenticated socket handshake rather than implemented in this tree. | SEAM | [`docs/decisions/0003-channel-gateway-ruling.md:90`](../../../docs/decisions/0003-channel-gateway-ruling.md) `"Remaining follow-ons: native media, team scopes beyond departments, live-platform"` | - |
| BT-REQ-1775 | A realtime voice session's tool list is built only from kernel tools/list over the run-scoped token. | IMPLEMENTED | [`services/channel_gateway/xai_voice_adapter.py:465`](../../../services/channel_gateway/xai_voice_adapter.py) `"async def _discover_tools(self) -> list[dict[str, Any]]:"` | SEC-183 |
| BT-REQ-1776 | A config-supplied tool list is rejected at voice adapter init before any socket opens. | IMPLEMENTED | [`services/channel_gateway/xai_voice_adapter.py:130`](../../../services/channel_gateway/xai_voice_adapter.py) `"def _reject_config_tools(config: dict[str, Any]) -> None:"` | SEC-183 |
| BT-REQ-1777 | Every provider function call is dispatched back through the kernel MCP face. | IMPLEMENTED | [`services/channel_gateway/xai_voice_adapter.py:761`](../../../services/channel_gateway/xai_voice_adapter.py) `"response = await self._kernel.mcp_call("` | SEC-26 |
| BT-REQ-1778 | A browser media bearer is single-use, 90 second TTL and stored only as a digest. | IMPLEMENTED | [`boltrig/kernel/call_route_support.py:19`](../../../boltrig/kernel/call_route_support.py) `"MEDIA_TOKEN_TTL_SECONDS = 90"` | SEC-WRK-03 |
| BT-REQ-1779 | Media redemption requires the gateway token's channel scope and the live owner lease before the bearer is compared. | IMPLEMENTED | [`boltrig/kernel/call_gateway_routes.py:96`](../../../boltrig/kernel/call_gateway_routes.py) `"if not await _owns_call_channel(kernel, gateway, pending_call):"` | SEC-WRK-03 |
| BT-REQ-1780 | Redemption mints a separate short-lived MCP token from the call owner's stored grant snapshot. | IMPLEMENTED | [`boltrig/kernel/call_gateway_routes.py:109`](../../../boltrig/kernel/call_gateway_routes.py) `"tool_token = kernel.mcp.issue_run_token("` | SEC-WRK-03 |
| BT-REQ-1781 | A call's tool context is the caller's permitted verbs snapshotted at creation. | IMPLEMENTED | [`boltrig/kernel/call_routes.py:59`](../../../boltrig/kernel/call_routes.py) `"concrete = canonical_concrete_verbs(tuple("` | SEC-WRK-03 |
| BT-REQ-1782 | Gateway-authored call events are filtered to an allowlist of type and field before storage. | IMPLEMENTED | [`boltrig/kernel/call_route_support.py:70`](../../../boltrig/kernel/call_route_support.py) `"Allow normalized text/metadata only; discard every media-shaped field."` | SEC-WRK-03 |
| BT-REQ-1783 | Raw microphone and synthesized audio never enter the call event store. | IMPLEMENTED | [`boltrig/models/realtime_calls.py:4`](../../../boltrig/models/realtime_calls.py) `"Boltrig persists the call lifecycle, transcript text, tool/HITL event metadata,"` | SEC-WRK-03 |
| BT-REQ-1784 | A final call transcript is projected once into the conversation under a deterministic id. | IMPLEMENTED | [`boltrig/kernel/call_transcript.py:11`](../../../boltrig/kernel/call_transcript.py) `"async def project_call_transcript(kernel, call, event) -> None:"` | SEC-WRK-03 |
| BT-REQ-1785 | Typed mid-call text is bounded by a durable, reconnect-stable per-call budget that fails closed. | IMPLEMENTED | [`boltrig/kernel/call_gateway_routes.py:66`](../../../boltrig/kernel/call_gateway_routes.py) `"if len(events) >= _TYPED_TEXT_HISTORY_LIMIT:"` | SEC-WRK-03 |
| BT-REQ-1786 | Concurrent browser calls are isolated per call id and bounded by a pool that refuses rather than evicts. | IMPLEMENTED | [`services/channel_gateway/app.py:508`](../../../services/channel_gateway/app.py) `raise BrowserMediaCapacityError("browser voice capacity reached")` | SEC-WRK-03 |
| BT-REQ-1787 | A voice approval parks the exact provider call and only a normalized resolution is projected back. | IMPLEMENTED | [`boltrig/kernel/realtime_call_bridge.py:18`](../../../boltrig/kernel/realtime_call_bridge.py) `"async def project_realtime_hitl_outcome("` | SEC-WRK-04 |
| BT-REQ-1788 | The realtime HITL projection is best-effort and can never change the resumed action. | IMPLEMENTED | [`boltrig/kernel/realtime_call_bridge.py:29`](../../../boltrig/kernel/realtime_call_bridge.py) `log.warning("realtime held-call projection failed", exc_info=True)` | SEC-WRK-04 |
| BT-REQ-1789 | Missing voice configuration returns a typed realtime_unavailable call plus the text conversation. | IMPLEMENTED | [`boltrig/kernel/call_routes.py:125`](../../../boltrig/kernel/call_routes.py) `status="realtime_unavailable",` | SEC-WRK-03 |
| BT-REQ-1790 | Reconnect rotates the spent media bearer rather than reusing it. | IMPLEMENTED | [`boltrig/kernel/call_routes.py:217`](../../../boltrig/kernel/call_routes.py) `"token, token_hash, expires_at = mint_media_token()"` | SEC-WRK-03 |
| BT-REQ-1791 | Call reads are owner-scoped and answer not_found rather than denied for another owner. | IMPLEMENTED | [`boltrig/kernel/call_routes.py:30`](../../../boltrig/kernel/call_routes.py) `"async def _owned_call(kernel, principal, call_id: str):"` | SEC-WRK-03 |
| BT-REQ-1792 | Conversation close, restore, rename and project move are owner-scoped. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/conversation_account_routes.py:17`](../../../boltrig/kernel/conversation_account_routes.py) `{"status": "denied", "reason": "not your conversation"}, status_code=403` | - |
| BT-REQ-1793 | The channels table is deliberately outside the RLS fence because the inbound path resolves it before a tenant is bound. | IMPLEMENTED | [`boltrig/store/rls.sql:64`](../../../boltrig/store/rls.sql) `"channels table is EXCLUDED for the same reason (decision 0003): the inbound"` | SEC-08 |
| BT-REQ-1794 | Every other channel and call table is inside the tenant fence. | IMPLEMENTED | [`boltrig/store/rls.sql:120`](../../../boltrig/store/rls.sql) `"'channel_deliveries','channel_outbox',"` | SEC-08 |
| BT-REQ-1795 | The channel gateway, signal-cli and whatsapp-bridge services are profile-gated and inert by default. | IMPLEMENTED | [`docker-compose.yml:584`](../../../docker-compose.yml) `profiles: ["channels"]` | - |
| BT-REQ-1796 | The Worker edge proxies the entire gateway prefix, not only the media WebSocket. | IMPLEMENTED | [`apps/worker/nginx.conf:67`](../../../apps/worker/nginx.conf) `"location /voice/ {"` | - |
| BT-REQ-1797 | The gateway status endpoint exposes channel ids, adapters and observations without authentication. | IMPLEMENTED | [`services/channel_gateway/app.py:869`](../../../services/channel_gateway/app.py) `"\"channels\": sorted(daemon._specs),"` | - |
| BT-REQ-1798 | A gateway session token cannot be revoked by any kernel route; only its TTL and lease bound it. | SCAFFOLDED | [`boltrig/kernel/mcp.py:130`](../../../boltrig/kernel/mcp.py) `"def revoke(self, token: str) -> None:"` | SEC-177 |
| BT-REQ-1799 | The MCP run-token registry is process-local, so a restart invalidates every gateway session. | IMPLEMENTED | [`boltrig/kernel/mcp.py:79`](../../../boltrig/kernel/mcp.py) `"self._tokens: dict[str, RunToken] = {}"` | SEC-23 |
