"""Canonical, secret-safe binding of a human approval to one exact action."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any


def _normalise_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number in approval context")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalise_json(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("non-string key in approval context")
            key = unicodedata.normalize("NFC", raw_key)
            if key in out:
                raise ValueError("normalised key collision in approval context")
            out[key] = _normalise_json(item)
        return out
    raise ValueError("non-JSON value in approval context")


def canonical_approval_value(value: Any) -> Any:
    """Return a detached canonical copy suitable for an adapter re-check."""

    return _normalise_json(value)


def approval_request_fingerprint(
    *,
    noun: str,
    verb: str,
    params: dict[str, Any],
    context: Any,
    resource_context: Any = None,
) -> str:
    """Bind one approval to one canonical action and authenticated initiator."""

    payload = {
        "version": 1,
        "tenant_id": context.tenant_id,
        "noun": noun,
        "verb": verb,
        "params": params,
        "initiator": {
            "actor": context.actor,
            "actor_tier": context.actor_tier,
            "on_behalf_of": context.on_behalf_of,
            "workspace_id": context.workspace_id,
            "run_id": context.run_id,
            "role": context.extra.get("principal_role"),
            "scope": context.extra.get("principal_scope"),
            "grants": {
                "allow": sorted(context.grants.allow),
                "deny": sorted(context.grants.deny),
            },
            "skills_loaded": sorted(context.skills_loaded),
        },
        "resource_context": resource_context,
    }
    canonical = json.dumps(
        _normalise_json(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["approval_request_fingerprint", "canonical_approval_value"]
