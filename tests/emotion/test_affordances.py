"""The two explicit mood affordances: reset, and adoption novelty (EMO-5)."""

from __future__ import annotations

import pathlib

import pytest

from boltrig.emotion.relay import EmotionRelay
from boltrig.emotion.tables import load_emotion_tables

TENANT = "acme"


def _relay(tmp_path: pathlib.Path) -> EmotionRelay:
    tables = load_emotion_tables()
    assert tables is not None, "the shipped libraries/emotion YAML must load"
    model, rules = tables
    return EmotionRelay(
        model=model,
        rules=rules,
        phenotype_path=tmp_path / "phenotype.json",
        state_path=tmp_path / "state.json",
        tenant=TENANT,
        autostart=False,
    )


def _snapshot(relay: EmotionRelay, tenant: str) -> dict[str, float]:
    import time

    now = time.time()  # the relay appraises at wall-clock; snapshots must too
    with relay._engines_lock:  # noqa: SLF001 - white-box: the affordance's whole point
        nested = relay._engine_for(tenant, now).snapshot(now)  # noqa: SLF001
    flat: dict[str, float] = {}
    for key, value in nested.items():
        if isinstance(value, dict):
            for inner, number in value.items():
                flat[f"{key}.{inner}"] = float(number)
        elif key != "last_updated":
            flat[key] = float(value)
    return flat


def test_adoption_refills_novelty_and_is_throttled(tmp_path: pathlib.Path) -> None:
    relay = _relay(tmp_path)
    before = _snapshot(relay, TENANT)

    relay.publish(TENANT, "emotion", {"type": "character_adopted", "character": "bella"})
    after = _snapshot(relay, TENANT)
    assert after["needs.novelty"] > before["needs.novelty"]
    assert after["emotions.curiosity"] > before["emotions.curiosity"]

    # A second adoption inside the throttle window appraises NOTHING more.
    relay.publish(TENANT, "emotion", {"type": "character_adopted", "character": "jarvis"})
    assert _snapshot(relay, TENANT) == pytest.approx(after, abs=1e-3)


def test_reset_returns_the_engine_to_model_baselines(tmp_path: pathlib.Path) -> None:
    relay = _relay(tmp_path)
    fresh = _snapshot(relay, TENANT)
    relay.publish(TENANT, "emotion", {"type": "character_adopted", "character": "bella"})
    assert _snapshot(relay, TENANT) != pytest.approx(fresh, abs=1e-3)

    relay.publish(TENANT, "emotion", {"type": "emotion_reset"})

    assert _snapshot(relay, TENANT) == pytest.approx(fresh, abs=1e-3)


def test_reset_also_drops_the_persisted_restore_snapshot(tmp_path: pathlib.Path) -> None:
    relay = _relay(tmp_path)
    relay._saved[TENANT] = {"emotions.curiosity": 0.99}  # noqa: SLF001 - a prior process's mood

    relay.publish(TENANT, "emotion", {"type": "emotion_reset"})

    assert TENANT not in relay._saved  # noqa: SLF001
    # And the engine the next reader sees is the fresh one, not a restore.
    fresh = _relay(tmp_path)
    assert _snapshot(relay, TENANT) == pytest.approx(_snapshot(fresh, "other"), abs=1e-3)
