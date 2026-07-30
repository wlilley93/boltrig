"""Bounded browser media bridge for one isolated realtime voice call.

The bridge is deliberately ephemeral: PCM frames live only in bounded queues
and WebSocket writes. It persists normalized text/lifecycle events through the
kernel client, never audio bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import WebSocket

_MAX_PCM_FRAME_BYTES = 64 * 1024
_MAX_QUEUED_FRAMES = 64


class BrowserAudio:
    """Duck-types xai_voice_adapter.LocalAudio without importing Boltrig."""

    def __init__(self, kernel: Any) -> None:
        self._kernel = kernel
        self._mic: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_MAX_QUEUED_FRAMES)
        self._socket: WebSocket | None = None
        self._call_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def call_id(self) -> str | None:
        return self._call_id

    async def attach(self, call_id: str, socket: WebSocket) -> bool:
        async with self._lock:
            if self._socket is not None:
                return False
            self._socket = socket
            self._call_id = call_id
            self._drain_mic()
            return True

    async def detach(self, call_id: str, *, retain_call: bool = False) -> None:
        async with self._lock:
            if self._call_id != call_id:
                return
            self._socket = None
            if not retain_call:
                self._call_id = None
            self._drain_mic()
        with contextlib.suppress(Exception):
            await self._kernel.append_call_event(
                call_id,
                "participant_left",
                {"reason": "media_disconnected"},
                participant_id="user",
            )
        with contextlib.suppress(Exception):
            await self._kernel.set_call_state(call_id, "reconnecting")

    def feed_mic(self, frame: bytes) -> bool:
        if self._socket is None or not frame or len(frame) > _MAX_PCM_FRAME_BYTES:
            return False
        if self._mic.full():
            # Latency is safer than completeness for live voice: discard the
            # oldest unplayed frame rather than building an unbounded backlog.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._mic.get_nowait()
        self._mic.put_nowait(bytes(frame))
        return True

    async def read_frame(self) -> bytes | None:
        return await self._mic.get()

    async def write_frame(self, frame: bytes) -> None:
        socket = self._socket
        if socket is None or not frame or len(frame) > _MAX_PCM_FRAME_BYTES:
            return
        with contextlib.suppress(Exception):
            await socket.send_bytes(frame)

    async def interrupt(self) -> None:
        await self.emit_event("interrupted", {"reason": "barge_in"})

    async def emit_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        participant_id: str | None = None,
    ) -> bool:
        call_id = self._call_id
        if call_id is None:
            return False
        # Persist first so a browser drop cannot erase the normalized event.
        persisted = False
        canonical_event: dict[str, Any] | None = None
        try:
            result = await self._kernel.append_call_event(
                call_id, event_type, payload, participant_id=participant_id
            )
            persisted = True
            if isinstance(result, dict) and isinstance(result.get("event"), dict):
                canonical_event = dict(result["event"])
        except Exception:
            pass
        socket = self._socket
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.send_json(
                    {
                        "type": "call_event",
                        "event": canonical_event or {
                            "call_id": call_id,
                            "type": event_type,
                            "participant_id": participant_id,
                            "payload": payload,
                        },
                    }
                )
        return persisted

    async def aclose(self) -> None:
        socket = self._socket
        self._socket = None
        self._call_id = None
        self._drain_mic()
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close(code=1001)

    def _drain_mic(self) -> None:
        while True:
            try:
                self._mic.get_nowait()
            except asyncio.QueueEmpty:
                return
