"""Compatibility import for canonical device actions."""

from boltrig.models.device_actions import (
    MAX_ARG_BYTES,
    MAX_ARGS,
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_BYTES,
    MAX_PATH_BYTES,
    canonical_device_action,
)

__all__ = [
    "MAX_ARG_BYTES",
    "MAX_ARGS",
    "MAX_DIRECTORY_ENTRIES",
    "MAX_FILE_BYTES",
    "MAX_PATH_BYTES",
    "canonical_device_action",
]
