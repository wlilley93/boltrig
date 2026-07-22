"""xAI Realtime voice adapter for the channel gateway (decision 0003).

A "voice" platform channel: the adapter holds the OpenAI-Realtime-compatible
speech-to-speech WebSocket to xAI (``wss://api.x.ai/v1/realtime``) and turns a
voice utterance into a governed work item, exactly like any other socket-class
platform port (see ADDING_A_PLATFORM.md - every binding condition applies).

The ONE hard rule of this port (fail-closed): the xAI session's tool list
contains ONLY ``type: "function"`` entries, and those are GENERATED from the
caller's capability set - discovered over the kernel's MCP face
(``POST /v1/mcp`` ``tools/list`` on the run-scoped token, so the list is
already tenant-ceiling ∩ run-grants scoped kernel-side). xAI's server-side
tools (``web_search`` / ``x_search`` / remote ``mcp``) execute OUTSIDE the
chokepoint on xAI's infrastructure, so a config that injects ANY tool entry is
REJECTED at adapter init - session.tools is kernel-owned, never config-owned.
Every ``response.function_call_arguments.done`` event is forwarded back through
``POST /v1/mcp`` ``tools/call`` (the same run-scoped token seam), so a
voice-triggered action runs the unchanged dispatch order - grant check, HITL,
rate limit, kernel-side credential resolution, audit - and the result returns
to the session as a ``function_call_output`` item.

Egress (condition 2): the adapter dials exactly ONE host, checked with
``egress.egress_refusal`` before connecting - add ``api.x.ai`` to
``CHANNEL_GATEWAY_EGRESS_ALLOW``. The kernel link rides the daemon's own
client.

Secrets (condition 7): ``api_key`` (the xAI key, resolved kernel-side by the
operator and handed to the spawn environment) and the run-scoped kernel token
arrive via ``config``/env at spawn and are NEVER logged - log lines and errors
name token TYPES only.

Inbound normalisation: a completed input transcription
(``conversation.item.input_audio_transcription.completed``) becomes
``{"id": <item_id>, "sender": <configured speaker>, "text": <transcript>,
"thread": <configured thread>}``. xAI's per-item id is the stable delivery id
feeding the kernel's durable replay dedup. ``sender`` is the operator-bound
external user id (a voice box has one physical speaker identity; the kernel's
binding rows map it to a Principal). ``thread`` is the COMPLETE deliver target
- one local playback endpoint, so it is a constant from config and ``deliver``
ignores the target's content.

Outbound: ``deliver({"text", "target"})`` asks the live session to speak the
governed reply (``response.create`` with a verbatim-speak instruction); the
synthesised audio streams back as ``response.output_audio.delta`` events into
the local audio-out seam. No live session -> AdapterDeliveryError -> the
kernel retries with backoff.

Barge-in: server VAD emits ``input_audio_buffer.speech_started`` when the
human talks over playback; the adapter interrupts the local audio-out seam and
cancels the in-flight response so playback stops NOW.

The local audio seam (no hardcoded sound card): ``LocalAudio`` is the
pluggable mic/speaker interface - ``read_frame`` (mic -> session),
``write_frame`` (session -> speaker), ``interrupt`` (barge-in). The default
``NullAudio`` discards output and never produces input (the adapter is then a
text-transcript surface driven by injected/server events only - the test
mode). ``QueueAudio`` is the in-process loopback used by the round-trip test.
A REAL device plugs in by passing ``config["audio"]``: a sounddevice/pyaudio
implementation on a workstation, or the hey-nabu box bridging its mic/speaker
(e.g. over the generic custom-interface adapter) into this seam. No audio
dependency enters requirements.in - websockets + httpx suffice.

SEVERED: no ``boltrig.*`` imports (SEC-28, machine-enforced).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
from typing import Any

import websockets

from adapters import AdapterDeliveryError, OnMessage, PlatformAdapter, register_adapter
from egress import egress_refusal
from kernel_client import KernelClient

log = logging.getLogger("channel_gateway.xai_voice")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_KERNEL_URL_ENV = "BOLTRIG_KERNEL_URL"
_TOKEN_ENV = "CHANNEL_GATEWAY_TOKEN"

_DEFAULT_REALTIME_URL = "wss://api.x.ai/v1/realtime"
_AUDIO_FORMAT = {"type": "audio/pcm", "rate": 24000}
_MAX_FRAME_CHARS = 1_000_000  # a malformed/garbage audio delta is dropped, not played

_RECONNECT_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0

# Config keys that must never carry tool definitions: session.tools is
# kernel-generated ONLY (see the module docstring). Any entry fails init.
_TOOL_CONFIG_KEYS = ("tools", "server_tools", "xai_tools", "builtin_tools")

_DEFAULT_INSTRUCTIONS = (
    "You are the Boltrig voice surface. Answer briefly. You act ONLY through "
    "the provided functions; every function call is dispatched and audited by "
    "the Boltrig kernel."
)


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _reject_config_tools(config: dict[str, Any]) -> None:
    """Fail closed at init: session.tools is generated from the kernel's
    granted-verb discovery ONLY. A config-injected tool list - above all an
    xAI SERVER-SIDE tool (web_search / x_search / remote mcp), which would
    execute outside the chokepoint - is refused outright."""
    for key in _TOOL_CONFIG_KEYS:
        entries = config.get(key)
        if not entries:
            continue
        kinds = sorted({
            str(e.get("type") or "?") for e in entries if isinstance(e, dict)
        })
        raise ValueError(
            f"xai_voice adapter owns session.tools (kernel-discovered function "
            f"tools only); refusing config key '{key}' (types: {', '.join(kinds)})"
        )


def _mangle(verb: str) -> str:
    """Realtime function names forbid dots; map verb ids 1:1 to safe names."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", verb)


