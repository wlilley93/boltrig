"""Identifiers and ownership fences for run-scoped credential records."""

from __future__ import annotations

from typing import Any


RUN_SCOPED_REF_PREFIX = "credential:run/"
RUN_SCOPED_CRED_PREFIX = "run:"
SECURE_ANSWER_KIND = "secure_answer"
ADAPTER_BEARER_KIND = "adapter_bearer"
HELD_CALL_KIND = "held_call"


def run_scoped_cred_id(run_id: str, purpose: str) -> str:
    """The credential_refs id a secure answer is sealed under."""
    return f"{RUN_SCOPED_CRED_PREFIX}{run_id}:{purpose}"


def adapter_bearer_cred_id(run_id: str, adapter_id: str) -> str:
    """Return the distinct credential_refs id for one run's adapter bearer."""
    return f"{RUN_SCOPED_CRED_PREFIX}{run_id}:adapter_bearer:{adapter_id}"


def held_call_cred_id(run_id: str, request_id: str) -> str:
    """Return the distinct credential_refs id for one gate-held call."""
    return f"{RUN_SCOPED_CRED_PREFIX}{run_id}:held_call:{request_id}"


def owner_matches(ref: dict, context_owner: str | None) -> bool:
    """Fail closed unless the sealed row belongs to the current identity.

    A run id alone is insufficient because invoke/spawn request bodies can name
    runs. Records created before the owner fence carry no owner and resolve for
    nobody.
    """
    owner = ref.get("owner")
    return bool(owner) and bool(context_owner) and owner == context_owner


def parse_run_scoped_ref(value: Any) -> tuple[str, str] | None:
    """Parse an exact ``credential:run/<run_id>/<purpose>`` reference."""
    if not isinstance(value, str) or not value.startswith(RUN_SCOPED_REF_PREFIX):
        return None
    parts = value[len(RUN_SCOPED_REF_PREFIX) :].split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


__all__ = [
    "ADAPTER_BEARER_KIND",
    "HELD_CALL_KIND",
    "RUN_SCOPED_CRED_PREFIX",
    "RUN_SCOPED_REF_PREFIX",
    "SECURE_ANSWER_KIND",
    "adapter_bearer_cred_id",
    "held_call_cred_id",
    "owner_matches",
    "parse_run_scoped_ref",
    "run_scoped_cred_id",
]
