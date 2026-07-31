"""channel.send - the governed outbound egress verb (decision 0003).

Posting to a channel is an ORDINARY egress verb: it flows through the one
chokepoint, so it inherits grant checks, HITL (consequence=high by default,
SEC-39), rate-limit, idempotency and audit-always. The kernel executes the
outbound send directly (the court's caveat: outbound sends the kernel executes
directly, not the sidecar). Delivery is a per-transport seam:

  - a channel configured with an ``outbound_url`` gets an egress-guarded POST
    (the webhook-class direct path, unchanged);
  - a SOCKET-class channel is handed to the Phase-2 sidecar through the durable
    ``channel_outbox`` (tenant-scoped, leased claim, ack/backoff-retry): the
    sidecar holds the platform connection, the kernel never pretends to;
  - a webhook-class channel with no outbound_url has no consumer at all, so the
    send stays honestly queued-but-unwired (no direct path and no outbox
    listener serves that class today).

The optional ``comment`` param is APPROVER-ONLY commentary (SEC-39): it rides
the params into the approval display context and the audit detail, but is
stripped at execution - the deliver seam (and therefore the outbox payload and
the webhook POST body) only ever carries ``text`` and ``target``, so an
approver's note can never reach the channel sender.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import Channel, ChannelOutboxMessage, InvocationContext
from boltrig.models.egress_diversion import DIVERTED_STATUS, Diversion

_SEND_OUT = {
    "type": "object",
    "properties": {"channel": {"type": "string"}, "delivery": {"type": "object"}},
}

DeliverFn = Callable[[Channel, str, str | None], Awaitable[dict]]

# Answers "is this send diverted, and to where" for one declared recipient. Injected
# at the composition root so this adapter never reads the environment and a test
# can state the posture it is exercising rather than arrange four variables.
DiversionFn = Callable[[str], "Diversion | None"]


async def _default_deliver(
    store,
    channel: Channel,
    text: str,
    target: str | None,
    diversion: Diversion | None = None,
) -> dict:
    """Kernel-side outbound delivery. A channel with a configured outbound_url
    gets an egress-guarded POST; a socket channel is enqueued for the sidecar
    (durable hand-off, decision 0003 Phase 2).

    When ``diversion`` is present the message goes to the stack's own loopback
    intake instead, and the receipt says ``diverted`` - never ``sent``, on any
    branch (C4 of [2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001). The diversion
    is taken BEFORE the transport branch on purpose: a socket channel diverting
    into its own outbox row would be indistinguishable from a real queued send at
    every reader downstream.
    """
    if diversion is not None:
        from boltrig.adapters.egress import pinned_async_client

        # The loopback is received by the REAL intake, so routing, binding,
        # notification and approval are genuinely exercised; only this final
        # transport leg is substituted. The court expressly did NOT require the
        # identical transport, and recorded that as a limitation to disclose
        # rather than cure - nobody may cite a dev-mode success as evidence the
        # real transport works.
        async with pinned_async_client(diversion.loopback_url, timeout=10) as client:
            resp = await client.post(
                diversion.loopback_url,
                json={"text": text, "target": target, "channel": channel.id},
            )
        return {
            "status": DIVERTED_STATUS,
            "code": resp.status_code,
            **diversion.as_context(),
        }
    outbound_url = (channel.config or {}).get("outbound_url")
    if outbound_url:
        from boltrig.adapters.egress import pinned_async_client

        # SSRF (H2/SEC-61): pin the connection to the vetted IP so httpx cannot
        # re-resolve the outbound host to internal space (raises EgressBlocked).
        async with pinned_async_client(outbound_url, timeout=10) as client:
            resp = await client.post(outbound_url, json={"text": text, "target": target})
        return {"status": "sent", "code": resp.status_code}
    if channel.transport == "socket":
        # The durable hand-off: the sidecar claims this row over its run-scoped
        # token and settles it with ack / fail-with-backoff. The payload carries
        # no credential - the platform secret is connect-time injected into the
        # sidecar, never stored here (decision 0003, conditions 2 + 7).
        message = ChannelOutboxMessage(
            id=f"co_{uuid.uuid4().hex[:16]}", tenant_id=channel.tenant_id,
            channel_id=channel.id, payload={"text": text, "target": target},
        )
        await store.enqueue_channel_outbox(message)
        return {"status": "queued", "transport": "socket", "outbox": message.id}
    return {"status": "queued", "transport": channel.transport}


class ChannelSendAdapter:
    id = "channel-send"
    version = "1.0.0"
    runtime = "script"
    source = "builtin"

    def __init__(
        self,
        store,
        deliver: DeliverFn | None = None,
        diversion: DiversionFn | None = None,
    ) -> None:
        self._store = store
        self._deliver = deliver or self._deliver_default
        self._diversion = diversion

    def _diversion_for(self, params: dict) -> Diversion | None:
        if self._diversion is None:
            return None
        return self._diversion(str(params.get("target") or ""))

    async def _deliver_default(self, channel: Channel, text: str, target: str | None) -> dict:
        return await _default_deliver(
            self._store, channel, text, target, self._diversion_for({"target": target})
        )

    def approval_context(self, verb: str, params: dict, context: InvocationContext) -> dict | None:
        """What the approver must be told before they approve (C3).

        The approval gate lifts ``approval_notice`` into the request QUESTION,
        which is what the notification carries, and renders the rest on the card.
        One hook therefore reaches all three surfaces the court named - and,
        because the resource context is part of the approval FINGERPRINT, an
        approval given on the diverted description cannot be redeemed for a real
        send. That is the ratio made structural rather than restated: an approval
        obtained on a false description of its effect is not an approval.
        """
        del context
        if verb != "channel.send":
            return None
        diversion = self._diversion_for(params)
        if diversion is None:
            return None
        return {"approval_notice": diversion.notice(), "egress": diversion.as_context()}

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="channel.send",
                noun_id="channel",
                input_schema={
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string"},
                        "text": {"type": "string"},
                        "target": {"type": "string"},
                        # approver-only commentary: shown in the approval display
                        # context, never delivered (stripped before the seam)
                        "comment": {"type": "string"},
                    },
                    "required": ["channel_id", "text"],
                },
                output_schema=_SEND_OUT,
                consequence="high",  # outbound: HITL by default (SEC-39)
                description="Post a message to a connected channel",
                rate_limit={"per": "minute", "max": 60, "scope": "tenant"},
            )
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if verb != "channel.send":
            return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))
        ch = await self._store.get_channel(context.tenant_id, params["channel_id"])
        if ch is None or not ch.enabled:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "unknown or disabled channel"))
        try:
            # The approver-only ``comment`` is deliberately NOT passed on: the
            # deliver seam carries exactly (text, target), so a comment can
            # never ride the outbox row or the webhook body to the sender.
            delivery = await self._deliver(ch, params["text"], params.get("target"))
        except Exception as exc:  # egress-blocked or a delivery failure
            return Result.failure(AdapterError(ErrorClass.INVALID, f"delivery failed: {exc}"))
        return Result.success({"channel": ch.id, "delivery": delivery})

    async def health(self) -> str:
        return "ok"


def build_channel_send(
    store,
    deliver: DeliverFn | None = None,
    diversion: DiversionFn | None = None,
) -> ChannelSendAdapter:
    return ChannelSendAdapter(store, deliver, diversion)
