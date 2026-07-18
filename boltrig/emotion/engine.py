"""The pure affective engine: emotions, needs, mood and tension over time (EMO-3).

A small dynamical system ported from the Atrophy donor prototype. State is
fourteen emotions (0..1), eight needs (0..10), a P/A/D mood vector and a
tension scalar. Time only ever enters through the ``now`` arguments; the module
imports no clock, no I/O and no randomness, so the same inputs always produce
the same state (EMO-3). Everything upstream of it (event matching, throttling,
persistence, threads) lives in :mod:`boltrig.emotion.relay`.

The model carries half-lives and decay constants in HOURS verbatim; ``tempo``
rescales them at run time (default 60.0: one model-hour passes per real
minute). Tension is the exception: it decays with a REAL 1.4 s half-life and is
never tempo-scaled. State is keys and numbers only, never message content
(EMO-2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _as_float(value: object, default: float) -> float:
    """A finite float from an untrusted snapshot field, else ``default``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = float(value)
        if math.isfinite(f):
            return f
    return default


@dataclass(frozen=True)
class Appraisal:
    """One appraisal kind's deltas: emotion deltas, need deltas and a tension kick.

    Deltas are scaled by the caller's intensity at appraise time. The table
    itself is data loaded from ``libraries/emotion/appraisals.yaml`` (EMO-5).
    """

    emotions: Mapping[str, float]
    needs: Mapping[str, float]
    tension: float = 0.0


@dataclass(frozen=True)
class EmotionModel:
    """The canonical model data: baselines, time constants and the appraisal table.

    ``baselines`` and ``half_lives_h`` are keyed by emotion name;
    ``need_defaults`` and ``need_decay_h`` by need name. Hours are carried
    verbatim from the donor data; ``tempo`` divides them into real seconds.
    """

    baselines: Mapping[str, float]
    half_lives_h: Mapping[str, float]
    need_defaults: Mapping[str, float]
    need_decay_h: Mapping[str, float]
    appraisals: Mapping[str, Appraisal] = field(default_factory=dict)
    tempo: float = 60.0


