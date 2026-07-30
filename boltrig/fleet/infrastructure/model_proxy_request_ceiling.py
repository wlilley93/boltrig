"""Request-side model and reasoning ceilings shared by every Codex thread."""

from __future__ import annotations

import json

from .model_proxy_ceiling_errors import (
    ModelCeilingViolation,
    ReasoningEffortCeilingViolation,
)

MAX_MODEL_CALL_BODY_BYTES = 32 * 1024 * 1024


def enforce_model_ceiling(body: bytes, allowed_model: str) -> bytes:
    """Require the admission-pinned model on every non-empty request."""
    if type(body) is not bytes:
        raise TypeError("body must be exact bytes")
    if type(allowed_model) is not str or not allowed_model or len(allowed_model) > 128:
        raise ValueError("allowed model must be a bounded non-empty string")
    if not body:
        return body
    if len(body) > MAX_MODEL_CALL_BODY_BYTES:
        raise ModelCeilingViolation("model-call body exceeds the verifiable size cap")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelCeilingViolation("model-call body is not parseable JSON") from error
    if not isinstance(payload, dict) or payload.get("model") != allowed_model:
        raise ModelCeilingViolation("model-call model is outside the admission ceiling")
    return body


def enforce_reasoning_effort_ceiling(body: bytes, allowed_effort: str) -> bytes:
    """Require the admission-pinned Responses ``reasoning.effort``."""
    if type(body) is not bytes:
        raise TypeError("body must be exact bytes")
    if type(allowed_effort) is not str or not allowed_effort or len(allowed_effort) > 32:
        raise ValueError("allowed effort must be a bounded non-empty string")
    if not body:
        return body
    if len(body) > MAX_MODEL_CALL_BODY_BYTES:
        raise ReasoningEffortCeilingViolation(
            "model-call body exceeds the verifiable size cap"
        )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReasoningEffortCeilingViolation(
            "model-call body is not parseable JSON"
        ) from error
    reasoning = payload.get("reasoning") if isinstance(payload, dict) else None
    if not isinstance(reasoning, dict) or reasoning.get("effort") != allowed_effort:
        raise ReasoningEffortCeilingViolation(
            "model-call reasoning effort is outside the admission ceiling"
        )
    return body
