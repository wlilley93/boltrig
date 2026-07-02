"""channel.send - the governed outbound egress verb (decision 0003).

Posting to a channel is an ORDINARY egress verb: it flows through the one
chokepoint, so it inherits grant checks, HITL (consequence=high by default,
SEC-39), rate-limit, idempotency and audit-always. The kernel executes the
outbound send directly (the court's caveat: outbound sends the kernel executes
directly, not the sidecar). Delivery is a per-transport seam: a channel
configured with an ``outbound_url`` gets an egress-guarded POST; a socket
platform (Slack/Discord/...) without a direct outbound is QUEUED for the Phase-2
sidecar. This keeps Phase 1 honest - socket delivery is Phase 2 - while the
governed verb and its audit exist now.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import Channel, InvocationContext

_SEND_OUT = {
    "type": "object",
    "properties": {"channel": {"type": "string"}, "delivery": {"type": "object"}},
}

DeliverFn = Callable[[Channel, str, str | None], Awaitable[dict]]


async def _default_deliver(channel: Channel, text: str, target: str | None) -> dict:
    """Kernel-side outbound delivery. A channel with a configured outbound_url
    gets an egress-guarded POST; anything else is queued for the sidecar."""
    outbound_url = (channel.config or {}).get("outbound_url")
    if not outbound_url:
        return {"status": "queued", "transport": channel.transport}
    from boltrig.adapters.egress import pinned_async_client

    # SSRF (H2/SEC-61): pin the connection to the vetted IP so httpx cannot
    # re-resolve the outbound host to internal space (raises EgressBlocked).
    async with pinned_async_client(outbound_url, timeout=10) as client:
        resp = await client.post(outbound_url, json={"text": text, "target": target})
    return {"status": "sent", "code": resp.status_code}


class ChannelSendAdapter:
    id = "channel-send"
    version = "1.0.0"
    runtime = "script"
    source = "builtin"

    def __init__(self, store, deliver: DeliverFn | None = None) -> None:
        self._store = store
        self._deliver = deliver or _default_deliver

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
            delivery = await self._deliver(ch, params["text"], params.get("target"))
        except Exception as exc:  # egress-blocked or a delivery failure
            return Result.failure(AdapterError(ErrorClass.INVALID, f"delivery failed: {exc}"))
        return Result.success({"channel": ch.id, "delivery": delivery})

    async def health(self) -> str:
        return "ok"


def build_channel_send(store, deliver: DeliverFn | None = None) -> ChannelSendAdapter:
    return ChannelSendAdapter(store, deliver)