class LocalAudio:
    """The pluggable mic/speaker seam (see the module docstring)."""

    async def read_frame(self) -> bytes | None:
        """One mic PCM frame, or None when no input is available/ever comes."""
        raise NotImplementedError

    async def write_frame(self, frame: bytes) -> None:
        """Play one PCM frame from the session."""
        raise NotImplementedError

    async def interrupt(self) -> None:
        """Barge-in: drop every queued/not-yet-played frame NOW."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release the device. Default: nothing to release."""


class NullAudio(LocalAudio):
    """The default seam: no mic, playback discarded. The adapter still works
    as a transcript surface (server events drive it); tests inject audio by
    subclassing or by driving the fake realtime server directly."""

    async def read_frame(self) -> bytes | None:
        await asyncio.sleep(3600)  # cancelled by stop(); never produces input
        return None

    async def write_frame(self, frame: bytes) -> None:
        return None

    async def interrupt(self) -> None:
        return None


class QueueAudio(LocalAudio):
    """In-process loopback seam (tests, and the shape a real device mirrors):
    mic frames are fed with ``feed_mic``; played frames collect in ``played``;
    ``interrupted`` counts barge-ins."""

    def __init__(self) -> None:
        self.mic: asyncio.Queue[bytes] = asyncio.Queue()
        self.played: list[bytes] = []
        self.interrupted = 0

    def feed_mic(self, frame: bytes) -> None:
        self.mic.put_nowait(frame)

    async def read_frame(self) -> bytes | None:
        return await self.mic.get()

    async def write_frame(self, frame: bytes) -> None:
        self.played.append(frame)

    async def interrupt(self) -> None:
        self.interrupted += 1
        self.played.clear()


