# Risks harvested from SPEC-17-channels-and-calls.md

RISK (HIGH): the generic adapter's inbound seam has NO authentication of its own, and
its `sender` field selects which Principal the message acts as. Anything that can open
the TCP listener can impersonate any bound `external_user_id` on that channel.
[`services/channel_gateway/adapters.py:98`](../../../services/channel_gateway/adapters.py) `"self._server = await asyncio.start_server(self._handle_peer, self._host, self._port)"`
The README states the exposure plainly for the off-box case
([`services/channel_gateway/README.md:109`](../../../services/channel_gateway/README.md) `"`listen_host: 0.0.0.0` plus network-level controls - the seam carries no"`),
but the same is true on-box for any process that can reach the loopback port.

---

RISK (HIGH): the WhatsApp adapter's `POST /inbound` listener has no authentication
either, and compose points the bridge at it across the sandbox network.
[`services/channel_gateway/whatsapp_adapter.py:136`](../../../services/channel_gateway/whatsapp_adapter.py) `listener.post("/inbound")(self._handle_inbound)`
with [`docker-compose.yml:679`](../../../docker-compose.yml) `"ADAPTER_URL: ${WHATSAPP_ADAPTER_URL:-http://channel-gateway:3001/inbound}"`.
Any container on the `sandbox` network can post a forged WhatsApp message naming any
sender id. This is the one inbound path in the area that reaches the governed intake
without verifying authenticity at its own boundary.

---

RISK (HIGH): the WhatsApp bridge's `POST /send` is gated only by a Host header, which
is a DNS-rebinding defence and not authentication. Any container on the sandbox network
can send arbitrary WhatsApp messages as the linked account.
[`services/channel_gateway/whatsapp_bridge/bridge.js:309`](../../../services/channel_gateway/whatsapp_bridge/bridge.js) `"error: 'Invalid Host header. Bridge accepts loopback hosts only.',"`
The same is true of the signal-cli sibling, which exposes an unauthenticated JSON-RPC
send on the same network ([`docker-compose.yml:645`](../../../docker-compose.yml) `"expose:"`).

---

RISK (HIGH): the Worker edge proxies the ENTIRE gateway under `/voice/`, not just the
media WebSocket, so `/voice/status` returns the tenant's channel ids, live adapter set
and per-channel observations to any unauthenticated caller who can reach Worker.
[`apps/worker/nginx.conf:67`](../../../apps/worker/nginx.conf) `"location /voice/ {"`
and [`services/channel_gateway/app.py:869`](../../../services/channel_gateway/app.py) `"channels": sorted(daemon._specs),`.
Channel ids are the capability that stands in for the tenant fence on the RLS-excluded
`channels` table, so leaking them erodes a stated defence layer even though the intake
signature still gates ingest.

---

RISK (MEDIUM): a gateway session token cannot be revoked. `McpFace.revoke` exists but
no route, console action or control verb calls it for a gateway session; the only
bounds are the 3600 second TTL and the 45 second per-channel lease.
[`boltrig/kernel/mcp.py:130`](../../../boltrig/kernel/mcp.py) `"def revoke(self, token: str) -> None:"`
(bounded: `rg -n "mcp\.revoke|revoke\(token" boltrig/ tests/ apps/ sdks/`, 2026-08-24,
pinned tree: the only callers are three test files and the Codex runtime resolver).
SEC-177 nevertheless describes the token as "revocable".

---

RISK (MEDIUM): the MCP run-token registry is a process-local dict, so a kernel restart
silently invalidates every live gateway session and a multi-replica deployment breaks
unless every gateway call lands on the minting replica.
[`boltrig/kernel/mcp.py:79`](../../../boltrig/kernel/mcp.py) `"self._tokens: dict[str, RunToken] = {}"`
The README discloses it ([`services/channel_gateway/README.md:86`](../../../services/channel_gateway/README.md) `"second token-minting authority. The MCP token registry is currently local to"`)
but nothing in code or compose prevents the second replica.

---

RISK (MEDIUM): the gateway token's maximum TTL is one hour
([`boltrig/kernel/mcp.py:75`](../../../boltrig/kernel/mcp.py) `"MAX_RUN_TOKEN_TTL_SECONDS = 3600"`),
and the session mint defaults to exactly that. A gateway therefore needs an operator to
mint and place a fresh token at least hourly, forever; there is no renewal path, and an
env-token deployment additionally needs a container restart each time. Nothing in the
repo automates that, which makes continuous socket-channel operation an unattended-hours
problem rather than a deployment step.

---

RISK (MEDIUM): `allowed_chats` and the reply/thread ceiling can key on DIFFERENT body
fields for the same message. The allowlist consults `addressing.chat_field` first and
then a six-field order
([`boltrig/kernel/channel_policy.py:23`](../../../boltrig/kernel/channel_policy.py) `configured = addressing.get("chat_field") or addressing.get("thread_field")`),
while addressing consults only `addressing.thread_field` and a different five-field
order ([`boltrig/kernel/channel_addressing_runtime.py:24`](../../../boltrig/kernel/channel_addressing_runtime.py) `thread_field = addressing.get("thread_field")`).
A body carrying both `channel` and `chat_id`, or a channel configured with `chat_field`
but not `thread_field`, is allow-listed on one key and ceilinged on another.

