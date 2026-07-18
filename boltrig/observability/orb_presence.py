"""Desktop-orb presence: mirror the run-event stream into a living background orb.

The beelink desktop runs ``orb-bg`` (Projects/beelink-desktop/orb), a shader wallpaper whose
emotion channel is a tiny CLI: ``orbctl <emotion> [intensity]``. This module makes Boltrig
express itself through it: every run event already fans out through ONE chokepoint,
``EventRelay.publish``, so a subclass overriding that method sees the kernel's full live state
without touching any of the publish call sites.

Enablement is environmental, not configured: the relay upgrades itself only when ``orbctl``
exists on PATH (i.e. this is the desktop box), and ``BOLTRIG_ORB_PRESENCE=0`` force-disables /
``=1`` force-enables. Prod containers have no orbctl and get the plain relay.

Fail-safe by construction: the orb is cosmetic, so nothing here may ever break a run. Every
orbctl invocation is a fire-and-forget subprocess, emotion updates only fire on a CHANGE of
emotion (a text-delta stream is one transition, not a call per token), and any exception is
swallowed. A daemon timer returns the orb to its idle baseline after the stream goes quiet.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Any

from boltrig.kernel.events import EventRelay

# event type -> (emotion, intensity). Types absent here (heartbeat) leave the orb unchanged.
_EMOTION_MAP: dict[str, tuple[str, float]] = {
    "message_start": ("working", 0.9),
    "text_delta": ("thinking", 0.8),
    "tool_call": ("working", 0.9),
    "tool_result": ("working", 0.9),
    "workflow_step": ("working", 0.9),
    "ultracode": ("working", 1.0),
    "subagent": ("excited", 1.0),
    "question": ("alert", 1.0),
    "hitl": ("alert", 1.0),
    "message_end": ("happy", 0.9),
    "cancelled": ("sad", 0.8),
}

_IDLE_AFTER_S = 25.0  # quiet this long -> orbctl auto (idle + time-of-day baseline)


def _enabled() -> bool:
    flag = os.environ.get("BOLTRIG_ORB_PRESENCE", "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    return shutil.which("orbctl") is not None


class OrbPresenceRelay(EventRelay):
    """An EventRelay that also drives the desktop orb's emotion channel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._orb_lock = threading.Lock()
        self._orb_emotion: str | None = None
        self._orb_last_event = 0.0
        self._orb_idle_timer: threading.Timer | None = None

    def publish(self, tenant_id: str, stream_id: str, event: dict[str, Any]) -> None:
        super().publish(tenant_id, stream_id, event)
        try:
            self._orb_react(event)
        except Exception:  # noqa: BLE001 - cosmetic channel, never let it touch a run
            pass

    # --- orb side (never raises) ---
    def _orb_react(self, event: dict[str, Any]) -> None:
        mapped = _EMOTION_MAP.get(str(event.get("type", "")))
        if mapped is None:
            return
        emotion, intensity = mapped
        with self._orb_lock:
            self._orb_last_event = time.monotonic()
            changed = emotion != self._orb_emotion
            self._orb_emotion = emotion
            if self._orb_idle_timer is not None:
                self._orb_idle_timer.cancel()
            self._orb_idle_timer = threading.Timer(_IDLE_AFTER_S, self._orb_idle)
            self._orb_idle_timer.daemon = True
            self._orb_idle_timer.start()
        if changed:
            self._orbctl(emotion, f"{intensity:g}")

    def _orb_idle(self) -> None:
        with self._orb_lock:
            if time.monotonic() - self._orb_last_event < _IDLE_AFTER_S:
                return  # a newer event rescheduled us
            self._orb_emotion = None
        self._orbctl("auto")

    @staticmethod
    def _orbctl(*args: str) -> None:
        try:
            subprocess.Popen(
                ["orbctl", *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            pass


def build_event_relay(*args: Any, **kwargs: Any) -> EventRelay:
    """The kernel's relay factory: the orb-aware relay on a desktop with orbctl, the plain
    relay everywhere else."""
    if _enabled():
        return OrbPresenceRelay(*args, **kwargs)
    return EventRelay(*args, **kwargs)
