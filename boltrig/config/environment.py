"""Shared, import-safe deployment-environment classification."""

from __future__ import annotations

import os
from collections.abc import Mapping

_PRODUCTION_VALUES = frozenset({"prod", "production", "staging"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


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
