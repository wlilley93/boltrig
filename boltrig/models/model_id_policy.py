"""Shared byte-exact immutable model identifier policy."""

from __future__ import annotations

import re

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9@_.:/-]{0,159}\Z")
_MUTABLE_MODEL_SEGMENTS = frozenset(
    {
        "auto",
        "beta",
        "current",
        "default",
        "experimental",
        "latest",
        "preview",
        "recommended",
        "stable",
    }
)


def exact_model_id(value: object) -> str:
    """Validate one exact upstream model id without normalization."""

    if type(value) is not str or _MODEL_ID.fullmatch(value) is None:
        raise ValueError("model_id must be a bounded canonical identifier")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("model_id must not be a path")
    segments = {
        segment.casefold() for segment in re.split(r"[._:/-]", value) if segment
    }
    if segments & _MUTABLE_MODEL_SEGMENTS:
        raise ValueError("model_id must not use a mutable model alias")
    return value


__all__ = ["exact_model_id"]
