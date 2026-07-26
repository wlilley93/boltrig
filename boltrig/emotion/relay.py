"""Emotion relay: the affective side-channel tapped off the kernel's event stream.

Supersedes the old orb-presence writer, which the same commit deleted. Every run event already fans out
through ONE chokepoint, ``EventRelay.publish``, so a subclass overriding that method sees
the kernel's full live state without touching any publish call site. Matched events are
appraised into a per-tenant :class:`EmotionEngine` (pure math, ``boltrig/emotion/engine.py``)
via data-driven rules loaded from ``libraries/emotion`` (EMO-5). Emotion is strictly
downstream of dispatch (EMO-1): nothing here can influence grant checks, HITL, or dispatch,
and every exception in the emotion path is swallowed (P9) - the channel is cosmetic and
must never break a run.

Threading ground truth: ``publish`` always runs on the asyncio loop thread, so ``_react``
is pure math and dict ops under one lock. All steady-state file I/O happens on the daemon
publisher thread: the phenotype file every ``publish_interval`` seconds and the tenant
state file every 20th tick, both written atomically (tmp + ``os.replace``). The single
READ of the persisted state file happens once at construction, before any traffic.

Enablement is environmental, not configured: ``BOLTRIG_EMOTION=0`` force-disables,
``=1`` force-enables, otherwise the relay upgrades itself only when ``orbctl`` exists on
PATH (i.e. this is the desktop box). Prod containers get the plain relay.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from boltrig.emotion.engine import EmotionEngine, EmotionModel
from boltrig.emotion.tables import EventRule, load_emotion_tables
from boltrig.kernel.events import EventRelay

_STATE_EVERY_TICKS = 20  # persist tenant snapshots every Nth publisher tick


class EmotionRelay(EventRelay):
    """An EventRelay that also runs the affective projection (downstream-only, P9)."""

    def __init__(
        self,
        *args: Any,
        model: EmotionModel,
        rules: Sequence[EventRule],
        phenotype_path: Path,
        state_path: Path | None,
        tenant: str = "default",
        publish_interval: float = 0.5,
        autostart: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._model = model
        self._rules = list(rules)
        self._phenotype_path = phenotype_path
        self._state_path = state_path
        self._tenant = tenant
        self._publish_interval = publish_interval
        # one lock guards the engines map and every engine mutation (EMO-4: keyed per tenant)
        self._engines: dict[str, EmotionEngine] = {}
        self._engines_lock = threading.Lock()
        self._saved: dict[str, Mapping[str, object]] = self._load_saved(state_path)
        self._throttle: dict[tuple[str, str], float] = {}
        self._tick = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if autostart:
            self.start()

    @staticmethod
    def _load_saved(state_path: Path | None) -> dict[str, Mapping[str, object]]:
        """The one construction-time read: tenant snapshots persisted by a prior process."""
        saved: dict[str, Mapping[str, object]] = {}
        if state_path is None:
            return saved
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            tenants = raw.get("tenants") if isinstance(raw, dict) else None
            if isinstance(tenants, dict):
                for tid, snap in tenants.items():
                    if isinstance(tid, str) and isinstance(snap, dict):
                        saved[tid] = snap
        except Exception:  # noqa: BLE001 - cosmetic channel, never let it touch a run
            pass
        return saved

    def publish(self, tenant_id: str, stream_id: str, event: dict[str, Any]) -> None:
        super().publish(tenant_id, stream_id, event)
        try:
            self._react(tenant_id, event)
        except Exception:  # noqa: BLE001 - cosmetic channel, never let it touch a run
            pass

    # --- emotion side (loop thread; pure math + dict ops, no I/O) ---
    def _react(self, tenant_id: str, event: Mapping[str, Any]) -> None:
        rule = self._match(event)
        if rule is None:
            return
        if rule.throttle_s > 0:
            key = (tenant_id, rule.appraise)
            mono = time.monotonic()
            last = self._throttle.get(key)
            if last is not None and mono - last < rule.throttle_s:
                return
            self._throttle[key] = mono
        now = time.time()
        with self._engines_lock:
            self._engine_for(tenant_id, now).appraise(rule.appraise, rule.intensity, now)

    def _match(self, event: Mapping[str, Any]) -> EventRule | None:
        """First matching rule wins (the event_map.yaml order is the precedence)."""
        for rule in self._rules:
            if rule.type != event.get("type"):
                continue
            if any(event.get(k) != v for k, v in rule.where.items()):
                continue
            if any(event.get(k) == v for k, v in rule.where_not.items()):
                continue
            if any(not event.get(field) for field in rule.has):
                continue
            return rule
        return None

    def _engine_for(self, tenant_id: str, now: float) -> EmotionEngine:
        """The tenant's engine, created lazily and restored from the persisted snapshot
        when one exists. Callers hold ``_engines_lock``."""
        engine = self._engines.get(tenant_id)
        if engine is None:
            snap = self._saved.pop(tenant_id, None)
            if snap is not None:
                engine = EmotionEngine.restore(self._model, snap, now)
            else:
                engine = EmotionEngine(self._model, now)
            self._engines[tenant_id] = engine
        return engine

    # --- publisher thread (the ONLY place that touches the filesystem after init) ---
    def start(self) -> None:
        """Start the daemon publisher thread (no-op when already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="boltrig-emotion-publisher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the publisher thread (tests + shutdown hygiene)."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.wait(self._publish_interval):
            self._tick += 1
            try:
                self._publish_once(self._tick)
            except Exception:  # noqa: BLE001 - cosmetic channel, never let it touch a run
                pass

    def _publish_once(self, tick: int) -> None:
        """One publisher beat: write the phenotype file; every Nth beat, the state file."""
        now = time.time()
        with self._engines_lock:
            engine = self._engines.get(self._tenant)
            if engine is None and len(self._engines) == 1:
                engine = next(iter(self._engines.values()))
            phenotype = None if engine is None else engine.phenotype(now)
            snapshots: dict[str, dict[str, object]] | None = None
            if tick % _STATE_EVERY_TICKS == 0:
                snapshots = {tid: eng.snapshot(now) for tid, eng in self._engines.items()}
        if phenotype is not None:
            self._write_json(self._phenotype_path, {"v": 1, "ts": now, "phenotype": phenotype})
        if snapshots is not None and self._state_path is not None:
            self._write_json(self._state_path, {"v": 1, "tenants": snapshots})

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        """Atomic write: tmp file in the same directory, then ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)


def _enabled() -> bool:
    flag = os.environ.get("BOLTRIG_EMOTION", "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    return shutil.which("orbctl") is not None


def build_event_relay(*args: Any, **kwargs: Any) -> EventRelay:
    """The kernel's relay factory: the emotion relay when the add-on is enabled and its
    data tables load, the plain relay everywhere else (fail-safe, P9)."""
    try:
        if not _enabled():
            return EventRelay(*args, **kwargs)
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
        if not runtime_dir:
            return EventRelay(*args, **kwargs)
        tables = load_emotion_tables()
        if tables is None:
            return EventRelay(*args, **kwargs)
        model, rules = tables
        state_home = os.environ.get("XDG_STATE_HOME", "").strip() or str(
            Path.home() / ".local" / "state"
        )
        return EmotionRelay(
            *args,
            model=model,
            rules=rules,
            phenotype_path=Path(runtime_dir) / "boltrig-phenotype.json",
            state_path=Path(state_home) / "boltrig" / "emotion-state.json",
            **kwargs,
        )
    except Exception:  # noqa: BLE001 - the emotion path must never break kernel bring-up
        return EventRelay(*args, **kwargs)