class EmotionEngine:
    """Deterministic emotion state advanced only by explicit timestamps (EMO-3).

    All mutation goes through :meth:`tick` and :meth:`appraise`; both take
    ``now`` as epoch seconds and never read a clock. One engine holds ONE
    tenant's state; tenant scoping is the relay's job (EMO-4).
    """

    def __init__(self, model: EmotionModel, now: float) -> None:
        self._model = model
        self._emotions: dict[str, float] = {
            name: _clamp01(value) for name, value in model.baselines.items()
        }
        self._needs: dict[str, float] = {
            name: _clamp(value, 0.0, 10.0) for name, value in model.need_defaults.items()
        }
        self._mood: dict[str, float] = {"p": 0.55, "a": 0.4, "d": 0.5}
        self._tension = 0.0
        self._last_updated = now

    # -- internal helpers ------------------------------------------------------

    def _emo(self, name: str) -> float:
        return self._emotions.get(name, 0.0)

    def _push_emotion(self, name: str, delta: float) -> None:
        """Add ``delta`` to an emotion if the model defines it, clamped to 0..1."""
        if name in self._emotions:
            self._emotions[name] = _clamp01(self._emotions[name] + delta)

    # -- dynamics --------------------------------------------------------------

    def tick(self, now: float) -> None:
        """Advance state to ``now``: decay, need pressure, then the mood integrator."""
        dt = now - self._last_updated
        self._last_updated = now
        if dt <= 0.0:
            return  # never decay backwards; a stale clock is a no-op
        tempo = self._model.tempo if self._model.tempo > 0.0 else 60.0

        # Emotion decay toward a mood-biased baseline:
        # base_eff = clamp01(base + (P - 0.5) * 0.16); half-life tempo-scaled.
        pleasure = self._mood["p"]
        for name in self._emotions:
            base = self._model.baselines.get(name, 0.0)
            base_eff = _clamp01(base + (pleasure - 0.5) * 0.16)
            hl_s = self._model.half_lives_h.get(name, 1.0) * 3600.0 / tempo
            value = self._emotions[name]
            if hl_s > 0.0:
                value = base_eff + (value - base_eff) * math.pow(0.5, dt / hl_s)
            self._emotions[name] = _clamp01(value)

        # Need decay TOWARD ZERO, tempo-scaled, clamped 0..10.
        for name in self._needs:
            decay_s = self._model.need_decay_h.get(name, 1.0) * 3600.0 / tempo
            value = self._needs[name]
            if decay_s > 0.0:
                value = value * math.pow(0.5, dt / decay_s)
            self._needs[name] = _clamp(value, 0.0, 10.0)

        # Tension decays with a REAL 1.4 s half-life, never tempo-scaled.
        self._tension = _clamp01(self._tension * math.pow(0.5, dt / 1.4))

        # Need pressure: starved needs leak into emotions (real-seconds coupling).
        if self._needs.get("stimulation", 10.0) < 2.5:
            self._push_emotion("restlessness", dt * 0.004)
        if self._needs.get("social", 10.0) < 2.0:
            self._push_emotion("melancholy", dt * 0.002)
        if self._needs.get("rest", 10.0) < 2.0:
            self._push_emotion("focus", -dt * 0.003)

        # Mood integrator: each P/A/D axis eases toward its target with a
        # 240 s half-life gain k = 1 - 0.5^(dt / 240).
        k = 1.0 - math.pow(0.5, dt / 240.0)
        p_target = _clamp01(
            0.5
            + 0.22
            * (
                self._emo("satisfaction")
                + self._emo("warmth")
                + self._emo("amusement")
                + self._emo("connection")
            )
            / 2.0
            - 0.3 * (self._emo("frustration") + self._emo("melancholy"))
        )
        a_target = _clamp01(
            0.15
            + 0.8
            * (
                self._emo("curiosity")
                + self._emo("anticipation")
                + self._emo("restlessness")
                + self._emo("playfulness")
                + self._emo("frustration")
            )
            / 2.6
        )
        d_target = _clamp01(
            0.5
            + 0.35 * (self._emo("confidence") + self._emo("defiance"))
            - 0.35 * self._emo("melancholy")
        )
        for axis, target in (("p", p_target), ("a", a_target), ("d", d_target)):
            self._mood[axis] = _clamp01(self._mood[axis] + (target - self._mood[axis]) * k)

    def appraise(self, kind: str, intensity: float, now: float) -> bool:
        """Apply the ``kind`` appraisal's deltas, scaled by ``intensity``.

        Decays state to ``now`` first, then adds each emotion delta (clamped
        0..1), each need delta (clamped 0..10) and the tension kick (clamped
        0..1). An unknown kind is a no-op returning False; names the model
        does not define are silently skipped (a data typo must not raise, P9).
        """
        self.tick(now)
        appraisal = self._model.appraisals.get(kind)
        if appraisal is None:
            return False
        for name, delta in appraisal.emotions.items():
            self._push_emotion(name, delta * intensity)
        for name, delta in appraisal.needs.items():
            if name in self._needs:
                self._needs[name] = _clamp(self._needs[name] + delta * intensity, 0.0, 10.0)
        self._tension = _clamp01(self._tension + appraisal.tension * intensity)
        return True

    # -- projections -----------------------------------------------------------

    def phenotype(self, now: float) -> dict[str, float]:
        """The nine observable scalars (each 0..1), after decaying state to ``now``.

        This is the ONLY surface downstream consumers (the orb) read; it is
        derived, never stored, and contains no free text (EMO-2).
        """
        self.tick(now)
        rest = self._needs.get("rest", 0.0)
        social_need = self._needs.get("social", 0.0)
        p, a, d = self._mood["p"], self._mood["a"], self._mood["d"]
        fatigue = _clamp01((1.0 - rest / 10.0) * 0.7 + self._emo("melancholy") * 0.5)
        return {
            "fatigue": fatigue,
            "valence": _clamp01(
                0.5
                + 0.3
                * (self._emo("warmth") + self._emo("satisfaction") + self._emo("connection") - 1.0)
                - 0.35 * self._emo("melancholy")
            ),
            "arousal": _clamp01(0.12 + 0.85 * a + 0.3 * self._tension),
            "irritation": _clamp01(
                self._emo("frustration") * 0.85 + self._emo("defiance") * 0.35 + self._tension * 0.5
            ),
            "attention": _clamp01(
                0.25 + self._emo("curiosity") * 0.5 + self._emo("focus") * 0.35 - fatigue * 0.4
            ),
            "social": _clamp01(1.0 - social_need / 10.0) * _clamp01(1.0 - fatigue),
            "buoyancy": _clamp01(0.5 + 0.3 * d + 0.2 * self._emo("confidence") - 0.35 * fatigue),
            "luminosity": _clamp01(0.35 + 0.4 * p + 0.3 * self._emo("playfulness") - 0.3 * fatigue),
            "tension": _clamp01(self._tension),
        }

    def snapshot(self, now: float) -> dict[str, object]:
        """A persistable snapshot after decaying to ``now``: keys and floats only (EMO-2)."""
        self.tick(now)
        return {
            "emotions": dict(self._emotions),
            "needs": dict(self._needs),
            "mood": {"p": self._mood["p"], "a": self._mood["a"], "d": self._mood["d"]},
            "tension": self._tension,
            "last_updated": now,
        }

    @classmethod
    def restore(cls, model: EmotionModel, snap: Mapping[str, object], now: float) -> EmotionEngine:
        """Rebuild an engine from a :meth:`snapshot` mapping, tolerantly.

        Every field falls back to its default when missing or garbage (a
        corrupt state file must degrade to a fresh engine, never raise, P9).
        The final :meth:`tick` applies the decay for the time elapsed since
        the snapshot's ``last_updated``.
        """
        engine = cls(model, _as_float(snap.get("last_updated"), now))
        emotions = snap.get("emotions")
        if isinstance(emotions, Mapping):
            for name in engine._emotions:
                engine._emotions[name] = _clamp01(
                    _as_float(emotions.get(name), engine._emotions[name])
                )
        needs = snap.get("needs")
        if isinstance(needs, Mapping):
            for name in engine._needs:
                engine._needs[name] = _clamp(
                    _as_float(needs.get(name), engine._needs[name]), 0.0, 10.0
                )
        mood = snap.get("mood")
        if isinstance(mood, Mapping):
            for axis in ("p", "a", "d"):
                engine._mood[axis] = _clamp01(_as_float(mood.get(axis), engine._mood[axis]))
        engine._tension = _clamp01(_as_float(snap.get("tension"), 0.0))
        engine.tick(now)
        return engine
