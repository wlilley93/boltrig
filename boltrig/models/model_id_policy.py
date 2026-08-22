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


def _shaped(value: object) -> str:
    if type(value) is not str or _MODEL_ID.fullmatch(value) is None:
        raise ValueError("model_id must be a bounded canonical identifier")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("model_id must not be a path")
    return value


def exact_model_id(value: object) -> str:
    """Validate one exact upstream model id without normalization."""

    value = _shaped(value)
    segments = {
        segment.casefold() for segment in re.split(r"[._:/-]", value) if segment
    }
    if segments & _MUTABLE_MODEL_SEGMENTS:
        raise ValueError("model_id must not use a mutable model alias")
    return value


def user_model_id(value: object) -> str:
    """Validate a model id a USER connected, where aliases are theirs to pick.

    ``exact_model_id`` pins kernel-configured artifacts (endpoints, profiles,
    the platform default) to ids whose meaning cannot drift under an audit
    trail. A user's own provider binding cannot be given that guarantee by a
    segment blocklist: on a self-hosted server EVERY tag is re-pointable, so
    refusing ``:latest`` while accepting ``:34ba10f8b5e0`` blocks the name the
    provider itself lists without making anything immutable. Downstream pins
    (the admission ceiling, the scoped gateway key) hold the exact string
    either way. Shape and path rules still apply unchanged.
    """

    return _shaped(value)


__all__ = ["exact_model_id", "user_model_id"]