---

RISK (MEDIUM): the per-message `target` is taken from the signed body and is NOT
validated against the addressing catalogue at intake, only shape-checked by a slug
regex ([`boltrig/kernel/channel_addressing_runtime.py:34`](../../../boltrig/kernel/channel_addressing_runtime.py) `target = _clean_target(body.get("target"))`).
Catalogue validation applies only to AUTHORED channel config
([`boltrig/config/channel_addressing.py:191`](../../../boltrig/config/channel_addressing.py) `"async def validate_channel_addressing_config("`).
A bound member-tier sender can therefore pin any named agent or any `workflow:<id>` on a
per-message basis. Authority is still the sender's grants, so this is a routing rather
than an authorisation defect, but it is a wider surface than the console exposes.

---

RISK (MEDIUM): the intake rate limiter runs AFTER sender resolution, so a signed message
from an unbound sender consumes a binding lookup, a self-onboard evaluation and a store
round trip without ever touching the per-channel counter
([`boltrig/kernel/channel_inbound_routes.py:53`](../../../boltrig/kernel/channel_inbound_routes.py) `"throttled = await _enforce_intake_rate(kernel, channel, sender)"`).
Only the 5/minute onboarding limiter bounds that path, and only when `self_onboard` is
configured.

---

RISK (MEDIUM): a socket channel whose adapter is flapping burns the outbox attempt cap
on rows it never had a connection for. `_settle` treats "no live adapter" as a delivery
failure ([`services/channel_gateway/app.py:634`](../../../services/channel_gateway/app.py) `raise KernelLinkError("no live adapter for this channel")`),
and with the shipped 5 second base and cap of 8
([`boltrig/kernel/channel_gateway_outbox_routes.py:13`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"OUTBOX_MAX_ATTEMPTS = 8"`)
a user's approval notice reaches terminal `failed` in about eleven minutes of adapter
downtime, after which recovery is an admin approval, not a retry.

---

RISK (MEDIUM): `_owned_channels` requires the owner lease to have at least
`lease_seconds` remaining ([`boltrig/kernel/channel_gateway_outbox_routes.py:70`](../../../boltrig/kernel/channel_gateway_outbox_routes.py) `"minimum_remaining_seconds=outbox_lease,"`),
but the owner lease is only 45 seconds while the outbox lease is clamped to 300. A
client that asks for any lease above roughly 35 seconds silently claims nothing, with no
error and no observation. The shipped client asks for 30, so the coupling is invisible
until someone tunes it.

---

RISK (MEDIUM): the gateway drops an inbound message whose intake POST fails at the
transport level ([`services/channel_gateway/app.py:272`](../../../services/channel_gateway/app.py) `"except KernelLinkError as exc:"`).
There is no local spool and no retry, so a kernel restart during a burst loses those
messages entirely. Outbound is durable; inbound is not.

---

RISK (LOW): binding ROLE is trusted from the binding row without re-checking that the
subject still holds it, for a subject with no user record. A synthetic
`external:<platform>:<id>` subject keeps the member ceiling for as long as the row
exists; there is no expiry and no periodic re-attestation
([`boltrig/kernel/channel_principal.py:86`](../../../boltrig/kernel/channel_principal.py) `"grants = ceiling"`).

---

RISK (LOW): nothing prunes `channel_outbox`, `channel_gateway_status` or
`realtime_call_events`. Delivered and terminally failed rows accumulate for the life of
the tenant; only `channel_deliveries` is swept
([`boltrig/store/channel_dedup.py:37`](../../../boltrig/store/channel_dedup.py) `"DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()"`).

---

RISK (LOW): `_sole_pending_for` lists EVERY pending HITL request for the tenant and then
filters in Python, on every inbound channel message that carries text
([`boltrig/kernel/channel_routes.py:145`](../../../boltrig/kernel/channel_routes.py) `"async def _sole_pending_for(kernel, ch, subject: str, thread: str):"`).
On a tenant with a large pending queue every chat message pays that scan.

---

RISK (LOW): condition 4 of the ruling required Slack v0 and Discord Ed25519 verification
"at the correct byte/handshake boundary"
([`docs/decisions/0003-channel-gateway-ruling.md:50`](../../../docs/decisions/0003-channel-gateway-ruling.md) `4. Per-platform verification (Slack v0, Discord Ed25519, MS Graph validationToken/clientState) implemented at the correct byte/handshake boundary`).
Neither exists in the tree. The ports answer honestly that they expose no HTTP
interactions endpoint, so there is no surface for those schemes
([`services/channel_gateway/slack_adapter.py:12`](../../../services/channel_gateway/slack_adapter.py) `"The verification boundary (condition 4, an honest statement): this port is"`).
That is a defensible reading, but it means any future webhook-mode Slack or Discord port
lands on an unimplemented verifier.
