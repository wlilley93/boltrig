# Communications gateway and agent roster exposure plan

- Status: proposed
- Date: 2026-07-04
- Related decisions: [0003 channel gateway](../decisions/0003-channel-gateway-ruling.md), [0009 host-agent communications gateway](../decisions/0009-host-agent-communications-gateway.md), [0010 Opbox generalisation and automation ownership](../decisions/0010-opbox-generalisation-and-automation-engine-ownership.md)
- Related proposal: [Opbox pinned Boltrig runtime migration](./opbox-pinned-boltrig-agent-runtime.md)

## Short ruling

Yes: communications exposure should become a first-class part of the agent roster
profile so an admin can answer "where can this agent be contacted?" in one place.

No: the agent profile must not become the channel credential store or the webhook
auth authority. Channel connections, signing secrets, external sender bindings,
delivery state, and platform verification stay in governed channel resources and
the communications gateway. The roster profile references those resources and
sets exposure, routing, and policy.

The target product model is:

```text
tenant channel resource       = how Boltrig connects to a platform
channel binding               = which external sender maps to which principal
host-agent facade             = how chat/API clients talk to a pinned runtime
agent roster/profile exposure = where an agent is reachable and what it may do
notification preference       = how humans receive approval/status messages
workflow trigger              = how automation starts, not a chat identity
```

## Why this matters

The Opbox migration surfaced a gap in Boltrig's product shape. Boltrig has a
kernel channel-gateway design and a Channels admin page, but setup is still
connection-first. Operators will expect the inverse question to work too: choose
an agent and expose it safely to Boltrig chat, Opbox chat, OpenAI-compatible
clients, Slack, Teams, email, webhooks, SMS, voice, and future channels.

This plan makes communications setup obvious without creating a second gateway
or a second permission system.

## Current baseline

Boltrig already has these pieces:

- Native site chat through `POST /v1/chat` with SSE events.
- Run event replay through `GET /v1/runs/{id}/events`.
- A Channels panel that lists, connects, configures, disconnects, pairs, and
  binds webhook/request-response channels through `/v1/channels*`.
- A channel-gateway decision that splits transports into in-kernel
  webhook/request-response routes and persistent sidecars.
- `channel.send` as a governed high-consequence verb.
- Settings surfaces for user notifications and personal agents.
- An Agents row with agent profile slides and governed capability edits.
- An Admin manifest config editor, including `notifications` and
  `personal_agents` sections.

The gaps are:

- No explicit agent-profile "Comms" or "Exposure" section.
- No durable surface registry that says "this chat thread/webhook/mailbox/socket
  is owned by this gateway".
- No per-agent list of reachable channels or client surfaces.
- No first-class "gateway of record" mode in the UI or schema.
- No setup wizard that combines channel creation, sender binding, agent exposure,
  HITL delivery, and test messages.
- No profile-bound routing for native site chat or OpenAI-compatible clients.
- No channel trigger wiring from workflow canvas trigger nodes to real channels.
- No persistent channel sidecar framework for Slack Socket Mode, Discord,
  WhatsApp/Baileys, Signal, Telegram long-poll, or mailbox pollers.
- No channel delivery receipts/dead-letter view in the console.
- No complete compatibility facade for Opbox/Hermes-style AG-UI and `/v1`
  clients in Boltrig.

## Product principle

Set up channels once; expose agents many times.

A tenant may connect a platform channel such as Slack, MS Teams, email, SMS, or a
generic webhook once. Each agent profile then decides whether it is reachable on
that channel, how inbound messages route, what verbs the conversation can use,
what approval path applies, and what outbound messages are allowed.

This avoids two common failure modes:

- A channel-level secret duplicated across several agent records.
- An agent profile that bypasses the kernel's channel identity, grants, HITL,
  audit, idempotency, or rate limits.

## Responsibility split

