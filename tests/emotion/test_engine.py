"""Emotion engine behavior plus the EMO-3 purity and EMO-5 table-is-data claims.

The engine is the pure core of the emotion add-on: no I/O, no clock reads, no
randomness - every method takes explicit epoch-second timestamps. These tests
pin the decay laws (emotions toward the mood-biased baseline, needs toward
zero), tempo scaling, the mood integrator, and appraisal application, then
bind EMO-3 (determinism plus an AST import whitelist over the module) and
EMO-5 (the shipped libraries/emotion YAML drives behavior and changing the
parsed data changes behavior with no code edit).
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from typing import cast

import pytest

from boltrig.emotion.engine import Appraisal, EmotionEngine, EmotionModel
from boltrig.emotion.tables import load_emotion_tables

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ENGINE_PY = _REPO / "boltrig" / "emotion" / "engine.py"

_T0 = 1_700_000_000.0

# The canonical Atrophy-donor model data (hours verbatim; tempo 60 makes one
# model hour pass per real minute). Inlined so the engine tests do not depend
# on the YAML loader - the tables get their own EMO-5 test below.
_BASELINES = {
    "connection": 0.5, "curiosity": 0.6, "confidence": 0.5, "warmth": 0.5,
    "frustration": 0.1, "playfulness": 0.3, "amusement": 0.2,
    "anticipation": 0.4, "satisfaction": 0.4, "restlessness": 0.2,
    "tenderness": 0.3, "melancholy": 0.1, "focus": 0.5, "defiance": 0.1,
}
_HALF_LIVES_H = {
    "connection": 2.0, "curiosity": 1.0, "confidence": 2.0, "warmth": 1.5,
    "frustration": 1.0, "playfulness": 0.5, "amusement": 0.5,
    "anticipation": 1.5, "satisfaction": 3.0, "restlessness": 1.0,
    "tenderness": 3.0, "melancholy": 4.0, "focus": 1.0, "defiance": 1.0,
}
_NEED_DEFAULTS = {
    "stimulation": 5.0, "expression": 5.0, "purpose": 5.0, "autonomy": 5.0,
    "recognition": 5.0, "novelty": 5.0, "social": 5.0, "rest": 5.0,
}
_NEED_DECAY_H = {
    "stimulation": 6.0, "expression": 8.0, "purpose": 12.0, "autonomy": 8.0,
    "recognition": 12.0, "novelty": 4.0, "social": 6.0, "rest": 24.0,
}
_APPRAISALS = {
    "user_message": Appraisal(
        emotions={"connection": 0.18, "curiosity": 0.15, "anticipation": 0.12,
                  "restlessness": -0.08},
        needs={"social": 2.2, "stimulation": 1.2},
    ),
    "task_success": Appraisal(
        emotions={"satisfaction": 0.28, "confidence": 0.18, "playfulness": 0.12,
                  "frustration": -0.15, "focus": -0.1},
        needs={"purpose": 2.5, "recognition": 1.0},
    ),
    "task_error": Appraisal(
        emotions={"frustration": 0.3, "confidence": -0.12, "restlessness": 0.18,
                  "focus": 0.15, "satisfaction": -0.1},
        needs={"stimulation": 0.8},
        tension=0.6,
    ),
    "praise": Appraisal(
        emotions={"warmth": 0.25, "tenderness": 0.18, "satisfaction": 0.2,
                  "confidence": 0.12, "melancholy": -0.1},
        needs={"recognition": 3.0, "social": 1.5},
    ),
    "poke": Appraisal(
        emotions={"frustration": 0.22, "defiance": 0.15, "restlessness": 0.15,
                  "curiosity": 0.08},
        needs={"stimulation": 1.5},
        tension=0.6,
    ),
    "interrupted": Appraisal(
        emotions={"melancholy": 0.15, "frustration": 0.15, "restlessness": 0.1,
                  "satisfaction": -0.1},
        needs={},
        tension=0.4,
    ),
}


def _model(tempo: float = 60.0) -> EmotionModel:
    return EmotionModel(
        baselines=_BASELINES,
        half_lives_h=_HALF_LIVES_H,
        need_defaults=_NEED_DEFAULTS,
        need_decay_h=_NEED_DECAY_H,
        appraisals=_APPRAISALS,
        tempo=tempo,
    )


def _emotions(engine: EmotionEngine, now: float) -> dict[str, float]:
    return cast(dict[str, float], engine.snapshot(now)["emotions"])


def _needs(engine: EmotionEngine, now: float) -> dict[str, float]:
    return cast(dict[str, float], engine.snapshot(now)["needs"])


def _mood(engine: EmotionEngine, now: float) -> dict[str, float]:
    return cast(dict[str, float], engine.snapshot(now)["mood"])


@pytest.mark.unit
def test_emotions_decay_toward_baseline() -> None:
    engine = EmotionEngine(_model(), _T0)
    assert engine.appraise("task_success", 1.0, _T0) is True
    lifted = _emotions(engine, _T0)["satisfaction"]
    assert lifted > 0.6  # baseline 0.4 plus the 0.28 delta

    # satisfaction's half-life is 3 model hours = 180 real seconds at tempo 60,
    # so one real hour is ~20 half-lives: the deviation is gone and the value
    # sits in the (mood-biased, at most +-0.08 shifted) baseline band.
    settled = _emotions(engine, _T0 + 3600.0)["satisfaction"]
    assert abs(settled - 0.4) < abs(lifted - 0.4)
    assert 0.3 <= settled <= 0.5


@pytest.mark.unit
def test_needs_decay_toward_zero() -> None:
    engine = EmotionEngine(_model(), _T0)
    start = _needs(engine, _T0)
    assert start["novelty"] == pytest.approx(5.0)

    # novelty's decay half-life is 4 model hours = 240 real seconds at tempo
    # 60; ten half-lives later it has decayed to essentially zero (toward
    # zero, not toward a baseline), and every need has strictly dropped.
    later = _needs(engine, _T0 + 2400.0)
    assert later["novelty"] < 0.1
    for name, value in later.items():
        assert value < start[name]


@pytest.mark.unit
def test_tempo_scales_decay_speed() -> None:
    # needs: stimulation's 6-model-hour half-life is 360 real seconds at tempo
    # 60 but only 180 at tempo 120, so the faster engine is a half-life ahead.
    slow = EmotionEngine(_model(tempo=60.0), _T0)
    fast = EmotionEngine(_model(tempo=120.0), _T0)
    assert _needs(fast, _T0 + 360.0)["stimulation"] < (
        _needs(slow, _T0 + 360.0)["stimulation"] - 0.5
    )

    # emotions: frustration's 1-model-hour half-life is 60 real seconds at
    # tempo 60 and 30 at tempo 120.
    slow2 = EmotionEngine(_model(tempo=60.0), _T0)
    fast2 = EmotionEngine(_model(tempo=120.0), _T0)
    assert slow2.appraise("poke", 1.0, _T0) is True
    assert fast2.appraise("poke", 1.0, _T0) is True
    assert _emotions(fast2, _T0 + 60.0)["frustration"] < (
        _emotions(slow2, _T0 + 60.0)["frustration"] - 0.02
    )


@pytest.mark.unit
def test_mood_drifts_toward_the_emotion_derived_target() -> None:
    happy = EmotionEngine(_model(), _T0)
    sour = EmotionEngine(_model(), _T0)
    assert happy.appraise("praise", 1.0, _T0) is True
    assert happy.appraise("task_success", 1.0, _T0) is True
    assert sour.appraise("poke", 1.0, _T0) is True
    assert sour.appraise("task_error", 1.0, _T0) is True
    assert sour.appraise("interrupted", 1.0, _T0) is True

    # drive both in small steps so the mood integrator (240 s half-time) sees
    # the elevated emotions before they decay away
    for step in range(1, 13):
        now = _T0 + 10.0 * step
        happy.tick(now)
        sour.tick(now)

    p_happy = _mood(happy, _T0 + 120.0)["p"]
    p_sour = _mood(sour, _T0 + 120.0)["p"]
    assert p_happy > 0.55  # drifted up from the initial P of 0.55
    assert p_happy > p_sour + 0.03  # the sour engine drifted the other way


@pytest.mark.unit
def test_appraisal_applies_scaled_deltas_and_unknown_kind_is_a_noop() -> None:
    engine = EmotionEngine(_model(), _T0)
    sat0 = _emotions(engine, _T0)["satisfaction"]
    purpose0 = _needs(engine, _T0)["purpose"]
    assert engine.appraise("task_success", 1.0, _T0) is True
    assert _emotions(engine, _T0)["satisfaction"] == pytest.approx(sat0 + 0.28)
    assert _needs(engine, _T0)["purpose"] == pytest.approx(purpose0 + 2.5)

    half = EmotionEngine(_model(), _T0)
    assert half.appraise("task_success", 0.5, _T0) is True
    assert _emotions(half, _T0)["satisfaction"] == pytest.approx(sat0 + 0.14)

    tense = EmotionEngine(_model(), _T0)
    assert tense.appraise("task_error", 1.0, _T0) is True
    assert cast(float, tense.snapshot(_T0)["tension"]) == pytest.approx(0.6)

    untouched = EmotionEngine(_model(), _T0)
    before = untouched.snapshot(_T0)
    assert untouched.appraise("no_such_kind", 1.0, _T0) is False
    assert untouched.snapshot(_T0) == before


@pytest.mark.unit
@pytest.mark.invariant("EMO-3")
def test_appraise_is_deterministic_for_identical_inputs() -> None:
    def run() -> tuple[dict[str, object], dict[str, float]]:
        engine = EmotionEngine(_model(), _T0)
        assert engine.appraise("user_message", 1.0, _T0) is True
        engine.tick(_T0 + 30.0)
        assert engine.appraise("task_error", 0.5, _T0 + 45.0) is True
        assert engine.appraise("praise", 0.25, _T0 + 60.0) is True
        phenotype = engine.phenotype(_T0 + 90.0)
        return engine.snapshot(_T0 + 120.0), phenotype

    snap_a, phenotype_a = run()
    snap_b, phenotype_b = run()
    assert snap_a == snap_b
    assert phenotype_a == phenotype_b


@pytest.mark.unit
@pytest.mark.invariant("EMO-3")
def test_engine_module_imports_stay_inside_the_pure_whitelist() -> None:
    allowed = {"__future__", "math", "dataclasses", "typing", "collections.abc"}
    tree = ast.parse(_ENGINE_PY.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(a.name for a in node.names if a.name not in allowed)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or module not in allowed:
                offenders.append(module or "<relative>")
    assert offenders == [], (
        "boltrig/emotion/engine.py must stay pure (no I/O, no clock, no "
        f"randomness, EMO-3); disallowed imports: {offenders}"
    )


@pytest.mark.unit
@pytest.mark.invariant("EMO-5")
def test_appraisal_table_is_data_and_mutating_it_changes_behavior() -> None:
    tables = load_emotion_tables()
    assert tables is not None, "the shipped libraries/emotion YAML must load"
    model, rules = tables
    assert rules, "the shipped event map must contain rules"

    # the shipped data drives behavior: task_success raises satisfaction by
    # exactly the delta the YAML declares (0.28)
    shipped = EmotionEngine(model, _T0)
    sat0 = _emotions(shipped, _T0)["satisfaction"]
    assert shipped.appraise("task_success", 1.0, _T0) is True
    assert _emotions(shipped, _T0)["satisfaction"] == pytest.approx(sat0 + 0.28)

    # change the parsed DATA (no code edit), rebuild, and behavior changes
    original = model.appraisals["task_success"]
    flipped = Appraisal(
        emotions={**dict(original.emotions), "satisfaction": -0.2},
        needs=original.needs,
        tension=original.tension,
    )
    mutated = dataclasses.replace(
        model, appraisals={**dict(model.appraisals), "task_success": flipped}
    )
    changed = EmotionEngine(mutated, _T0)
    assert changed.appraise("task_success", 1.0, _T0) is True
    assert _emotions(changed, _T0)["satisfaction"] == pytest.approx(sat0 - 0.2)
