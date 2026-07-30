"""Small deterministic helpers for the public Knowledge projection."""

from __future__ import annotations

import hashlib
from typing import Any

from .models import Segment


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:40]
    return f"{prefix}_{digest}"


def asset_type(media_type: str) -> str:
    return "pdf" if media_type.split(";", 1)[0].strip().lower() == "application/pdf" else "text"


def segment_public(segment: Segment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "sequence": segment.sequence,
        "text": segment.text,
        "locator": segment.locator,
        "content_hash": segment.content_hash,
    }


def projection_public(row) -> dict[str, Any]:
    return {
        "provider_id": row.provider_id,
        "operation": row.operation,
        "status": row.status,
        "error": row.error,
        "updated_at": row.updated_at.isoformat(),
    }
