"""Validation and framing for the terminal client's JSON-lines gateway mode."""

from __future__ import annotations

import json
import re
from typing import Any

_TARGET_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")


def clean_target(value: Any) -> str | None:
    """A target slug or None (the kernel's channel_routes._clean_target rule)."""
    slug = str(value or "").strip()
    return slug if _TARGET_RE.fullmatch(slug) else None


def encode_frame(sender: str, text: str, message_id: str, target: str | None = None) -> bytes:
    """One inbound JSON-lines frame; the loop uses a per-process monotonic id."""
    frame: dict[str, Any] = {"id": message_id, "sender": sender, "text": text}
    if target:
        frame["target"] = target
    return (json.dumps(frame, separators=(",", ":")) + "\n").encode()


def decode_frame(line: bytes) -> dict[str, Any] | None:
    """One outbound line, or None - a malformed line is dropped, never fatal."""
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return message if isinstance(message, dict) else None
