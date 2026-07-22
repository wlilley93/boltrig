# Adding a platform adapter (the port guide)

The channel gateway's adapter registry (`adapters.py`) is the port target for
real socket-class platforms: Slack Socket Mode, Discord WS, Telegram long-poll,
WhatsApp/Baileys, Signal. This guide is the contract. Read it together with
decision `docs/decisions/0003-channel-gateway-ruling.md` - its 10 conditions
are binding and a port that violates them is rejected, not debated.

## Raw material: the Hermes gateway adapters

The MIT-licensed Hermes gateway (`Nous Research/hermes-agent`) ships working
per-platform connection code under `gateway/platforms/` (`slack.py`,
`discord.py`, `telegram.py`, `whatsapp.py`, `signal.py`, and more). That code
is RAW MATERIAL for ports: it demonstrates each platform's connection
mechanics (socket URLs, heartbeats, reconnects, event shapes) but it is built
for Hermes's own monolith, so it must be ADAPTED, not dropped in.

**License obligation (MIT).** Hermes is Copyright (c) 2025 Nous Research,
MIT-licensed. Any file that copies or derives from Hermes code MUST carry the
MIT license text and the Nous Research copyright notice (a header comment
naming the source file and the license is the minimum; vendored files keep the
full license block). Check the license in the source repo before porting and
record provenance in the ported file's docstring.

## The adapter contract

Subclass `PlatformAdapter` (`adapters.py`) and register the class:

```python
@register_adapter
class SlackSocketAdapter(PlatformAdapter):
    platform = "slack"

    def __init__(self, config: dict): ...
    async def start(self, on_message): ...   # open the socket; per inbound
                                             # event: await on_message({...})
    async def stop(self): ...                # close the connection
    async def deliver(self, payload): ...    # send {"text", "target"} to the
                                             # platform; raise
                                             # AdapterDeliveryError on failure
```

- `on_message(message)` is called with a plain dict per inbound platform
  event. Shape it like the reference adapter: at minimum
  `{"id", "sender", "text"}` - `id` is the platform's stable delivery/event id
  (it feeds the kernel's durable replay dedup; a platform with no stable id
  cannot be deduped - say so in the adapter docstring), `sender` is the
  VERIFIED platform user id the kernel maps to a Principal via its binding
  rows. Per-platform signature verification (Slack v0, Discord Ed25519) happens
  at the platform's own byte/handshake boundary INSIDE the adapter (condition
  4) - the kernel's canonical-HMAC intake is only for the gateway->kernel hop.
- `"thread"` is a COMPLETE deliver target, not a fragment (learned from the
  Telegram port): the kernel stamps it on the work item's `reply_route`, and
  the notify seam enqueues it VERBATIM as the outbox payload's `target`
  (`kernel/channel_notify.py`). So shape it as exactly what your `deliver()`
  can route on - e.g. Telegram uses `chat_id:message_thread_id` for forum
  topics, Discord the channel id, Signal the sender number or `group:<id>`.
  `deliver()` then parses its own thread grammar (the reference split is
  `target.partition(":")`).
- "Socket class" honestly includes poll transports: a platform with no
  bot-accessible socket (Telegram's Bot API) ports as an adapter-owned
  long-poll loop with the same reconnect/backoff ownership as a receive loop.
  Say so in the docstring rather than pretending to a socket.
- `deliver(payload)` receives exactly what `channel.send` enqueued
  (`{"text", "target"}`). Raise `AdapterDeliveryError` on failure; the daemon
  fails the outbox row and the kernel retries with exponential backoff
  (terminal `failed` after 8 attempts). Delivery must be idempotency-tolerant:
  at-least-once means a platform dedup key where the platform offers one.

## The rules (binding conditions - a port breaking these is rejected)

1. **No `boltrig.*` imports** (SEC-28, machine-enforced over this directory).
   Duplicate the ~10 lines you need locally, like `kernel_client.py` does.
2. **No policy, no grants, no persistent credential** (condition 2). An adapter
   never decides WHO may do WHAT. It moves messages.
3. **Secrets arrive via `config`/env at spawn only** (condition 7) and are
   NEVER logged - not in exceptions, not in debug lines. Platform tokens are
   connect-time injected by the operator (the kernel resolves the credential
   and hands it to the spawn environment; it never crosses a wire).
4. **Egress restricted** (condition 2): an adapter that dials out MUST check
   `egress.egress_refusal(url, allow)` before connecting and document its
   endpoint hosts for `CHANNEL_GATEWAY_EGRESS_ALLOW`. No other network I/O.
5. **No new kernel route**: inbound goes to the ONE intake path, outbound rides
   the outbox pump. If a port "needs" a third link, the port is wrong - surface
   it instead of building a side door.
6. **The messaging SDK lives in THIS image** (condition 9): add the dependency
   to `requirements.in`, regenerate the hash-locked `requirements.txt` with the
   command at its top, and never let it leak into the kernel image.

## Lifecycle

The daemon supervises: `start()` runs under reconnect-with-backoff (a start
failure retries at 1s doubling to 30s); `stop()` must be idempotent and must
not hang shutdown. Heartbeats, resume tokens, and crash forensics belong INSIDE
the adapter - that is why this class of channel has a gateway at all.

## Prove it

Mirror the reference round-trip test
(`tests/security/test_channel_gateway_roundtrip.py`): spawn the daemon in-proc
against a test kernel, push one platform event through to a governed work item,
and deliver one `channel.send` back out through `deliver`. A port without both
legs of that proof is scaffold, and the docs will say so.
