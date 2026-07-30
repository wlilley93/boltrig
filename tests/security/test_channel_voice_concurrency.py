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
