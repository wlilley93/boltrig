"""boltrig.config.environment: the single env-truthy dialect (``is_truthy``).

Every env-style boolean knob in the codebase parses through ``is_truthy``; the
accepted true set is "1"/"true"/"yes"/"on"/"y"/"t" (case-insensitive, stripped).
store/sealing.py keeps an import-free mirror of ``_TRUE_VALUES`` that must stay
in lockstep (SEC-54 stack boundary).
"""

import pytest

from boltrig.config.environment import is_truthy, production_signal
from boltrig.store.sealing import _TRUE_VALUES as _SEALING_TRUE_VALUES


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "y", "t"])
def test_true_values_both_dialects(value: str) -> None:
    assert is_truthy(value)
    assert is_truthy(value.upper())
    assert is_truthy(f"  {value}  ")


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "n", "f", "2", "truthy"])
def test_false_values(value: str | None) -> None:
    assert not is_truthy(value)


def test_sealing_mirror_in_lockstep() -> None:
    from boltrig.config import environment

    assert _SEALING_TRUE_VALUES == environment._TRUE_VALUES


def test_production_signal_accepts_widened_true_set() -> None:
    assert production_signal({"BOLTRIG_PRODUCTION": "y"}) == "BOLTRIG_PRODUCTION"
    assert production_signal({"BOLTRIG_PRODUCTION": "t"}) == "BOLTRIG_PRODUCTION"
    assert production_signal({"BOLTRIG_PRODUCTION": "0"}) is None