| Layer | Owns | Must not own |
|---|---|---|
| Channel resource | Platform, transport class, enabled flag, config, credential refs, signing secret refs, inbound URL, outbound endpoint metadata | Agent prompt, model choice, business grants |
| Channel binding | External sender id, tenant-scoped principal, role tier, pairing state | Runtime authority beyond the mapped principal |
| Host-agent facade | Chat/API protocol compatibility, stream translation, request normalization, client backpressure, approval continuation | Provider routing, business auth, channel identity policy |
| Agent roster profile | Exposure policy, default route, allowed surfaces, allowed skills/verbs, inbound and outbound policy references | Secrets, platform webhook verification, retry queue ownership |
| Notification preferences | Human delivery preferences for approvals/status/error/budget events | External sender authentication or agent reachability |
| Workflow trigger | Automation entrypoint and workflow state transition | Conversation identity or chat thread ownership |
| Kernel | Grants, HITL, audit, budgets, idempotency checks, credential resolution, adapter dispatch | Long-lived platform SDK socket loops |
| Pi runtime | Reasoning/tool loop under granted verbs | Gateway auth, channel sessions, billing authority, direct DB writes |
| Bifrost/model gateway | Model/provider routing and cache policy | User auth, channel ingress, omnichannel routing |

## Channel inventory

The inventory below is intentionally wider than the first migration. Each row
states where it should land so future work does not reopen the gateway question.

| Surface or channel | Transport class | Gateway of record | Agent exposure shape | Phase |
|---|---|---|---|---|
| Boltrig site chat | Native site/API SSE | Boltrig native chat or host-agent facade | Profile lists `boltrig_site_chat` as an enabled surface | C2 |
| Opbox frontend chat | Host chat facade behind Opbox proxy | Boltrig host-agent facade during migration | Profile lists `opbox_chat` with Opbox auth bridge | C3 |
| OpenAI-compatible clients | HTTP request/stream | Boltrig host-agent facade or legacy gateway until cutover | Profile lists `openai_compat` and supported models/agents | C3 |
| AG-UI clients | HTTP SSE/event protocol | Boltrig host-agent facade | Profile lists `ag_ui` and event mapping | C3 |
| Generic signed webhook | Webhook/request-response | Kernel channel gateway | Channel ref plus inbound route policy | C4 |
| MS Teams webhook/MS Graph | Webhook/request-response | Kernel channel gateway | Channel ref, binding strategy, card/render policy | C4 |
| Slack Events API | Webhook/request-response | Kernel channel gateway | Channel ref, signing secret, thread binding policy | C4 |
| Slack Socket Mode | Persistent socket | Supervised channel sidecar | Channel ref, sidecar health, same profile policy | C5 |
| Discord gateway | Persistent socket | Supervised channel sidecar | Channel ref, guild/channel routing policy | C5 |
| Discord interactions webhook | Webhook/request-response | Kernel channel gateway | Channel ref, interaction response policy | C4 or C5 |
| Telegram webhook mode | Webhook/request-response | Kernel channel gateway | Channel ref, chat-id binding policy | C4 |
| Telegram long-poll | Persistent poller | Supervised channel sidecar | Channel ref, poller health, same profile policy | C5 |
| Email via MS Graph/Gmail webhook | Webhook/request-response where available | Kernel channel gateway | Mailbox/channel ref, sender binding, attachment policy | C4 |
| Email via IMAP/POP poller | Persistent poller | Supervised channel sidecar | Mailbox ref, dedupe and reply-thread policy | C5 |
| Outbound SMTP/email | Outbound adapter/`channel.send` | Kernel adapter through channel gateway | Outbound policy and HITL default | C4 |
| SMS via Twilio-style webhook | Webhook/request-response | Kernel channel gateway | Phone-number ref, sender binding, short-message policy | C4 |
| WhatsApp Cloud API webhook | Webhook/request-response | Kernel channel gateway | Business-account ref, template/send policy | C4 |
| WhatsApp/Baileys | Persistent connection | Supervised channel sidecar | Channel ref, device/session health | C5 |
| Signal | Persistent connection | Supervised channel sidecar | Channel ref, account/session health | C5 |
| Voice call webhooks | Webhook/request-response plus media session | Kernel route for control events; sidecar for realtime media | Phone-number ref, transcript and approval policy | C5 or later |
| Browser push | Outbound notification surface | Notification service/channel gateway | Human notification preference, not agent inbound by default | C6 |
| In-app notifications | Native Boltrig notifications | Boltrig kernel/UI | Human notification preference, not external channel | C6 |
| Pager/PagerDuty-style alerting | Outbound webhook/API | Kernel adapter/`channel.send` | Escalation policy only unless inbound is enabled | C6 |
| GitHub/Stripe/product webhooks | Webhook/request-response | Kernel channel gateway | Usually workflow trigger, not chat, unless explicitly routed | C4 |
| MCP clients | Developer/API surface | Kernel MCP server | Not a communications channel; profile affects granted tools only | Existing |

