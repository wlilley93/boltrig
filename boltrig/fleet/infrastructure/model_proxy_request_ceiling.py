"""Request-side model and reasoning ceilings shared by every Codex thread."""

from __future__ import annotations

import json

from boltrig.models.model_id_policy import user_model_id

from .model_proxy_ceiling_errors import (
    ModelCeilingViolation,
    ReasoningEffortCeilingViolation,
)

MAX_MODEL_CALL_BODY_BYTES = 32 * 1024 * 1024


def enforce_model_ceiling(body: bytes, allowed_model: str) -> bytes:
    """Require the admission-pinned model on every non-empty request."""
    if type(body) is not bytes:
        raise TypeError("body must be exact bytes")
    try:
        # The ceiling pins the exact admission STRING; whether that string is a
        # provider alias was decided (and allowed for user bindings) upstream.
        user_model_id(allowed_model)
    except ValueError:
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
    if reasoning is None:
        # Absence is BELOW the ceiling, not outside it: codex only includes a
        # reasoning block for models it recognises as reasoning models, so a
        # ceiling that demands the block refuses every plain model's call
        # (measured 2026-08-20: the first live turn against a self-hosted
        # model died here). The same None/exact shape the native-collaboration
        # gate already applies to child overrides.
        return body
    effort = reasoning.get("effort") if isinstance(reasoning, dict) else object()
    if effort is not None and effort != allowed_effort:
        raise ReasoningEffortCeilingViolation(
            "model-call reasoning effort is outside the admission ceiling"
        )
    return body
