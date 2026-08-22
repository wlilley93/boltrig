"""Hearing HOW something was said, beside the adapter that hears it.

Kept in the adapters layer rather than in ``boltrig.emotion`` because SEC-54
forbids an adapter depending upward, and because the split is real: measuring a
speaker's pitch and reporting "that sounded cross" is an observation, like a
transcript. What hearing it does to a character is the emotion package's
business, through ``libraries/emotion/appraisals.yaml``.
"""

from __future__ import annotations

from .prosody import Prosody, analyse_prosody, decode_wav
from .tone import MIN_UTTERANCES, Baseline, classify
from .valence import warmth

__all__ = [
    "Baseline",
    "MIN_UTTERANCES",
    "Prosody",
    "analyse_prosody",
    "classify",
    "decode_wav",
    "warmth",
]
