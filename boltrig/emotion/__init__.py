"""Boltrig's affective side-channel: a read-only emotion projection over run events.

Governing ruling: emotion is strictly DOWNSTREAM of dispatch (EMO-1). It
observes the kernel's event stream through the ONE relay factory seam and
projects it into a phenotype file for cosmetic consumers (the desktop orb). It
must never influence grant checks, HITL or dispatch, and it is fail-safe by
construction (P9): every exception is swallowed, nothing here may ever break a
run. This package supersedes ``boltrig.observability.orb_presence``.

Layout: :mod:`boltrig.emotion.engine` is the pure dynamical system (EMO-3),
:mod:`boltrig.emotion.tables` loads the ``libraries/emotion`` YAML data
(EMO-5), and :mod:`boltrig.emotion.relay` attaches both to the event stream.
"""

from __future__ import annotations

from boltrig.emotion.engine import Appraisal, EmotionEngine, EmotionModel

__all__ = ["Appraisal", "EmotionEngine", "EmotionModel"]
