"""Validated chat attachment records and model-visible text projection."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from boltrig.config.manifest import ChatConfig
from boltrig.models import BoltrigError

from .prompt_stack import wrap_untrusted


class AttachmentRejected(BoltrigError):
    """A chat turn's attachments breached the configured intake caps."""

    status_code = 413
    reason = "attachment_rejected"


def _is_text_attachment(media_type: str) -> bool:
    return (media_type or "").lower().startswith("text/")


def validate_attachments(
    attachments: list[dict[str, Any]] | None, cfg: ChatConfig
) -> list[dict[str, Any]]:
    """Validate decoded byte/count caps before any turn side effect."""
    if not attachments:
        return []
    if not isinstance(attachments, list):
        raise AttachmentRejected("attachments must be a list")
    if len(attachments) > cfg.max_attachments:
        raise AttachmentRejected(f"too many attachments (max {cfg.max_attachments})")
    total = 0
    records: list[dict[str, Any]] = []
    for raw in attachments:
        if not isinstance(raw, dict):
            raise AttachmentRejected("each attachment must be an object")
        name = str(raw.get("name") or "attachment")
        media_type = str(raw.get("media_type") or "application/octet-stream")
        data = raw.get("data") or ""
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentRejected("attachment data is not valid base64") from exc
        size = len(decoded)
        if size > cfg.max_attachment_bytes:
            raise AttachmentRejected(
                f"attachment {name!r} is {size} bytes "
                f"(max {cfg.max_attachment_bytes} decoded)"
            )
        total += size
        if total > cfg.max_total_attachment_bytes:
            raise AttachmentRejected(
                f"attachments total {total} bytes "
                f"(max {cfg.max_total_attachment_bytes} decoded)"
            )
        records.append(
            {
                "name": name,
                "media_type": media_type,
                "data": str(data),
                "size": size,
            }
        )
    return records


def attachment_task_supplement(
    attachments: list[dict[str, Any]] | None,
) -> str:
    """Project only text attachments into typed untrusted task data."""
    parts: list[str] = []
    for attachment in attachments or []:
        if not _is_text_attachment(str(attachment.get("media_type", ""))):
            continue
        try:
            text = base64.b64decode(
                attachment.get("data") or "", validate=True
            ).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            continue
        parts.append(
            wrap_untrusted(
                "attachment",
                str(attachment.get("name") or "attachment"),
                text,
            )
        )
    return "\n\n" + "\n\n".join(parts) if parts else ""
