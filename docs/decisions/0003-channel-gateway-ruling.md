# 0003 - Channel gateway architecture (VJS First Instance, hybrid)

Status: RULED (binding). Disposition of the first-impression fork on how Boltrig
terminates external messaging channels (Slack, Discord, WhatsApp, Telegram,
Signal, MS Teams, email, generic signed webhooks) and fans them into the one
governed chokepoint, plus how it surfaces in the console and workflows.

## Decision: HYBRID (by transport class)

"Channel" is two transport shapes, and the split-test is applied to each:

- **Webhook / request-response class** (generic signed webhook, MS Graph, Slack
  Events, Telegram webhook-mode): terminated **in-kernel** as thin FastAPI routes
  on `app.py`, reusing `inbound_webhook.verify_and_normalise` + `work/normalise`.
  A severed process here fails demonstrated-need (a signed POST is a hash-compare
  with no long-lived resource) and would be a side door.
- **Persistent-connection class** (Slack Socket Mode, Discord WS, Telegram
  long-poll, WhatsApp/Baileys, Signal): terminated by a **severed supervised
  sidecar** (the pi-sidecar / DocEngine precedent). A socket held open for days
  with heartbeats, reconnect-backoff, and crash forensics has no home in a
  stateless route, and welding the messaging SDKs into the dependency-light
  kernel would breach decision 0001. The sidecar owns no policy/grants/persistent
  credential and re-enters only over a run-scoped token, exactly like pi-sidecar.

Both classes terminate at the **identical seam**: platform verify -> sender ->
Principal resolution -> `normalise(tenant_id from the verified binding)` ->
`kernel.invoke`. So nothing built in Phase 1 is discarded when the sidecar lands.
The invariant is ONE DISPATCHER, not one process.

## Identity mapping (kernel-authoritative)
The verified external sender is mapped to a `Principal` via **tenant-scoped RLS
channel-binding rows**. `tenant_id` comes ONLY from the verified binding (never
the payload or an untrusted header), then `set_current_tenant` binds RLS. An
unmapped/un-paired sender is denied fail-closed. Pairing is kernel-governed RLS
rows (not files); `channel.pair` is HITL-gated; one-time codes are hashed,
TTL-bounded, rate-limited, lockout-guarded, never logged.

## Noun modeling (confirmed)
Channel is a governed noun with verbs `channel.connect / configure / disconnect /
send / pair`. `channel.send` is an ordinary egress verb through the chokepoint
(grants, HITL, rate-limit, idempotency, audit, egress guard). Credentials are
kernel-only (SEC-04/05) except the single permitted **connect-time secret**
injected to the sidecar (mirrors `pi_runtime` model-key handling; never logged,
never to an agent). `connect/disconnect/send` default to `consequence=high`.

## Binding conditions
1. One-dispatcher: every channel path terminates at the identical seam; none bypasses the chokepoint.
2. The sidecar owns no policy/grants/persistent tool credential; re-enters over a run-scoped token; egress restricted to the platform endpoints + the kernel intake.
3. Severability machine-enforced: add `channel_sidecar` to the SEC-28 forbidden-import regex; the sidecar stays outside the `boltrig` package (D5).
4. Per-platform verification (Slack v0, Discord Ed25519, MS Graph validationToken/clientState) implemented at the correct byte/handshake boundary; `verify_and_normalise` (canonical-JSON HMAC) reused only for the generic/GitHub/Stripe class.
5. `tenant_id` only from a verified RLS channel binding, then `set_current_tenant`.
6. Unpaired/unmapped senders denied fail-closed; pairing = kernel RLS rows, HITL-gated, hashed/TTL/rate-limited/lockout.
7. Credentials kernel-only except the one connect-time secret injection to the sidecar.
8. `connect/disconnect/send` default `consequence=high` unless an explicit low is authored (SEC-39).
9. The sidecar is a separate image alongside pi-sidecar; do NOT import the messaging SDKs into the kernel image (protects 0001).
10. No re-litigation to build the sidecar once Phase 2 lands, unless the sidecar is proposed to hold policy/credentials beyond conditions 2 and 7.

## Phasing
- **Phase 1** (now): webhook channels in-kernel; the `channel` noun + verbs; the
  `ChannelPrincipalResolver`; RLS channel-binding + pairing tables; console
  set-up/admin; workflow trigger + `channel.send` action.
- **Phase 2** (when a live channel is committed): the supervised sidecar (vendor
  Hermes's gateway in proxy mode) for the socket channels; implements Slack v0 /
  Discord Ed25519 there. Needs the Principal's app/bot credentials.