## Agent roster profile model

The roster profile gets a `comms` or `exposure` section. The exact name can be
settled during implementation; the important contract is that it references
channels and surfaces instead of embedding secrets.

Example profile shape:

```yaml
agents:
  - name: front-desk
    kind: worker
    runtime: pi-worker
    skills:
      - support_triage
      - document_lookup
    comms:
      enabled: true
      default_surface: boltrig_site_chat
      surfaces:
        - id: boltrig_site_chat
          kind: chat.api
          mode: owning
          inbound:
            route: chat.default
            allowed_intents: ["ask", "search", "draft"]
            max_attachments: 5
          outbound:
            allow_agent_initiated: false
            approval_required: true
        - id: opbox_chat
          kind: host_facade
          mode: shadow
          host: opbox
          inbound:
            route: opbox.host_agent
            preserve_thread_state: host
        - id: teams-front-desk
          kind: channel
          channel_id: ch_teams_front_desk
          mode: canary
          inbound:
            binding_required: true
            unpaired_behavior: reject
            default_principal_policy: mapped_sender
            allowed_intents: ["ask", "approve", "status"]
          outbound:
            delivery: channel.send
            approval_required: true
            quiet_hours: "user_preferences"
      hitl:
        approval_channel: user_preferences
        escalation_channel: teams-front-desk
      policy:
        gateway_of_record_required: true
        dedupe_window_seconds: 900
        attachment_policy: standard
        retention_policy: tenant_default
```

## Data model additions

Use this shape as a planning target; names can change during implementation.

### `communication_surfaces`

Tenant-scoped registry of reachable surfaces.

Fields:

- `id`
- `tenant_id`
- `kind`: `site_chat`, `host_facade`, `openai_compat`, `ag_ui`, `channel`
- `channel_id`: nullable, set for true external channels
- `host`: nullable, for Opbox or future host apps
- `transport_class`: `native`, `http_stream`, `webhook`, `persistent`,
  `outbound_only`
- `gateway_of_record`: service identifier such as `boltrig-host-agent`,
  `boltrig-kernel`, `channel-sidecar-slack`, or `legacy-hermes`
- `mode`: `off`, `shadow`, `canary`, `owning`, `rollback`
- `status`: `draft`, `ready`, `degraded`, `disabled`
- `config`: non-secret metadata
- `created_by`, `updated_by`, `created_at`, `updated_at`

### `agent_exposures`

Maps an agent profile to a surface.

Fields:

- `id`
- `tenant_id`
- `agent_profile_name`
- `surface_id`
- `mode`: `off`, `shadow`, `canary`, `owning`
- `inbound_policy`
- `outbound_policy`
- `hitl_policy`
- `rendering_policy`
- `rate_limit_policy`
- `retention_policy`
- `created_by`, `updated_by`, `created_at`, `updated_at`

### `surface_ownership_locks`

Prevents double-owning migration mistakes.

Fields:

- `surface_id`
- `ownership_key`: thread id, webhook subscription id, socket workspace id,
  mailbox id, phone number, OpenAI client route, or channel binding id
- `owner_gateway`
- `mode`: `shadow`, `canary`, `owning`
- `lease_expires_at`: nullable for static ownership
- `last_seen_at`

### `channel_delivery_events`

Operational log for outbound delivery and dead-letter handling.

Fields:

