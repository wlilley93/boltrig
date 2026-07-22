"""The channel gateway service (decision 0003, Phase 2 skeleton).

The severed terminator for the socket (persistent-connection) channel class:
it holds the platform connections the stateless kernel must not, and re-enters
the kernel over TWO links only (condition 1: every path converges on the one
chokepoint):

  (a) INBOUND  - normalized platform messages are POSTed to the kernel's ONE
      intake route (``/v1/channels/{id}/inbound``), signed with the connect-time
      secret under the same HMAC scheme the webhook class uses;
  (b) OUTBOUND - a pump claims the kernel's durable channel outbox over the
      run-scoped token, delivers each message to its platform adapter, then
      acks (terminal) or fails (the kernel retries with backoff).

Conditions 2 + 7 (binding): the gateway owns NO policy, grants, or persistent
credential. Two secrets touch it, both injected into the ENVIRONMENT AT SPAWN
and never logged: the run-scoped kernel token (``CHANNEL_GATEWAY_TOKEN``) and
the per-channel connect-time secret (``CHANNEL_GATEWAY_CHANNELS``). Egress is
restricted to the kernel intake + the platform endpoints (``egress.py`` +
the container network, see the Dockerfile header).

SEVERED: this service is deliberately NOT part of the ``boltrig`` package and
imports nothing from it (SEC-28, machine-enforced); the only coupling is the
wire protocol in ``kernel_client.py``.

Configuration (env at spawn):
  BOLTRIG_KERNEL_URL         kernel base URL (default http://localhost:8000)
  CHANNEL_GATEWAY_TOKEN      the run-scoped token (minted by an admin via
                             POST /v1/channels/gateway/session; TTL-bounded)
  CHANNEL_GATEWAY_CHANNELS   JSON list: [{"channel_id", "platform", "secret",
                             "config": {...}}] - the connect-time injection
  CHANNEL_GATEWAY_EGRESS_ALLOW  comma hosts: the kernel host + platform endpoints
  CHANNEL_GATEWAY_POLL_SECONDS  outbox poll cadence when idle (default 2)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from adapters import PlatformAdapter, create_adapter
from egress import egress_refusal
from kernel_client import KernelAuthError, KernelClient, KernelLinkError

# Platform ports register themselves on import (data, not daemon logic - see
# ADDING_A_PLATFORM.md): importing the module populates the adapter registry.
import slack_adapter  # noqa: F401
import telegram_adapter  # noqa: F401
import discord_adapter  # noqa: F401
import signal_adapter  # noqa: F401
import whatsapp_adapter  # noqa: F401

log = logging.getLogger("channel_gateway")

_KERNEL_URL_ENV = "BOLTRIG_KERNEL_URL"
_TOKEN_ENV = "CHANNEL_GATEWAY_TOKEN"
_CHANNELS_ENV = "CHANNEL_GATEWAY_CHANNELS"
_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_POLL_ENV = "CHANNEL_GATEWAY_POLL_SECONDS"

_AUTH_RETRY_SECONDS = 30  # a refused token needs a supervised respawn, not a hot loop


@dataclass(frozen=True)
class ChannelSpec:
    """One channel the gateway serves. ``secret`` is the connect-time HMAC
    secret (condition 7): injected at spawn, fed only to the intake signature,
    NEVER logged."""

    channel_id: str
    platform: str
    secret: str
    config: dict[str, Any] = field(default_factory=dict)


def load_channel_specs(raw: str | None) -> list[ChannelSpec]:
    """Parse the CHANNEL_GATEWAY_CHANNELS connect-time injection (fail-closed:
    a malformed spec is a startup error, never a skipped channel)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        specs = [
            ChannelSpec(
                channel_id=str(entry["channel_id"]),
                platform=str(entry["platform"]),
                secret=str(entry["secret"]),
                config=dict(entry.get("config") or {}),
            )
            for entry in data
        ]
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"{_CHANNELS_ENV} is malformed: {exc}") from exc
    if not all(s.channel_id and s.platform and s.secret for s in specs):
        raise ValueError(f"{_CHANNELS_ENV}: every entry needs channel_id + platform + secret")
    return specs


