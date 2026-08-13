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

Conditions 2 + 7 (binding): the gateway owns NO policy, grants, or credential
authority. A short-lived run token is loaded from one configured source and
never logged. In canonical mode, provider credentials cross the authenticated
reconcile link into memory only after this gateway wins the durable per-channel
owner lease. Egress is restricted to the kernel intake + platform endpoints
(``egress.py`` + the container network, see the Dockerfile header).

SEVERED: this service is deliberately NOT part of the ``boltrig`` package and
imports nothing from it (SEC-28, machine-enforced); the only coupling is the
wire protocol in ``kernel_client.py``.

Configuration (env at spawn):
  BOLTRIG_KERNEL_URL         kernel base URL (default http://localhost:8000)
  CHANNEL_GATEWAY_TOKEN      the run-scoped token (minted by an admin via
                             POST /v1/channels/gateway/session; TTL-bounded)
  CHANNEL_GATEWAY_TOKEN_FILE path to a mounted token, mutually exclusive with
                             TOKEN; a changed valid value reloads after a 401
  CHANNEL_GATEWAY_CHANNELS   development-only static compatibility JSON;
                             production requires kernel desired state
  CHANNEL_GATEWAY_EGRESS_ALLOW  comma hosts: the kernel host + platform endpoints
  CHANNEL_GATEWAY_POLL_SECONDS  outbox poll cadence when idle (default 2)
  CHANNEL_GATEWAY_MAX_BROWSER_CALLS  bounded concurrent browser voice sessions
                                    per gateway (default 8)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from adapters import PlatformAdapter, create_adapter
from egress import egress_refusal
from kernel_client import KernelAuthError, KernelClient, KernelLinkError
from browser_audio import BrowserAudio

# Platform ports register themselves on import (data, not daemon logic - see
# ADDING_A_PLATFORM.md): importing the module populates the adapter registry.
import slack_adapter  # noqa: F401
import telegram_adapter  # noqa: F401
import discord_adapter  # noqa: F401
import signal_adapter  # noqa: F401
import whatsapp_adapter  # noqa: F401
import xai_voice_adapter  # noqa: F401

log = logging.getLogger("channel_gateway")

_KERNEL_URL_ENV = "BOLTRIG_KERNEL_URL"
_TOKEN_ENV = "CHANNEL_GATEWAY_TOKEN"
_TOKEN_FILE_ENV = "CHANNEL_GATEWAY_TOKEN_FILE"
_CHANNELS_ENV = "CHANNEL_GATEWAY_CHANNELS"
_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_POLL_ENV = "CHANNEL_GATEWAY_POLL_SECONDS"
_RECONCILE_ENV = "CHANNEL_GATEWAY_RECONCILE_SECONDS"
_MAX_BROWSER_CALLS_ENV = "CHANNEL_GATEWAY_MAX_BROWSER_CALLS"

_AUTH_RETRY_SECONDS = 30
_DEFAULT_MAX_BROWSER_CALLS = 8
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,512}")
_MAX_USER_TEXT_CHARS = 8_000


class BrowserMediaCapacityError(RuntimeError):
    """The bounded browser-call pool is full; no active call was displaced."""