- `id`
- `tenant_id`
- `surface_id`
- `channel_id`
- `direction`: `inbound`, `outbound`
- `external_message_id`
- `dedupe_key`
- `status`: `accepted`, `queued`, `sent`, `delivered`, `failed`, `dead_letter`
- `attempts`
- `last_error`
- `run_id`
- `audit_seq`
- `created_at`, `updated_at`

## Boltrig site exposure

The site should expose communications setup in four places, each with a distinct
purpose.

### 1. Agents row: profile Comms tab

The per-agent slide should gain a `Comms` or `Exposure` section. This is the
operator's main setup page for "where can this agent be contacted?"

It should show:

- Enabled/disabled exposure state.
- Reachable surfaces grouped as Site, Host/API, External channels, Outbound only.
- Mode badges: off, shadow, canary, owning, rollback.
- Gateway of record for each surface.
- Channel connection health and last inbound/outbound event.
- External sender binding coverage: bound, unpaired, rejected, locked out.
- Allowed intents or routes.
- Allowed skills/verb families after grant intersection.
- HITL approval delivery path.
- Attachment policy.
- Rate limit and budget policy.
- Retention/audit policy.
- Test actions: simulate inbound, send outbound test, approval continuation test.
- Rollback action where a previous gateway still exists.

The profile page should not expose raw secrets. It may link to the Channels page
for channel connection details.

### 2. Ops/Admin Channels page: connection setup

The Channels page remains the place to connect and administer tenant channels.

It should evolve from connection CRUD to channel operations:

- Channel list with platform, transport class, status, enabled, gateway of
  record, last inbound, last outbound, binding count, dead-letter count.
- Connect wizard for webhook/request-response channels.
- Sidecar enrollment wizard for persistent channels once sidecars exist.
- Sender bindings and pairing codes.
- Test inbound payload with signature verification.
- Test outbound `channel.send` with full HITL result rendering.
- Ownership lock display: which gateway owns this webhook/socket/mailbox/phone.
- Delivery receipts, retry queue, dead-letter queue.
- Audit links for `channel.*` mutations and sends.
- Disable, disconnect, and rollback controls.

### 3. Settings: Personal Agent and Notifications

Settings remains user-scoped.

Personal Agent should answer:

- Is my delegated personal agent enabled?
- Which runtime and skills does it use?
- Which personal surfaces may contact it?
- Are its grants capped to me?

Notifications should answer:

- Where should I receive approvals, escalations, status updates, budget alerts,
  and errors?
- Which channels are enabled for my human notifications?

Notifications do not decide which external senders can contact an agent. They are
delivery preferences for humans.

### 4. Chat, Approvals, Automations, Insight

Other site areas need visibility, not ownership:

- Chat should show which agent/profile and surface owns the current conversation.
- Approvals should show the originating surface and channel when a request came
  from Slack/Teams/email/etc.
- Automations should turn visual webhook/channel triggers into real trigger
  bindings when workflow support lands.
- Insight should filter audit, runs, and delivery events by surface, channel,
  gateway, and agent profile.

## Setup wizard

The guided setup should be profile-first but resource-aware.

1. Pick an agent profile.
2. Choose a surface type:
   - Boltrig site chat
   - Host app chat/API, such as Opbox
   - OpenAI-compatible API client
   - Existing external channel
   - New external channel
   - Outbound-only notification/delivery surface
3. If the surface is external, connect or select a channel resource.
4. Verify transport:
   - webhook callback URL reachable
   - signature secret stored
   - platform challenge passed
   - sidecar healthy for persistent channels
5. Decide ownership mode:
   - off
   - shadow, no ack/send/mutate/retry
   - canary, explicit percentage or allowlist
   - owning
   - rollback to previous gateway
6. Configure identity:
   - require existing sender binding
   - allow pairing
   - reject unknown senders
   - direct admin bind
7. Configure inbound route:
   - default agent route
   - explicit intent map
   - workflow trigger route
   - approval-response route
   - status-only route
8. Configure allowed authority:
   - profile skills
   - verb/noun allowlist
   - attachment policy
   - max steps, timeout, budget cap
