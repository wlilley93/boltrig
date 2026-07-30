"""Caller-safe projection of administrator-approved model profiles."""

from __future__ import annotations

import json
import os
from typing import Any


def visible_model_profiles() -> list[dict[str, Any]]:
    """List profile choice metadata without exposing its server route.

    The detailed provider/model/base URL remains in the fleet resolver. The
    management surface receives only the stable id and a deliberately coarse
    routing class; availability is whether the configured record has the two
    required route fields, not a live provider-health claim.
    """
    raw = os.environ.get("BOLTRIG_MODEL_PROFILES")
    if not raw:
        return []
    try:
        records = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(records, dict):
        return []
    out: list[dict[str, Any]] = []
    for name, record in sorted(records.items()):
        if not isinstance(record, dict):
            continue
        available = bool(record.get("provider") and record.get("model"))
        out.append(
            {
                "id": str(name),
                "label": str(name).replace("-", " ").replace("_", " ").title(),
                "routing_class": "governed" if available else "unavailable",
                "data_classes": ["standard"],
                "available": available,
                "unavailable_reason": None if available else "profile unavailable",
            }
        )
    return out


def resolve_realtime_model_profile(profile_id: str) -> dict[str, str] | None:
    """Resolve an approved profile for the xAI realtime gateway.

    The route is returned only to the trusted channel gateway, never through a
    browser call projection.
    """
    raw = os.environ.get("BOLTRIG_MODEL_PROFILES")
    try:
        records = json.loads(raw) if raw else {}
    except ValueError:
        return None
    record = records.get(profile_id) if isinstance(records, dict) else None
    if not isinstance(record, dict):
        return None
    provider = str(record.get("provider") or "").lower()
    model = str(record.get("model") or "").strip()
    if provider not in {"xai", "x.ai", "grok"} or not model:
        return None
    return {"id": profile_id, "provider": "xai", "model": model}