@register_adapter
class XaiVoiceAdapter(PlatformAdapter):
    """xAI Realtime voice port of the PlatformAdapter contract.

    Config (all injected at spawn; ``api_key`` is a secret, NEVER logged):
      ``api_key``       the xAI API key (console.x.ai)
      ``realtime_url``  the realtime WSS (default wss://api.x.ai/v1/realtime;
                        a test points it at a fake in-proc server)
      ``model``         realtime model, appended as the ?model= query when set
      ``voice``         session voice (optional; xAI default when unset)
      ``instructions``  session system instructions (optional)
      ``speaker``       the external user id transcripts are attributed to
                        (bound kernel-side to a Principal; default "voice-user")
      ``thread``        the deliver target stamped on intake (default
                        "voice:local"; one local playback endpoint)
      ``kernel_client`` an injectable KernelClient (tests); otherwise built
                        from ``kernel_url``/``token`` or the standard env
      ``audio``         a LocalAudio implementation (default NullAudio)
      ``egress_allow``  host set for the egress guard (default: the
                        CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn)
    """

    platform = "voice"

    def __init__(self, config: dict[str, Any]) -> None:
        _reject_config_tools(config)  # fail closed BEFORE anything else
        self._api_key = str(config.get("api_key") or "")
        if not self._api_key:
            raise ValueError("xai_voice adapter config needs api_key")
        self._realtime_url = str(
            config.get("realtime_url") or _DEFAULT_REALTIME_URL
        ).rstrip("/")
        self._model = str(config.get("model") or "")
        self._voice = str(config.get("voice") or "")
        self._instructions = str(config.get("instructions") or _DEFAULT_INSTRUCTIONS)
        self._speaker = str(config.get("speaker") or "voice-user")
        self._thread = str(config.get("thread") or "voice:local")
        allow = config.get("egress_allow")
        self._egress_allow = (
            {str(h).strip().lower() for h in allow if str(h).strip()}
            if allow is not None
            else _env_egress_allow()
        )
        self._audio: LocalAudio = config.get("audio") or NullAudio()
        self._kernel: KernelClient | None = config.get("kernel_client")
        if self._kernel is None:
            kernel_url = str(
                config.get("kernel_url")
                or os.environ.get(_KERNEL_URL_ENV, "http://localhost:8000")
            )
            token = config.get("token") or os.environ.get(_TOKEN_ENV)
            self._kernel = KernelClient(kernel_url, token)
            self._owns_kernel = True
        else:
            self._owns_kernel = False
        self._ws: Any = None
        self._on_message: OnMessage | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._tool_names: dict[str, str] = {}  # mangled function name -> verb id
        self._responding = False

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Open the realtime session; return once the socket is UP and the
        session is configured. The receive/reconnect and mic loops run in
        adapter-owned tasks afterwards."""
        self._on_message = on_message
        self._stopping.clear()
        await self._connect_once()  # raises: the daemon retries with backoff
        self._tasks.append(asyncio.create_task(self._supervise_loop()))
        self._tasks.append(asyncio.create_task(self._mic_loop()))

    async def stop(self) -> None:
        """Idempotent: safe to call twice, never hangs shutdown."""
        self._stopping.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._close_ws()
        await self._audio.aclose()
        if self._owns_kernel and self._kernel is not None:
            await self._kernel.aclose()
            self._kernel = None

    # --- the connection ----------------------------------------------------
    async def _connect_once(self) -> None:
        """Discover the caller's function tools from the kernel, then open the
        WSS and configure the session. Egress-checked before ANY dial; the
        api_key never appears in logs or errors."""
        tools = await self._discover_tools()
        url = self._realtime_url
        if self._model:
            url = f"{url}?model={self._model}"
        refusal = egress_refusal(url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"xai realtime egress-refused: {refusal}")
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                ping_interval=20,
                ping_timeout=20,
            )
        except Exception as exc:
            raise RuntimeError(
                f"realtime connect failed: {type(exc).__name__}"
            ) from exc
        await self._send({
            "type": "session.update",
            "session": self._session_config(tools),
        })
        log.info("xai realtime session connected (%d kernel tools)", len(tools))

    def _session_config(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """The nested audio session schema (the legacy flat fields are silently
        ignored by xAI). ``turn_detection`` is server VAD so utterance
        boundaries and barge-in are detected server-side."""
        output: dict[str, Any] = {"format": dict(_AUDIO_FORMAT)}
        if self._voice:
            output["voice"] = self._voice
        return {
            "type": "realtime",
            "instructions": self._instructions,
            "audio": {
                "input": {
                    "format": dict(_AUDIO_FORMAT),
                    "turn_detection": {"type": "server_vad"},
                },
                "output": output,
            },
            "tools": tools,
        }

    async def _discover_tools(self) -> list[dict[str, Any]]:
        """``tools/list`` over the run-scoped MCP token: the kernel answers with
        the caller's granted verbs ONLY, so the session can never name a tool
        the chokepoint would refuse. Every entry is a client-side function."""
        assert self._kernel is not None
        response = await self._kernel.mcp_call("tools/list", {})
        raw = (response.get("result") or {}).get("tools") or []
        tools: list[dict[str, Any]] = []
        self._tool_names = {}
        for entry in raw:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            verb = str(entry["name"])
            mangled = _mangle(verb)
            if mangled in self._tool_names:
                log.warning("tool name collision on %s; skipped", mangled)
                continue
            self._tool_names[mangled] = verb
            tools.append({
                "type": "function",
                "name": mangled,
                "description": str(entry.get("description") or verb),
                "parameters": entry.get("inputSchema") or {"type": "object"},
            })
        return tools

    async def _supervise_loop(self) -> None:
        """The adapter-owned receive/reconnect loop (the daemon only supervises
        start failures): run until the socket drops, then re-open - and
        re-configure the session - with backoff until stop() is called."""
        backoff = _RECONNECT_SECONDS
        while not self._stopping.is_set():
            try:
                await self._receive_loop()
                backoff = _RECONNECT_SECONDS  # a clean disconnect: reconnect now
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any drop reconnects
                log.warning("xai realtime dropped (%s); reconnecting", type(exc).__name__)
            await self._close_ws()
            if self._stopping.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
            if self._stopping.is_set():
                break
            try:
                await self._connect_once()
            except Exception as exc:  # noqa: BLE001 - keep retrying inside
                log.warning("xai realtime reconnect failed (%s)", type(exc).__name__)

    async def _receive_loop(self) -> None:
        """Read session events until the socket closes."""
        async for raw in self._ws:
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue  # a malformed frame is dropped, never fatal
            if isinstance(event, dict):
                await self._handle_event(event)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        etype = str(event.get("type") or "")
        if etype == "conversation.item.input_audio_transcription.completed":
            await self._ingest_transcript(event)
        elif etype in ("response.output_audio.delta", "response.audio.delta"):
            self._responding = True
            await self._play_delta(event)
        elif etype == "response.function_call_arguments.done":
            await self._forward_function_call(event)
        elif etype == "input_audio_buffer.speech_started":
            await self._barge_in()
        elif etype == "response.done":
            self._responding = False
        elif etype == "error":
            # xAI error payloads carry no secrets; log the code, never the key.
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            log.warning("xai realtime error event (%s)", error.get("code") or "unknown")

    # --- link (a): transcripts in -------------------------------------------
    async def _ingest_transcript(self, event: dict[str, Any]) -> None:
        transcript = str(event.get("transcript") or "").strip()
        item_id = str(event.get("item_id") or "")
        if not transcript or not item_id:
            # Without the stable item id the kernel cannot dedup replays;
            # an empty transcript is not human input. Drop loud.
            log.warning("xai transcript event dropped (id/transcript missing)")
            return
        if self._on_message is not None:
            await self._on_message({
                "id": item_id,
                "sender": self._speaker,
                "text": transcript,
                "thread": self._thread,
            })

    # --- audio out + barge-in -------------------------------------------------
    async def _play_delta(self, event: dict[str, Any]) -> None:
        delta = str(event.get("delta") or "")
        if not delta or len(delta) > _MAX_FRAME_CHARS:
            return
        try:
            frame = base64.b64decode(delta)
        except Exception:  # noqa: BLE001 - a bad frame is dropped, not played
            return
        await self._audio.write_frame(frame)

    async def _barge_in(self) -> None:
        """The human talked over playback (server VAD): stop local playback NOW
        and cancel the in-flight response so nothing stale keeps speaking."""
        await self._audio.interrupt()
        if self._responding:
            self._responding = False
            await self._send({"type": "response.cancel"})

    # --- function calls: every one rides the chokepoint -----------------------
    async def _forward_function_call(self, event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id") or "")
        verb = self._tool_names.get(str(event.get("name") or ""))
        if not call_id or verb is None:
            log.warning("xai function call dropped (unknown name or no call_id)")
            return
        arguments = event.get("arguments")
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            if not isinstance(args, dict):
                raise ValueError("arguments not an object")
        except (TypeError, ValueError):
            args = {}
        output = await self._call_kernel_tool(verb, args)
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            },
        })
        await self._send({"type": "response.create"})

    async def _call_kernel_tool(self, verb: str, args: dict[str, Any]) -> str:
        """``tools/call`` over the run-scoped MCP token - the SAME chokepoint as
        every other caller (SEC-26): grant check, HITL, rate limit, kernel-side
        credential resolution, audit. The result (or the refusal) is what the
        session hears."""
        assert self._kernel is not None
        try:
            response = await self._kernel.mcp_call(
                "tools/call", {"name": verb, "arguments": args}
            )
        except Exception as exc:  # noqa: BLE001 - the session needs an answer
            return json.dumps({"status": "error", "reason": type(exc).__name__})
        result = response.get("result")
        if isinstance(result, dict):
            content = result.get("content") or []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text") or "")
            return json.dumps(result)
        error = response.get("error")
        if isinstance(error, dict):
            return json.dumps({"status": "error", "reason": error.get("message")})
        return json.dumps({"status": "error", "reason": "empty kernel response"})

    # --- link (b): outbound --------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """Speak one ``channel.send`` payload through the live session. The
        governed text is injected as a verbatim-speak response; the audio
        streams back into the local audio-out seam. ``target`` names the one
        local playback endpoint and needs no parsing."""
        text = str(payload.get("text") or "")
        if not text:
            raise AdapterDeliveryError("deliver payload needs text")
        if self._ws is None:
            raise AdapterDeliveryError("no live realtime session to speak through")
        try:
            await self._send({
                "type": "response.create",
                "response": {
                    "modalities": ["audio", "text"],
                    "instructions": (
                        "Speak the following to the user exactly as written, "
                        f"then stop: {text}"
                    ),
                },
            })
        except Exception as exc:  # noqa: BLE001 - any send failure retries
            raise AdapterDeliveryError(
                f"realtime speak failed: {type(exc).__name__}"
            ) from exc

    # --- mic in ----------------------------------------------------------------
    async def _mic_loop(self) -> None:
        """Pump mic frames from the local audio seam into the input buffer.
        NullAudio never produces a frame, so this idles until cancelled."""
        while not self._stopping.is_set():
            try:
                frame = await self._audio.read_frame()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a dead mic must not kill the session
                log.warning("audio input seam failed (%s)", type(exc).__name__)
                return
            if frame is None:
                continue
            if self._ws is not None:
                await self._send({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(frame).decode("ascii"),
                })

    # --- helpers ---------------------------------------------------------------
    async def _send(self, event: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(event))

    async def _close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