9. Configure outbound:
   - no agent-initiated outbound
   - reply only
   - explicit sends through `channel.send`
   - approval required
   - quiet hours and escalation
10. Preview exposure graph:
   - surface -> gateway -> channel binding -> principal -> agent profile ->
     runtime -> granted verbs -> audit/HITL
11. Run tests:
   - test inbound with a signed sample
   - test unknown sender behavior
   - test outbound send
   - test approval continuation
   - test dedupe/idempotency
12. Enable canary or owning mode.
13. Monitor delivery events, audit, and run outcomes.

## Modes

Use explicit modes everywhere. Hidden partial migrations are where bugs happen.

| Mode | Inbound | Outbound | State mutation | Use |
|---|---|---|---|---|
| `off` | refused or ignored | none | none | configured but inactive |
| `shadow` | observed only | none | no ack/retry/write | parity testing |
| `canary` | allowlisted or sampled | allowed for canary only | owning for selected traffic | limited rollout |
| `owning` | accepted | allowed by policy | full owner | production |
| `rollback` | route to previous owner | previous owner | previous owner | emergency fallback |

Shadow mode must not ack a production webhook, consume a socket event, send a
message, update thread state, or enqueue retries. It may log parity observations
only.

## Routing rules

Inbound routing must be deterministic before a model sees text.

1. Verify the platform request.
2. Resolve tenant from the trusted channel record or ownership binding.
3. Resolve external sender to a tenant-scoped principal or fail closed.
4. Resolve surface and gateway ownership.
5. Resolve agent exposure policy.
6. Normalize message, attachments, thread, and idempotency key.
7. Intersect profile skills with principal grants and surface policy.
8. Invoke the kernel or host-agent facade.
9. Persist audit and delivery status.

The model cannot choose the tenant, principal, gateway owner, or channel binding.

## Thread and identity model

Every conversational surface needs a thread binding:

- Site chat: Boltrig conversation id.
- Opbox chat: Opbox thread/session id bridged to Boltrig run/conversation id.
- OpenAI-compatible clients: client conversation id where available, otherwise a
  generated stable session key.
- Slack/Teams/Discord: platform thread/channel/message ids.
- Email: message-id, references/in-reply-to, mailbox id, sender.
- SMS/WhatsApp/Signal/Telegram: phone/chat/session id.
- Voice: call sid/session id plus transcript id.
- Webhooks for workflow triggers: external event id plus dedupe key; no chat
  thread unless explicitly routed to a conversation.

Thread bindings are not model memory. They are routing and idempotency state.

## Permissions

Agent exposure never widens authority by itself.

Effective authority is:

```text
verified principal grants
  intersect agent profile skills/verbs
  intersect surface exposure policy
  intersect channel policy
  intersect tenant/org/workspace policy
  subject to HITL, budgets, rate limits, and audit
```

This matters for org and user permissions:

- A Teams sender mapped to a member cannot gain org-admin verbs by messaging an
  org-admin-owned agent.
- A personal agent cannot act beyond its owner's grants.
- An Opbox workspace request must preserve workspace and org membership before
  invoking Boltrig verbs.
- A channel binding role is not a business role unless the kernel maps it to a
  principal with corresponding grants.
- Approval responses must verify the responder is allowed to approve that HITL
  request, not merely that they are reachable on the same channel.

## Automations

Communications and automations overlap but are not the same engine.

- A channel message can start a workflow only through an explicit trigger route.
- A workflow can send a message only through a governed verb such as
  `channel.send`.
- Agent-backed workflow steps can use the pinned Boltrig runtime without moving
  workflow state to Boltrig.
- Do not run two automation engines for the same workflow domain.
- If Boltrig later becomes the automation engine for a domain, migrate that
  domain as a separate engine/state migration.

Workflow trigger nodes should eventually bind to:

- `surface_id`
- `channel_id`
- trigger filters
- dedupe key expression
- mapped principal policy
- target workflow id
- default agent/profile where the workflow delegates

## Opbox migration path

For Opbox, use the product phases from the pinned-runtime proposal:

1. **Phase 1 - Boltrig readiness and comms/profile groundwork.**
   Add `opbox_chat` as a planned host communication surface, model channel and
   agent exposure, harvest prompt/profile fixtures, and define the gateway of
   record. Do not route production Opbox traffic yet.
2. **Phase 2 - Opbox frontend consolidation.**
   Remove `Agents` as a top-level Opbox tab, move agent-backed configuration into
   `Automations`, align Settings, and embed or mirror the relevant Boltrig UI
   inside Opbox. This makes channel exposure, worker profiles, approvals,
   settings, and automation ownership visible before the engine changes.
3. **Phase 3 - engine/kernel cutover.**
   Preserve Opbox browser routes and auth, then repoint selected
   `AGENT_CHAT_URL` traffic to a Boltrig host-agent facade. Keep Hermes/legacy
   gateway available for rollback. Move `opbox_chat` from shadow to canary to
   owning only after golden tasks, permissions, billing, approval continuation,
   and observability pass.

Within Phase 3:

- Preserve or replace `/v1/models` and `/v1/chat/completions` only if live
  clients use them.
- Migrate the drainer/agent-task worker separately from chat.
- Keep Opbox kernel and workflow automation ownership intact unless a later
  separate engine migration is explicitly ordered.
- Defer true Slack/Teams/email/SMS/voice migration unless production Opbox
  traffic currently depends on those channels.

## Hermes and Pi answer

Use Pi/Boltrig for runtime execution. Use the Boltrig host-agent facade for
chat/API compatibility. Use the 0003 channel gateway pattern for true external
channels. Keep Hermes only as a legacy rollback path or a reference for gateway
behavior.

Hermes having a built/tested gateway does not make it the target engine. It makes
it a useful parity source and rollback layer while Boltrig grows the reusable
surface and profile model.

## Phasing

These `C` milestones are communications capability milestones, not the Opbox
product phases. For Opbox, C0-C2 mostly support Product Phase 1 and Phase 2; C3
is used during Product Phase 3 engine cutover; C4-C7 are later omnichannel
expansion unless a live Opbox channel already depends on them.

### C0 - Inventory and ownership map

Deliverables:

- List every live chat/API/channel surface per tenant/host.
- Record current gateway owner, rollback route, auth method, and retry owner.
- Identify all webhook subscriptions, socket apps, mailboxes, phone numbers, and
  OpenAI-compatible client routes.
- Add an initial `surface_id` naming convention.

Exit gate:

- No migration starts without an ownership row for the surface being migrated.

### C1 - Surface registry and profile schema

Deliverables:

- Add typed schema for communication surfaces and agent exposures.
- Add validation that one surface cannot have two owning gateways.
- Add profile fixture examples.
- Add admin export/import support for non-secret exposure config.

Exit gate:

- The registry can represent site chat, Opbox chat, OpenAI-compatible clients,
  and at least one external channel without storing secrets in profile config.

### C2 - Boltrig site exposure

Deliverables:

- Add Comms/Exposure section to agent profile slide.
- Show site chat as a built-in surface.
- Show current runtime, profile skills, effective authority, and HITL path.
- Add profile-bound chat selection or route metadata.
- Show surface owner on chat conversations.

Exit gate:

- An admin can see whether an agent is reachable from Boltrig site chat and what
  authority that conversation has.

### C3 - Host-agent facade and Opbox chat/API

Deliverables:

- Implement or formalize `boltrig-host-agent` facade.
- Support Opbox `AGENT_CHAT_URL` contract.
- Support approval continuation.
- Support fixture-tested stream mapping.
- Optionally support `/v1/models` and `/v1/chat/completions`.
- Add `opbox_chat`, `ag_ui`, and `openai_compat` surfaces.

Exit gate:

- Opbox chat golden tasks pass in shadow/canary, and rollback is a routing flip.

### C4 - Request-response external channels

Deliverables:

- Productize generic signed webhook.
- Productize MS Teams/MS Graph webhook where needed.
- Add Slack Events API adapter if Slack webhook mode is selected.
- Add Telegram webhook mode if selected.
- Add Twilio/SMS webhook mode if selected.
- Add email webhook modes where available.
- Add channel test send, test inbound, delivery events, and dead-letter UI.