@dataclass
class BrowserMediaSession:
    """One caller's isolated provider, kernel-token view, and PCM bridge."""

    call_id: str
    channel_id: str
    adapter: PlatformAdapter
    audio: BrowserAudio
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class ChannelSpec:
    """One channel the gateway serves. ``secret`` is the connect-time HMAC
    secret (condition 7): injected at spawn, fed only to the intake signature,
    NEVER logged."""

    channel_id: str
    platform: str
    secret: str
    config: dict[str, Any] = field(default_factory=dict)
    revision: str = ""
    activation: str = "automatic"


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
                revision=str(entry.get("revision") or ""),
                activation=str(entry.get("activation") or "automatic"),
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
        reconcile_seconds: float = 10.0,
        max_browser_calls: int = _DEFAULT_MAX_BROWSER_CALLS,
        adapter_factory: Callable[
            [str, dict[str, Any]], PlatformAdapter
        ] = create_adapter,
        token_reloader: Callable[[], str | None] | None = None,
        token_source: str = "environment",
    ) -> None:
        if isinstance(max_browser_calls, bool) or max_browser_calls < 1:
            raise ValueError("max_browser_calls must be a positive integer")
        self._kernel = kernel
        self._specs = {s.channel_id: s for s in specs}
        self._static_specs = dict(self._specs)
        self._factory = adapter_factory
        self._poll = poll_seconds
        self._reconcile_seconds = reconcile_seconds
        # A non-empty static env snapshot stays a compatibility deployment.
        # An empty snapshot opts into the canonical kernel desired-state pull.
        self._dynamic_reconcile = not bool(specs)
        self._owner_election_supported = callable(
            getattr(kernel, "reconcile_channels", None)
        )
        self._token_reloader = token_reloader
        self._token_source = token_source
        self._max_browser_calls = max_browser_calls
        self._adapters: dict[str, PlatformAdapter] = {}
        self._browser_audio: dict[str, BrowserAudio] = {}
        self._browser_sessions: dict[str, BrowserMediaSession] = {}
        self._browser_session_lock = asyncio.Lock()
        self._browser_session_pending: set[str] = set()
        self._tasks: list[asyncio.Task[Any]] = []
        self._adapter_tasks: dict[str, asyncio.Task[Any]] = {}
        self._observations: dict[str, dict[str, str]] = {}
        self._stopping = asyncio.Event()
        loaded_token = getattr(kernel, "has_token", None)
        self.auth_ok = (
            bool(loaded_token)
            if loaded_token is not None
            else token_source != "missing"
        )
        # An empty desired set is valid only after the kernel has actually
        # authenticated this gateway and returned it. Without this separate
        # bit, an initial network failure could make /ready report a false green.
        self.reconcile_ok = not self._owner_election_supported

    async def start(self) -> None:
        if self._dynamic_reconcile:
            try:
                await self._reconcile_once()
            except KernelAuthError:
                self.auth_ok = False
                self.reconcile_ok = False
            except KernelLinkError as exc:
                self.reconcile_ok = False
                log.warning("initial channel reconcile failed (%s)", exc)
        elif self._owner_election_supported:
            try:
                await self._reconcile_static_ownership_once()
            except KernelAuthError:
                self.auth_ok = False
                self.reconcile_ok = False
                self._specs = {}
            except KernelLinkError as exc:
                self.reconcile_ok = False
                self._specs = {}
                log.warning("initial static channel ownership failed (%s)", exc)
        for spec in self._specs.values():
            if spec.channel_id not in self._adapter_tasks:
                self._start_adapter_task(spec)
        self._tasks.append(asyncio.create_task(self._pump_outbox()))
        if self._owner_election_supported:
            self._tasks.append(asyncio.create_task(self._reconcile_loop()))

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
        self._adapter_tasks.clear()
        for adapter in list(self._adapters.values()):
            try:
                await adapter.stop()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass
        self._adapters.clear()
        async with self._browser_session_lock:
            sessions = list(self._browser_sessions.values())
            self._browser_sessions.clear()
            self._browser_session_pending.clear()
        for session in sessions:
            try:
                async with session.operation_lock:
                    await session.adapter.stop()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass

    # --- link (a): inbound -------------------------------------------------
    async def _on_message(
        self, spec: ChannelSpec, message: dict[str, Any]
    ) -> None:
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
    def _start_adapter_task(self, spec: ChannelSpec) -> None:
        task = asyncio.create_task(self._run_adapter(spec))
        self._adapter_tasks[spec.channel_id] = task
        self._tasks.append(task)

    async def _stop_adapter_task(self, channel_id: str) -> None:
        task = self._adapter_tasks.pop(channel_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        adapter = self._adapters.pop(channel_id, None)
        if adapter is not None:
            with contextlib.suppress(Exception):
                await adapter.stop()

    async def _reconcile_once(self) -> None:
        desired = await self._kernel.reconcile_channels()
        self.auth_ok = True
        self.reconcile_ok = True
        next_specs: dict[str, ChannelSpec] = {}
        unresolved: dict[str, dict[str, str]] = {}
        for entry in list(desired.get("channels") or []):
            channel_id = str(entry.get("channel_id") or "")
            revision = str(entry.get("revision") or "")
            if not channel_id or not revision:
                continue
            if entry.get("state") != "configured":
                unresolved[channel_id] = {
                    "channel_id": channel_id,
                    "revision": revision,
                    "status": "needs_action",
                    "reason_code": str(
                        entry.get("reason_code") or "configuration_incomplete"
                    ),
                }
                continue
            next_specs[channel_id] = ChannelSpec(
                channel_id=channel_id,
                platform=str(entry.get("platform") or ""),
                secret=str(entry.get("secret") or ""),
                config=dict(entry.get("config") or {}),
                revision=revision,
                activation=str(entry.get("activation") or "automatic"),
            )
        for channel_id in sorted(set(self._specs) - set(next_specs)):
            await self._stop_adapter_task(channel_id)
            self._observations.pop(channel_id, None)
        for channel_id, spec in next_specs.items():
            current = self._specs.get(channel_id)
            if (
                current is not None
                and current.revision == spec.revision
                and channel_id in self._adapter_tasks
            ):
                continue
            if current is not None:
                await self._stop_adapter_task(channel_id)
            self._start_adapter_task(spec)
        self._specs = next_specs
        self._observations.update(unresolved)
        await self._report_observations()

    async def _report_observations(self) -> None:
        if not self._owner_election_supported:
            return
        await self._kernel.heartbeat_channels(list(self._observations.values()))

    async def _reconcile_static_ownership_once(self) -> None:
        """Renew ownership while retaining the explicit development snapshot.

        Production composition rejects static specs. This path exists only for
        compatibility tests/local development, but it still participates in the
        same kernel lease so it cannot create a second live owner.
        """
        desired = await self._kernel.reconcile_channels()
        self.auth_ok = True
        self.reconcile_ok = True
        entries = {
            str(entry.get("channel_id") or ""): entry
            for entry in list(desired.get("channels") or [])
        }
        owned = {
            channel_id
            for channel_id in self._static_specs
            if (
                channel_id in entries
                and dict(entries[channel_id].get("ownership") or {}).get(
                    "status"
                ) == "owner"
            )
        }
        for channel_id in sorted(set(self._specs) - owned):
            await self._stop_adapter_task(channel_id)
            self._observations.pop(channel_id, None)
        for channel_id in sorted(owned - set(self._specs)):
            spec = self._static_specs[channel_id]
            self._start_adapter_task(spec)
        self._specs = {
            channel_id: self._static_specs[channel_id]
            for channel_id in sorted(owned)
        }
        await self._report_observations()

    async def _reconcile_loop(self) -> None:
        while not self._stopping.is_set():
            await self._sleep(self._reconcile_seconds)
            if self._stopping.is_set():
                return
            try:
                if self._dynamic_reconcile:
                    await self._reconcile_once()
                else:
                    await self._reconcile_static_ownership_once()
            except KernelAuthError:
                self.auth_ok = False
                self.reconcile_ok = False
                recovered = self._reload_token()
                log.error(
                    "channel reconcile refused: token expired or revoked%s",
                    "; a rotated token file was loaded"
                    if recovered else "",
                )
            except KernelLinkError as exc:
                self.reconcile_ok = False
                log.warning("channel reconcile failed (%s)", exc)

    def _reload_token(self) -> bool:
        if self._token_reloader is None:
            return False
        try:
            token = self._token_reloader()
        except (OSError, ValueError):
            return False
        return bool(token and self._kernel.set_token(token))

    async def _run_adapter(self, spec: ChannelSpec) -> None:
        backoff = 1.0
        browser_audio = (
            self._browser_audio.setdefault(spec.channel_id, BrowserAudio(self._kernel))
            if spec.platform == "voice" and "audio" not in spec.config
            else None
        )
        self._observations[spec.channel_id] = {
            "channel_id": spec.channel_id,
            "revision": spec.revision,
            "status": "provisioning",
        }
        try:
            while not self._stopping.is_set():
                config = dict(spec.config)
                if browser_audio is not None:
                    # JSON config can never carry a Python audio object. The daemon
                    # owns this ephemeral bridge and injects it at construction.
                    config["audio"] = browser_audio
                    config["event_sink"] = browser_audio.emit_event
                adapter = self._factory(spec.platform, config)
                try:
                    async def on_message(message: dict[str, Any]) -> None:
                        await self._on_message(spec, message)

                    await adapter.start(on_message)
                except Exception as exc:  # noqa: BLE001 - any start failure retries
                    self._observations[spec.channel_id] = {
                        "channel_id": spec.channel_id,
                        "revision": spec.revision,
                        "status": "degraded",
                        "reason_code": "adapter_start_failed",
                    }
                    log.warning(
                        "adapter for channel %s failed to start (%s); retrying in %.0fs",
                        spec.channel_id, type(exc).__name__, backoff,
                    )
                    await self._sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                self._adapters[spec.channel_id] = adapter
                if spec.activation == "external_pairing":
                    self._observations[spec.channel_id] = {
                        "channel_id": spec.channel_id,
                        "revision": spec.revision,
                        "status": "needs_action",
                        "reason_code": "external_pairing_not_proven",
                    }
                else:
                    self._observations[spec.channel_id] = {
                        "channel_id": spec.channel_id,
                        "revision": spec.revision,
                        "status": "ready",
                    }
                log.info("adapter up: channel %s (platform %s)", spec.channel_id, spec.platform)
                await self._stopping.wait()
                break
        finally:
            stopped_adapter = self._adapters.pop(spec.channel_id, None)
            if stopped_adapter is not None:
                with contextlib.suppress(Exception):
                    await stopped_adapter.stop()

    async def claim_browser_media(
        self, call_id: str, media_token: str
    ) -> tuple[BrowserAudio | None, dict[str, Any]]:
        """Redeem a call bearer into one isolated, bounded provider session.

        The configured channel adapter remains the static channel connection.
        Browser callers never rotate it and never share a provider dialogue,
        caller-scoped kernel token, tool map, HITL task, usage meter, or PCM
        queue with another call.
        """
        claimed = await self._kernel.claim_call_media(call_id, media_token)
        channel_id = str(claimed.get("channel_id") or "")
        tool_token = str(claimed.get("tool_token") or "")
        spec = self._specs.get(channel_id)
        if (
            spec is None
            or spec.platform != "voice"
            or channel_id not in self._adapters
            or "audio" in spec.config
            or not tool_token
        ):
            return None, claimed

        replaced: BrowserMediaSession | None = None
        async with self._browser_session_lock:
            if call_id in self._browser_session_pending:
                return None, claimed
            replaced = self._browser_sessions.pop(call_id, None)
            if (
                len(self._browser_sessions) + len(self._browser_session_pending)
                >= self._max_browser_calls
            ):
                if replaced is not None:
                    self._browser_sessions[call_id] = replaced
                raise BrowserMediaCapacityError("browser voice capacity reached")
            self._browser_session_pending.add(call_id)

        audio = BrowserAudio(self._kernel)
        adapter: PlatformAdapter | None = None
        try:
            if replaced is not None:
                # A freshly redeemed one-time bearer for this exact call is an
                # authenticated reconnect. Retire the prior generation before
                # opening its replacement; no other call is touched.
                async with replaced.operation_lock:
                    await replaced.adapter.stop()
            config = dict(spec.config)
            config["audio"] = audio
            config["event_sink"] = audio.emit_event
            adapter = self._factory(spec.platform, config)
            activate = getattr(adapter, "activate_call", None)
            if not callable(activate):
                with contextlib.suppress(Exception):
                    await adapter.stop()
                adapter = None
                return None, claimed
            # Activation before start opens the very first provider socket with
            # the caller's tool token and profile; no base-authority provider
            # conversation is briefly created or later recycled.
            await activate(tool_token, call_id, claimed.get("session_profile"))
            async def on_message(message: dict[str, Any]) -> None:
                await self._on_message(spec, message)

            await adapter.start(on_message)
            session = BrowserMediaSession(call_id, channel_id, adapter, audio)
            async with self._browser_session_lock:
                self._browser_sessions[call_id] = session
            return audio, claimed
        except Exception:
            if adapter is not None:
                with contextlib.suppress(Exception):
                    await adapter.stop()
            raise
        finally:
            async with self._browser_session_lock:
                self._browser_session_pending.discard(call_id)

    async def inject_browser_text(
        self, call_id: str, audio: BrowserAudio, text: str
    ) -> bool:
        """Forward text only for the exact authenticated media generation.

        The identity recheck and provider injection share the exact session's
        operation lock, so reconnect waits without blocking unrelated calls.
        """
        async with self._browser_session_lock:
            session = self._browser_sessions.get(call_id)
            if session is None or session.audio is not audio:
                return False
        async with session.operation_lock:
            async with self._browser_session_lock:
                if self._browser_sessions.get(call_id) is not session:
                    return False
            inject = getattr(session.adapter, "inject_user_text", None)
            if not callable(inject):
                return False
            try:
                return bool(await inject(text))
            except Exception as exc:  # noqa: BLE001 - never kill the media socket
                # The text itself is caller content: log the outcome, not the text.
                log.warning(
                    "user text injection failed for call %s (%s)",
                    call_id, type(exc).__name__,
                )
                return False

    async def release_browser_media(
        self, call_id: str, audio: BrowserAudio | None = None
    ) -> None:
        """Destroy one exact call generation; every other session remains live.

        ``audio`` fences late cleanup from a replaced WebSocket: an old
        disconnect must not remove the newer same-call provider session.
        """
        async with self._browser_session_lock:
            session = self._browser_sessions.get(call_id)
            if session is None or (audio is not None and session.audio is not audio):
                return
            self._browser_sessions.pop(call_id)
        if session is not None:
            async with session.operation_lock:
                await session.adapter.stop()

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
                recovered = self._reload_token()
                log.error(
                    "outbox claim refused: the run-scoped token is expired or revoked; "
                    "%s",
                    (
                        "a rotated token file was loaded"
                        if recovered
                        else "mint a replacement gateway session token"
                    ),
                )
                await self._sleep(
                    self._poll if recovered else _AUTH_RETRY_SECONDS
                )
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

    async def _settle(self, message: dict[str, Any]) -> None:
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


def _production() -> bool:
    values = (
        os.environ.get("BOLTRIG_PRODUCTION"),
        os.environ.get("BOLTRIG_ENV"),
        os.environ.get("ENV"),
        os.environ.get("APP_ENV"),
    )
    return any(
        str(value or "").strip().lower()
        in {"1", "true", "yes", "on", "prod", "production", "staging"}
        for value in values
    )


def _read_token_file(path: str) -> str | None:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        return None
    if not _TOKEN_PATTERN.fullmatch(value):
        raise ValueError("gateway token file is malformed")
    return value


def build_daemon() -> ChannelSidecarDaemon:
    """Build the daemon from the spawn environment. Fails fast when the kernel
    URL is egress-refused; secret values are never logged."""
    kernel_url = os.environ.get(_KERNEL_URL_ENV, "http://localhost:8000")
    refusal = egress_refusal(kernel_url, _egress_allow())
    if refusal:
        raise RuntimeError(f"kernel URL egress-refused: {refusal}")
    specs = load_channel_specs(os.environ.get(_CHANNELS_ENV))
    if specs and _production():
        raise RuntimeError(
            "static channel specs are disabled in production; use kernel "
            "desired-state reconciliation"
        )
    token_file = str(os.environ.get(_TOKEN_FILE_ENV) or "").strip()
    env_token = str(os.environ.get(_TOKEN_ENV) or "").strip()
    if token_file and env_token:
        raise RuntimeError(
            "configure exactly one gateway token source, not both"
        )
    token_reloader = None
    token_source = "missing"
    token: str | None = None
    if token_file:
        def token_reloader() -> str | None:
            return _read_token_file(token_file)

        token = token_reloader()
        token_source = "file"
    elif env_token:
        if not _TOKEN_PATTERN.fullmatch(env_token):
            raise ValueError(f"{_TOKEN_ENV} is malformed")
        token = env_token
        token_source = "environment"
    poll = float(os.environ.get(_POLL_ENV, "2"))
    reconcile = float(os.environ.get(_RECONCILE_ENV, "10"))
    try:
        max_browser_calls = int(
            os.environ.get(
                _MAX_BROWSER_CALLS_ENV, str(_DEFAULT_MAX_BROWSER_CALLS)
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"{_MAX_BROWSER_CALLS_ENV} must be a positive integer"
        ) from exc
    return ChannelSidecarDaemon(
        KernelClient(kernel_url, token),
        specs,
        poll_seconds=poll,
        reconcile_seconds=reconcile,
        max_browser_calls=max_browser_calls,
        token_reloader=token_reloader,
        token_source=token_source,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
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


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Operational readiness, distinct from liveness and delivery proof."""
    daemon: ChannelSidecarDaemon = request.app.state.daemon
    converged = all(
        channel_id in daemon._adapters for channel_id in daemon._specs
    )
    ok = daemon.auth_ok and daemon.reconcile_ok and converged
    return JSONResponse(
        {
            "status": "ok" if ok else "degraded",
            "token_ok": daemon.auth_ok,
            "reconciliation_ok": daemon.reconcile_ok,
            "token_source": daemon._token_source,
            "token_reload_supported": daemon._token_reloader is not None,
            "single_owner_enforced": (
                daemon._dynamic_reconcile
                or daemon._owner_election_supported
            ),
            "desired": len(daemon._specs),
            "adapters_up": len(daemon._adapters),
        },
        status_code=200 if ok else 503,
    )


def _user_text_frame(raw: str | None) -> str | None:
    """Parse one typed mid-call message frame (``{"type":"user_text",...}``);
    anything else is not user text and is ignored by the caller."""
    if not raw or len(raw) > 2 * _MAX_USER_TEXT_CHARS:
        return None
    try:
        frame = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict) or frame.get("type") != "user_text":
        return None
    text = str(frame.get("text") or "").strip()[:_MAX_USER_TEXT_CHARS]
    return text or None


@app.websocket("/v1/calls/{call_id}/media")
async def browser_call_media(websocket: WebSocket, call_id: str) -> None:
    """Authenticate in the first frame, then relay bounded PCM frames.

    The bearer intentionally travels in a WebSocket message rather than the URL,
    where reverse-proxy access logs commonly capture query strings. Text frames
    after authentication are control messages: ``ping`` keepalives and typed
    mid-call ``user_text`` messages forwarded into the provider session.
    """
    await websocket.accept()
    bridge: BrowserAudio | None = None
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        if not isinstance(first, dict) or first.get("type") != "authenticate":
            await websocket.close(code=4401)
            return
        token = str(first.get("media_token") or "")
        if not token:
            await websocket.close(code=4401)
            return
        daemon: ChannelSidecarDaemon = websocket.app.state.daemon
        try:
            bridge, claimed = await daemon.claim_browser_media(call_id, token)
        except (KernelAuthError, KernelLinkError):
            await websocket.close(code=4401)
            return
        except BrowserMediaCapacityError:
            await websocket.close(code=4429)
            return
        except Exception:  # provider reset/unavailable; bearer stays secret
            await websocket.close(code=1013)
            return
        if bridge is None or not await bridge.attach(call_id, websocket):
            await websocket.close(code=4429)
            return
        await websocket.send_json({"type": "ready", "call": claimed.get("call") or {}})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            frame = message.get("bytes")
            if isinstance(frame, bytes):
                bridge.feed_mic(frame)
                continue
            text = message.get("text")
            if text == '{"type":"ping"}':
                await websocket.send_json({"type": "pong"})
                continue
            user_text = _user_text_frame(text)
            if user_text is not None:
                await daemon.inject_browser_text(call_id, bridge, user_text)
    except (TimeoutError, WebSocketDisconnect):
        pass
    finally:
        if bridge is not None:
            with contextlib.suppress(Exception):
                # Keep the call id just long enough for adapter.stop() to flush
                # this call's final content-free usage event through the sink.
                await bridge.detach(call_id, retain_call=True)
            with contextlib.suppress(Exception):
                await websocket.app.state.daemon.release_browser_media(
                    call_id, bridge
                )


@app.get("/status")
async def status(request: Request) -> JSONResponse:
    """What the gateway serves and whether its token still holds. Secrets are
    never surfaced - ids and booleans only."""
    daemon: ChannelSidecarDaemon = request.app.state.daemon
    return JSONResponse(
        {
            "channels": sorted(daemon._specs),
            "adapters_up": sorted(daemon._adapters),
            "token_ok": daemon.auth_ok,
            "reconciliation_ok": daemon.reconcile_ok,
            "token_source": daemon._token_source,
            "token_reload_supported": daemon._token_reloader is not None,
            "single_owner_enforced": (
                daemon._dynamic_reconcile
                or daemon._owner_election_supported
            ),
            "observations": [
                daemon._observations[channel_id]
                for channel_id in sorted(daemon._observations)
            ],
            "browser_calls_active": len(daemon._browser_sessions),
            "browser_calls_capacity": daemon._max_browser_calls,
        }
    )