class ChannelSidecarDaemon:
    """The adapter supervisor + the outbound pump. ``kernel`` is a KernelClient;
    the adapter factory is injectable so tests can substitute fakes."""

    def __init__(
        self,
        kernel: KernelClient,
        specs: list[ChannelSpec],
        *,
        poll_seconds: float = 2.0,
        adapter_factory: Callable[[str, dict], PlatformAdapter] = create_adapter,
    ) -> None:
        self._kernel = kernel
        self._specs = {s.channel_id: s for s in specs}
        self._factory = adapter_factory
        self._poll = poll_seconds
        self._adapters: dict[str, PlatformAdapter] = {}
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self.auth_ok = True  # surfaced on /status; a refused token flips it

    async def start(self) -> None:
        for spec in self._specs.values():
            self._tasks.append(asyncio.create_task(self._run_adapter(spec)))
        if self._specs:
            self._tasks.append(asyncio.create_task(self._pump_outbox()))

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown path
                pass
        self._tasks.clear()
        for adapter in list(self._adapters.values()):
            try:
                await adapter.stop()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass
        self._adapters.clear()

    # --- link (a): inbound -------------------------------------------------
    async def _on_message(self, spec: ChannelSpec, message: dict) -> None:
        body = {
            "id": message.get("id"),
            "sender": str(message.get("sender")),
            "text": message.get("text"),
            "type": "message",
        }
        if message.get("thread"):
            # routing data only (SEC-178): the intake maps it onto the reply
            # route so a reply returns to the originating thread
            body["thread"] = str(message["thread"])
        try:
            status, _ = await self._kernel.post_inbound(spec.channel_id, spec.secret, body)
        except KernelLinkError as exc:
            log.warning("intake POST failed for channel %s (%s)", spec.channel_id, exc)
            return
        if status >= 400:
            # never log the body or the secret - only the outcome
            log.warning("intake refused for channel %s (status %s)", spec.channel_id, status)

    # --- adapter lifecycle (start / stop / reconnect with backoff) ---------
    async def _run_adapter(self, spec: ChannelSpec) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            adapter = self._factory(spec.platform, dict(spec.config))
            try:
                await adapter.start(lambda m, s=spec: self._on_message(s, m))
            except Exception as exc:  # noqa: BLE001 - any start failure retries
                log.warning(
                    "adapter for channel %s failed to start (%s); retrying in %.0fs",
                    spec.channel_id, type(exc).__name__, backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            self._adapters[spec.channel_id] = adapter
            log.info("adapter up: channel %s (platform %s)", spec.channel_id, spec.platform)
            await self._stopping.wait()
            break
        adapter = self._adapters.pop(spec.channel_id, None)
        if adapter is not None:
            try:
                await adapter.stop()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass

    # --- link (b): the outbound pump ---------------------------------------
    async def _pump_outbox(self) -> None:
        backoff = self._poll
        while not self._stopping.is_set():
            try:
                messages = await self._kernel.claim_outbox()
            except KernelAuthError:
                # The run-scoped token lapsed. A run-scoped token is meant to be
                # re-minted by the operator and re-injected at (re)spawn - so we
                # mark ourselves degraded and idle instead of hot-looping.
                self.auth_ok = False
                log.error(
                    "outbox claim refused: the run-scoped token is expired or revoked; "
                    "re-mint POST /v1/channels/gateway/session and respawn to re-inject"
                )
                await self._sleep(_AUTH_RETRY_SECONDS)
                continue
            except KernelLinkError as exc:
                log.warning("outbox claim failed (%s); backing off", exc)
                await self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            self.auth_ok = True
            backoff = self._poll
            if not messages:
                await self._sleep(self._poll)
                continue
            for message in messages:
                await self._settle(message)

    async def _settle(self, message: dict) -> None:
        adapter = self._adapters.get(str(message.get("channel_id")))
        try:
            if adapter is None:
                raise KernelLinkError("no live adapter for this channel")
            await adapter.deliver(dict(message.get("payload") or {}))
        except Exception as exc:  # noqa: BLE001 - any delivery failure retries
            log.warning("delivery failed for outbox %s; failing for retry", message.get("id"))
            await self._safe_fail(str(message.get("id")), f"{type(exc).__name__}: {exc}")
            return
        await self._safe_ack(str(message.get("id")))

    async def _safe_ack(self, message_id: str) -> None:
        try:
            await self._kernel.ack_outbox(message_id)
        except KernelLinkError as exc:
            # the lease will lapse and a later claim redelivers (at-least-once)
            log.warning("ack failed for outbox %s (%s)", message_id, exc)

    async def _safe_fail(self, message_id: str, error: str) -> None:
        try:
            await self._kernel.fail_outbox(message_id, error[:200])
        except KernelLinkError as exc:
            log.warning("fail-report failed for outbox %s (%s)", message_id, exc)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except TimeoutError:
            pass


def _egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def build_daemon() -> ChannelSidecarDaemon:
    """Build the daemon from the spawn environment. Fails fast when the kernel
    URL is egress-refused; secret values are never logged."""
    kernel_url = os.environ.get(_KERNEL_URL_ENV, "http://localhost:8000")
    refusal = egress_refusal(kernel_url, _egress_allow())
    if refusal:
        raise RuntimeError(f"kernel URL egress-refused: {refusal}")
    specs = load_channel_specs(os.environ.get(_CHANNELS_ENV))
    poll = float(os.environ.get(_POLL_ENV, "2"))
    return ChannelSidecarDaemon(
        KernelClient(kernel_url, os.environ.get(_TOKEN_ENV)), specs, poll_seconds=poll
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    daemon = build_daemon()
    app.state.daemon = daemon
    await daemon.start()
    try:
        yield
    finally:
        await daemon.stop()


app = FastAPI(title="Boltrig Channel Gateway", version="0.1.0", lifespan=_lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe (no kernel dependency)."""
    return JSONResponse({"status": "ok"})


@app.get("/status")
async def status(request) -> JSONResponse:
    """What the gateway serves and whether its token still holds. Secrets are
    never surfaced - ids and booleans only."""
    daemon: ChannelSidecarDaemon = request.app.state.daemon
    return JSONResponse(
        {
            "channels": sorted(daemon._specs),
            "adapters_up": sorted(daemon._adapters),
            "token_ok": daemon.auth_ok,
        }
    )
