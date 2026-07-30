"""Shared, import-safe deployment-environment classification."""

from __future__ import annotations

import os
from collections.abc import Mapping

_PRODUCTION_VALUES = frozenset({"prod", "production", "staging"})
_DEVELOPMENT_VALUES = frozenset({"dev", "development", "local", "test"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "t"})


def is_truthy(value: str | None) -> bool:
    """Parse an env-style boolean string ("1"/"true"/"yes"/"on"/"y"/"t", case-insensitive)."""
    return (value or "").strip().lower() in _TRUE_VALUES


def production_signal(env: Mapping[str, str] | None = None) -> str | None:
    """Return the first explicit production/staging signal, otherwise ``None``."""
    values = env if env is not None else os.environ
    explicit = (values.get("BOLTRIG_PRODUCTION") or "").strip().lower()
    if explicit in _TRUE_VALUES:
        return "BOLTRIG_PRODUCTION"
    for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        value = (values.get(key) or "").strip().lower()
        if value in _PRODUCTION_VALUES:
            return f"{key}={value}"
    return None


def development_signal(env: Mapping[str, str] | None = None) -> str | None:
    """Return the first AFFIRMATIVE development/test signal, otherwise ``None``.

    The counterpart to ``production_signal``, and the reason it exists is a
    ruling ([2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 D5): *a gate whose
    permissive branch is the absence of a signal is not a gate.*

    ``production_signal`` returns None when all four variables are unset, and a
    control that read "no production signal" as permission therefore permitted on
    every environment nobody had configured. Classical Visas returned no
    production signal while serving a real client on a public domain. A control
    that must establish a fact has to require an affirmative statement of it, not
    the silence of its negation.
    """
    values = env if env is not None else os.environ
    for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        value = (values.get(key) or "").strip().lower()
        if value in _DEVELOPMENT_VALUES:
            return f"{key}={value}"
    return None