Exit gate:

- Each channel has platform verification, sender mapping, dedupe, HITL, outbound
  idempotency, audit, and rollback documented.

### C5 - Persistent channel sidecars

Deliverables:

- Sidecar framework with health, leases, backoff, replay cursor, and run-scoped
  kernel re-entry.
- Slack Socket Mode sidecar if Slack requires it.
- Discord gateway sidecar if Discord is in scope.
- Telegram long-poll sidecar if webhook mode is unavailable.
- WhatsApp/Baileys and Signal only after security review.
- Mailbox poller only if webhook mail is insufficient.

Exit gate:

- Sidecar cannot hold policy, direct credentials beyond injected channel secrets,
  or bypass kernel grants/audit.

### C6 - Omnichannel HITL and notifications

Deliverables:

- Unified approval delivery policy.
- Human notification preferences bridged to channel delivery.
- Approval response verification per responder.
- Escalation chain and quiet-hours policy wired.
- Delivery receipts and retries visible in Approvals and Insight.

Exit gate:

- A pending human request has one delivery owner and one approval authority,
  regardless of channel.

### C7 - Hardening and operations

Deliverables:

- Load tests for SSE, webhooks, sidecars, and retry queues.
- Rate limits by tenant, surface, channel, sender, and profile.
- Idempotency tests for duplicate inbound and retry outbound.
- Dead-letter handling and replay tools.
- Support runbook for rollback and incident response.
- Security invariants for tenant isolation, signature verification, replay
  windows, and no double-owning gateway.

Exit gate:

- A channel incident can be contained by disabling a surface without disabling
  the entire agent runtime.

## Release gates per channel

Every channel must pass this checklist before owning production traffic:

- Platform verification implemented at the correct byte/protocol boundary.
- Timestamp/replay protection exists where the platform supports it.
- Tenant is resolved from trusted channel config or verified binding.
- Unknown sender behavior is explicit and tested.
- Pairing codes are hashed, TTL-bound, lockout-guarded, and shown once.
- Inbound event id or dedupe key is stored.
- Outbound idempotency key is stored.
- Attachment limits and content policy are enforced.
- Effective principal grants are visible in audit.
- `channel.send` consequence/HITL behavior is correct.
- Gateway of record is unique.
- Shadow mode cannot ack/send/mutate/retry.
- Canary routing is deterministic and reversible.
- Delivery failure moves to retry or dead-letter with reason.
- Console shows status and rollback route.
- Golden task or channel fixture covers a realistic happy path.
- Negative tests cover bad signature, replay, wrong tenant, unknown sender, and
  duplicate event.

## Test plan

Kernel tests:

- bad signature denied
- stale timestamp denied
- replay denied
- tenant spoof in payload ignored
- sender binding required
- pairing TTL enforced
- pairing lockout enforced
- direct bind tenant isolation
- role/grant intersection enforced
- `channel.send` HITL triggered for high consequence
- outbound idempotency prevents duplicate send
- ownership lock blocks two owning gateways

Facade tests:

- AG-UI stream mapping
- OpenAI-compatible chunk mapping
- client abort closes upstream
- approval continuation resumes correct thread/tool
- auth failure fails closed
- degraded runtime is rendered honestly
- per-conversation model/runtime pinning where applicable

UI tests:

- non-admin cannot administer channels
- profile Comms tab does not display secrets
- external channel links to Channels page
- ownership mode changes require confirmation
- shadow mode warnings are visible
- test inbound renders verification result
- test outbound renders pending human, queued, sent, failed, and dead-letter
- chat shows owning surface/profile
- Approvals shows originating surface/channel

Migration tests:

- Opbox `AGENT_CHAT_URL` can switch old -> new -> old.
- `/v1` clients either pass parity or remain on legacy gateway.
- Drainer migration does not change workflow scheduler ownership.
- No automation trigger points to both old and new owner.
- Rollback does not orphan pending approvals.

