"""Shared validation for opaque, tenant-scoped model choice identifiers."""

from __future__ import annotations

import re

MAX_MODEL_CHOICE_ID_CHARS = 160
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]{1,160}\Z")


def opaque_model_choice_id(value: object) -> str:
    """Return one bounded printable-ASCII identifier without normalizing it."""

    if (
        type(value) is not str
        or _PATH_SEGMENT.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ValueError("model choice id must be one bounded URL-safe path segment")
    return value


__all__ = ["MAX_MODEL_CHOICE_ID_CHARS", "opaque_model_choice_id"]
