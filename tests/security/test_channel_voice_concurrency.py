"""Concurrent browser voice calls are isolated and bounded (SEC-WRK-03)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_GATEWAY_DIR = str(
    Path(__file__).resolve().parents[2] / "services" / "channel_gateway"
)
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402


class _Kernel:
    def __init__(self) -> None:
        self.claims = 0

    async def claim_call_media(self, call_id: str, media_token: str) -> dict[str, Any]:
        self.claims += 1
        return {
            "channel_id": "voice-1",
            "tool_token": f"tools:{media_token}",
            "session_profile": {
                "provider": "xai",
                "model": f"model:{call_id}",
            },
            "call": {"id": call_id},
        }

    async def claim_outbox(self) -> list[dict[str, Any]]:
        return []


class _Adapter(sidecar_app.PlatformAdapter):
    platform = "voice"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.activations: list[tuple[str, str, object]] = []
        self.texts: list[str] = []
        self.inject_started = asyncio.Event()
        self.inject_release: asyncio.Event | None = None
        self.started = False
        self.stopped = False

    async def activate_call(
        self, tool_token: str, call_id: str, session_profile: object
    ) -> None:
        self.activations.append((tool_token, call_id, session_profile))

    async def start(self, on_message) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True
        audio = self.config.get("audio")
        if audio is not None:
            await audio.aclose()

    async def deliver(self, payload: dict[str, Any]) -> None:
        return None

    async def inject_user_text(self, text: str) -> bool:
        self.inject_started.set()
        if self.inject_release is not None:
            await self.inject_release.wait()
        self.texts.append(text)
        return True


async def _until_static_adapter(daemon: sidecar_app.ChannelSidecarDaemon) -> None:
    for _ in range(100):
        if "voice-1" in daemon._adapters:
            return
        await asyncio.sleep(0)
    raise AssertionError("static voice adapter did not start")


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
async def test_browser_voice_calls_are_isolated_bounded_and_released_exactly() -> None:
    kernel = _Kernel()
    adapters: list[_Adapter] = []

    def factory(platform: str, config: dict[str, Any]) -> _Adapter:
        assert platform == "voice"
        adapter = _Adapter(config)
        adapters.append(adapter)
        return adapter

    daemon = sidecar_app.ChannelSidecarDaemon(
        kernel,  # type: ignore[arg-type]
        [
            sidecar_app.ChannelSpec(
                channel_id="voice-1",
                platform="voice",
                secret="not-logged",
                config={"api_key": "also-not-logged"},
            )
        ],
        poll_seconds=60,
        max_browser_calls=2,
        adapter_factory=factory,
    )
    await daemon.start()
    try:
        await _until_static_adapter(daemon)
        static = adapters[0]

        audio_a, _ = await daemon.claim_browser_media("call-a", "media-a")
        audio_b, _ = await daemon.claim_browser_media("call-b", "media-b")
        assert audio_a is not None and audio_b is not None and audio_a is not audio_b

        session_a = daemon._browser_sessions["call-a"]
        session_b = daemon._browser_sessions["call-b"]
        assert session_a.adapter is not session_b.adapter
        assert session_a.adapter is not static and session_b.adapter is not static
        assert session_a.adapter.activations == [  # type: ignore[attr-defined]
            (
                "tools:media-a",
                "call-a",
                {"provider": "xai", "model": "model:call-a"},
            )
        ]
        assert session_b.adapter.activations == [  # type: ignore[attr-defined]
            (
                "tools:media-b",
                "call-b",
                {"provider": "xai", "model": "model:call-b"},
            )
        ]

        with pytest.raises(sidecar_app.BrowserMediaCapacityError):
            await daemon.claim_browser_media("call-c", "media-c")
        assert set(daemon._browser_sessions) == {"call-a", "call-b"}
        assert not session_a.adapter.stopped  # type: ignore[attr-defined]
        assert not session_b.adapter.stopped  # type: ignore[attr-defined]

        await daemon.release_browser_media("call-a")
        assert session_a.adapter.stopped  # type: ignore[attr-defined]
        assert not session_b.adapter.stopped  # type: ignore[attr-defined]
        assert set(daemon._browser_sessions) == {"call-b"}

        audio_c, _ = await daemon.claim_browser_media("call-c", "media-c-rotated")
        assert audio_c is not None
        assert set(daemon._browser_sessions) == {"call-b", "call-c"}
        assert not session_b.adapter.stopped  # type: ignore[attr-defined]

        # A newly redeemed bearer for the same call replaces exactly that
        # generation. Its old WebSocket may finish cleanup later, but the bridge
        # identity fence prevents that cleanup from stopping the replacement.
        old_b_audio = session_b.audio
        replacement_b, _ = await daemon.claim_browser_media(
            "call-b", "media-b-rotated"
        )
        assert replacement_b is not None and replacement_b is not old_b_audio
        assert session_b.adapter.stopped  # type: ignore[attr-defined]
        current_b = daemon._browser_sessions["call-b"]
        await daemon.release_browser_media("call-b", old_b_audio)
        assert daemon._browser_sessions["call-b"] is current_b
        assert not current_b.adapter.stopped  # type: ignore[attr-defined]
        await daemon.release_browser_media("call-b", replacement_b)
        assert "call-b" not in daemon._browser_sessions
        assert current_b.adapter.stopped  # type: ignore[attr-defined]
    finally:
        await daemon.stop()


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
async def test_browser_user_text_reaches_only_its_own_call_session() -> None:
    kernel = _Kernel()
    adapters: list[_Adapter] = []

    def factory(platform: str, config: dict[str, Any]) -> _Adapter:
        adapter = _Adapter(config)
        adapters.append(adapter)
        return adapter

    daemon = sidecar_app.ChannelSidecarDaemon(
        kernel,  # type: ignore[arg-type]
        [
            sidecar_app.ChannelSpec(
                channel_id="voice-1",
                platform="voice",
                secret="not-logged",
                config={"api_key": "also-not-logged"},
            )
        ],
        poll_seconds=60,
        adapter_factory=factory,
    )
    await daemon.start()
    try:
        await _until_static_adapter(daemon)
        static = adapters[0]
        audio_a, _ = await daemon.claim_browser_media("call-a", "media-a")
        audio_b, _ = await daemon.claim_browser_media("call-b", "media-b")
        assert audio_a is not None and audio_b is not None

        assert await daemon.inject_browser_text(
            "call-b", audio_b, "typed mid-call"
        ) is True
        session_a = daemon._browser_sessions["call-a"]
        session_b = daemon._browser_sessions["call-b"]
        assert session_b.adapter.texts == ["typed mid-call"]  # type: ignore[attr-defined]
        assert session_a.adapter.texts == []  # type: ignore[attr-defined]
        assert static.texts == []

        # An unknown or already-released call id has nowhere to land.
        assert await daemon.inject_browser_text(
            "call-gone", audio_b, "nobody home"
        ) is False

        # Replacement cannot race an already-authorized provider write between
        # its generation check and use: claim waits for the exact injection.
        stale_b = audio_b
        old_adapter = session_b.adapter
        old_adapter.inject_started.clear()  # type: ignore[attr-defined]
        old_adapter.inject_release = asyncio.Event()  # type: ignore[attr-defined]
        in_flight = asyncio.create_task(daemon.inject_browser_text(
            "call-b", stale_b, "authorized before reconnect"
        ))
        await old_adapter.inject_started.wait()  # type: ignore[attr-defined]
        replacement_task = asyncio.create_task(daemon.claim_browser_media(
            "call-b", "media-b-rotated"
        ))
        await asyncio.sleep(0)
        assert not replacement_task.done()
        assert await asyncio.wait_for(
            daemon.inject_browser_text("call-a", audio_a, "parallel call"),
            timeout=1,
        ) is True
        assert session_a.adapter.texts == ["parallel call"]  # type: ignore[attr-defined]
        old_adapter.inject_release.set()  # type: ignore[attr-defined]
        assert await in_flight is True
        current_b, _ = await replacement_task
        assert current_b is not None and current_b is not stale_b

        # Once replaced, a queued frame from the old authenticated WebSocket
        # must not reach the current provider, even though its call id is equal.
        assert old_adapter.texts == [  # type: ignore[attr-defined]
            "typed mid-call",
            "authorized before reconnect",
        ]
        replacement = daemon._browser_sessions["call-b"]
        assert await daemon.inject_browser_text(
            "call-b", stale_b, "stale generation"
        ) is False
        assert replacement.adapter.texts == []  # type: ignore[attr-defined]
        assert await daemon.inject_browser_text(
            "call-b", current_b, "current generation"
        ) is True
        assert replacement.adapter.texts == [  # type: ignore[attr-defined]
            "current generation"
        ]
    finally:
        await daemon.stop()
