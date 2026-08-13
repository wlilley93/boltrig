"""Exact protected-release mode parsing shared by build and runtime gates."""

from __future__ import annotations

from collections.abc import Mapping


RELEASE_MODE_ENV = "BOLTRIG_RELEASE_MODE"
VALID_RELEASE_MODES = frozenset({"core", "full"})


def validate_release_mode(value: str) -> str:
    """Return an exact admitted mode; reject missing or decorated values."""
    if value not in VALID_RELEASE_MODES:
        expected = " or ".join(sorted(VALID_RELEASE_MODES))
        raise ValueError(
            f"{RELEASE_MODE_ENV} must be set explicitly in the protected "
            f"release environment to exactly {expected}"
        )
    return value


def configured_release_mode(env: Mapping[str, str]) -> str | None:
    """Return an exact configured mode, preserving absence as no override."""
    if RELEASE_MODE_ENV not in env:
        return None
    return validate_release_mode(env[RELEASE_MODE_ENV])


__all__ = [
    "RELEASE_MODE_ENV",
    "VALID_RELEASE_MODES",
    "configured_release_mode",
    "validate_release_mode",
]
