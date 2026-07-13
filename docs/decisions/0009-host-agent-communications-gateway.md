# 0009 - Host-agent communications gateway for pinned runtimes

- Status: accepted
- Date: 2026-07-04
- Court: VJS First Instance addendum, bound by decision 0003

## Context

The Opbox transition raised a first-impression risk: Boltrig can run an agent
through Pi and can route model calls through Bifrost, but that does not replace
Hermes's gateway role. Hermes/Opbox agent-chat currently presents client-facing
protocols: AG-UI SSE, OpenAI-compatible chat, approval continuation, health/model
surfaces, and runtime hiding.

Pi and Bifrost sit below that layer:

- Pi is a sandboxed runtime lane.
- Bifrost is a model/provider gateway.
- Neither is an omnichannel or client communications gateway.

Boltrig already has a binding channel-gateway decision for true external channels
(`0003-channel-gateway-ruling.md`): webhook/request-response channels terminate as
thin kernel routes; persistent socket/long-poll channels terminate in a supervised
sidecar; both re-enter the same governed chokepoint.

## Questions Presented

1. Can Pi plus Bifrost replace the Hermes/Opbox communications gateway?
2. Can the Opbox chat facade also become the omnichannel gateway?
3. Where should true Slack/Teams/email/webhook channel identity be decided?
4. Is communications migration all-or-nothing like workflow automation?
5. May two gateways consume or deliver the same channel traffic during migration?

## Answers

1. **No.** Pi plus Bifrost is runtime/model plumbing. It does not authenticate
   client requests, own channel sessions, normalize AG-UI/OpenAI ingress, stream
   client protocol events, or manage delivery/retry semantics.
2. **No for omnichannel; yes only for chat/API compatibility.** The Opbox
   `AGENT_CHAT_URL` facade is the right narrow replacement for Hermes-style chat
   and OpenAI-compatible client surfaces. It is not the right place to absorb
   Slack/Teams/email/voice channel SDKs or channel identity policy.
3. **In the channel gateway pattern from decision 0003.** Channel identity comes
   from verified tenant-scoped bindings, then re-enters the kernel chokepoint. It
   is never inferred by the model and never owned by Bifrost, Pi, or the chat
   facade.
4. **No globally; yes at each channel/client-surface boundary.** Chat/API,
   Slack, Teams, email, voice, signed webhooks, and OpenAI-compatible clients can
   migrate separately. But one surface/channel binding must have one gateway of
   record for auth, identity, idempotency, delivery, retry, and audit.
5. **No, not without an explicit non-owning shadow mode.** Two gateways must not
   both own the same inbound events, outbound deliveries, thread state, or retry
   queue. Shadowing is allowed only if one path is non-owning and cannot send,
   ack, mutate, or retry production traffic.

## Hermes vs Pi

Use **Pi/Boltrig for agent execution**. Use a **Boltrig host-agent facade** for
chat/API protocol compatibility. Do not use Pi as the communications gateway and
do not use Bifrost as the communications gateway.

Hermes has two remaining roles:

- **Legacy/rollback:** keep the current Hermes/agent-chat path available until
  Boltrig parity is proven.
- **Transport reference or vendored sidecar precedent:** channel-gateway work may
  reuse Hermes-style gateway/proxy ideas where they fit decision 0003, but that
  does not make Hermes the future agent engine.

Therefore the migration target is not "Hermes vs Pi" as peers. The target stack
is:

```text
client/channel -> host-agent communications gateway -> Boltrig/Pi runtime
               -> optional Bifrost model gateway -> host kernel/MCP tools
```

## Decision

Boltrig will treat the **host-agent communications gateway** as a separate layer
from Pi, Bifrost, MCP, and the kernel.

For a pinned-runtime migration such as Opbox, the host-agent communications
gateway is the compatibility facade that accepts host/client protocols and drives
Boltrig behind them. It may expose:

- `POST /chat/stream`
- `POST /chat/approve`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /health`

It owns protocol compatibility, stream/event translation, request normalization,
approval continuation wiring, and client-facing backpressure/close behavior. It
does **not** own business authorization, workflow state, channel identity policy,
billing authority, direct database writes, or provider secrets.

For true omnichannel ingress/egress, decision 0003 remains controlling:

- webhook/request-response class: thin kernel routes
- persistent-connection class: supervised sidecar
- both terminate at the same verified-principal -> normalise -> kernel chokepoint

The Opbox migration therefore has two distinct tracks:

1. **Chat/API compatibility now:** build a small `boltrig-host-agent` facade behind
   Opbox's existing `AGENT_CHAT_URL`, preserving AG-UI, approval continuation,
   and optional OpenAI-compatible `/v1` clients.
2. **Omnichannel later:** use the existing 0003 hybrid channel-gateway pattern,
   not Pi+Bifrost and not the Opbox chat facade.

## Binding conditions

1. Bifrost must never be documented or implemented as the communications gateway.
   It is model/provider routing only.
2. Pi must never own channel identity, request auth, billing, or host policy. It
   is runtime execution only.
3. The host-agent gateway may hold compatibility state, but product source of
   truth stays with the host app or kernel.
4. The host-agent gateway must fail closed when host auth/session/budget gates
   fail, and must not turn a human bearer into broad model-loop authority.
5. OpenAI-compatible and AG-UI output adapters must be tested from fixtures before
   migration traffic uses them.
6. Channel identities for Slack/Teams/email/webhooks must follow decision 0003
   and tenant-scoped verified bindings; they are not inferred by the model.
7. Persistent channel SDKs do not enter the kernel image or the host-agent chat
   facade unless a later decision explicitly narrows that condition.
8. Rollback remains a routing/config flip to the prior gateway or agent-chat
   surface until parity is proven.
9. One gateway of record per channel/client surface. A single chat thread,
   channel binding, webhook subscription, mailbox, phone number, or OpenAI client
   route must not be split across competing gateways.
10. Communications migration may be phased by surface: Opbox `AGENT_CHAT_URL`
    first, optional `/v1` clients next, then individual external channels under
    decision 0003.
11. Inbound deduplication and outbound idempotency must be decided before any
    owning channel migration. Do not point two owning webhook endpoints, socket
    clients, or mailbox pollers at the same production channel.

## Consequences

- Opbox can replace Hermes runtime without first building all omnichannel support.
- Future repos get a reusable gateway pattern for host-specific chat/API
  compatibility.
- Bifrost remains simple and bounded as the model gateway.
- The existing channel-gateway architecture remains valid and is not duplicated.
- Any later Slack/Teams/email/voice work must be scoped as channel-gateway work,
  not as Pi, Bifrost, or model-provider work.