## Backlog

- [ ] `COMMS-PROFILE-00`: Inventory every current Opbox/Boltrig chat, API, webhook, socket, mailbox, phone, and notification route.
- [ ] `COMMS-PROFILE-01`: Define `communication_surfaces` schema and migration.
- [ ] `COMMS-PROFILE-02`: Define `agent_exposures` schema and validation.
- [ ] `COMMS-PROFILE-03`: Add ownership lock semantics for surface/channel/client routes.
- [ ] `COMMS-PROFILE-04`: Add profile fixture examples for site chat, Opbox chat, generic webhook, Teams, Slack, email, and SMS.
- [ ] `COMMS-PROFILE-05`: Add manifest export/import support for non-secret surface and exposure config.
- [ ] `COMMS-PROFILE-06`: Add Agents row Comms/Exposure section.
- [ ] `COMMS-PROFILE-07`: Add surface owner/profile metadata to Chat conversations.
- [ ] `COMMS-PROFILE-08`: Extend Channels page with gateway owner, status, last event, delivery events, and dead-letter counters.
- [ ] `COMMS-PROFILE-09`: Add test inbound action to Channels page.
- [ ] `COMMS-PROFILE-10`: Add test outbound `channel.send` action to Channels page.
- [ ] `COMMS-PROFILE-11`: Add channel delivery event store and read API.
- [ ] `COMMS-PROFILE-12`: Add Insight filters for surface, channel, gateway, and agent profile.
- [ ] `COMMS-PROFILE-13`: Add Approvals origin rendering for surface/channel/thread.
- [ ] `COMMS-PROFILE-14`: Add host-agent facade surface records for Opbox chat and optional `/v1` clients.
- [ ] `COMMS-PROFILE-15`: Fixture-test AG-UI, OpenAI-compatible, and approval continuation stream mappings.
- [ ] `COMMS-PROFILE-16`: Add one-gateway-of-record invariant tests.
- [ ] `COMMS-PROFILE-17`: Add shadow-mode no-ack/no-send/no-mutate tests.
- [ ] `COMMS-PROFILE-18`: Productize generic signed webhook setup wizard.
- [ ] `COMMS-PROFILE-19`: Productize Teams/MS Graph request-response channel if selected.
- [ ] `COMMS-PROFILE-20`: Productize Slack Events API channel if selected.
- [ ] `COMMS-PROFILE-21`: Productize email webhook or mailbox-poller channel after channel choice.
- [ ] `COMMS-PROFILE-22`: Productize SMS/Twilio channel after channel choice.
- [ ] `COMMS-PROFILE-23`: Build persistent sidecar framework before Slack Socket/Discord/WhatsApp/Signal.
- [ ] `COMMS-PROFILE-24`: Add workflow trigger binding for channel/webhook triggers.
- [ ] `COMMS-PROFILE-25`: Add unified HITL delivery policy across site, host, and external channels.
- [ ] `COMMS-PROFILE-26`: Add runbook section for rollback per surface.
- [ ] `COMMS-PROFILE-27`: Add operator docs explaining channel resource versus agent exposure.
- [ ] `COMMS-PROFILE-28`: Add support docs for pairing external senders.
- [ ] `COMMS-PROFILE-29`: Add release checklist per channel type.

## Open decisions

1. Final naming: `comms`, `exposure`, or `surfaces` on the agent profile.
2. Whether profile-bound site chat should route by explicit agent id in
   `POST /v1/chat` or by conversation metadata only.
3. Which external request-response channel goes first after generic webhook:
   Teams, Slack Events, email webhook, or SMS.
4. Whether delivery events should live in the channel store or audit-derived
   observability store.
5. Whether personal agents get external channel exposure in the first release or
   only site chat plus human notification preferences.

## Decision to carry forward

Build the setup experience as an agent profile Comms/Exposure section, backed by
separate channel resources and a surface registry. Do not make Pi, Bifrost, or a
model runtime responsible for communications gateway behavior. Do not make agent
profiles hold secrets. Do not migrate any channel/client surface without a single
gateway of record and a tested rollback route.
