"""Owner-scoped ephemeral frame storage and result projection."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from boltrig.adapters.builtin.browser_contract import (
    MAX_COORDINATE,
    MAX_FRAME_BYTES,
    MAX_FRAMES,
    MAX_FRAMES_PER_SCOPE,
)
from boltrig.models import InvocationContext


@dataclass(frozen=True)
class BrowserFrame:
    id: str
    tenant_id: str
    owner_id: str
    session_name: str
    digest: str
    data: bytes
    width: int
    height: int
    url: str
    title: str
    captured_at: str

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media_type": "image/jpeg",
            "width": self.width,
            "height": self.height,
            "url": self.url,
            "title": self.title,
            "captured_at": self.captured_at,
        }


class BrowserFrameStore:
    def __init__(self) -> None:
        self._frames: OrderedDict[str, BrowserFrame] = OrderedDict()

    def list(self, scope: tuple[str, str, str], limit: int) -> list[dict[str, Any]]:
        rows = [
            frame.view()
            for frame in reversed(self._frames.values())
            if frame_scope_for(frame) == scope
        ]
        return rows[:limit]

    def owned(self, value: Any, context: InvocationContext) -> BrowserFrame:
        frame_id = clean_frame_id(value)
        frame = self._frames.get(frame_id)
        if (
            frame is None
            or frame.tenant_id != str(context.tenant_id)
            or frame.owner_id != owner_id(context)
        ):
            raise LookupError("browser frame not found")
        self._frames.move_to_end(frame_id)
        return frame

    def remember(self, frame: BrowserFrame) -> None:
        self._frames[frame.id] = frame
        scope = frame_scope_for(frame)
        scoped = [key for key, item in self._frames.items() if frame_scope_for(item) == scope]
        while len(scoped) > MAX_FRAMES_PER_SCOPE:
            self._frames.pop(scoped.pop(0), None)
        while len(self._frames) > MAX_FRAMES:
            self._frames.popitem(last=False)


def load_frame(
    path: str,
    raw_page: Any,
    *,
    tenant_id: str,
    owner_id_value: str,
    session_name: str,
) -> BrowserFrame:
    if not isinstance(raw_page, dict):
        raise ValueError("browser CLI omitted page metadata")
    data = _read_jpeg(path)
    width = bounded_int(raw_page.get("w"), minimum=1, maximum=MAX_COORDINATE, name="width")
    height = bounded_int(raw_page.get("h"), minimum=1, maximum=MAX_COORDINATE, name="height")
    return BrowserFrame(
        id=f"frame_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        owner_id=owner_id_value,
        session_name=session_name,
        digest=hashlib.sha256(data).hexdigest(),
        data=data,
        width=width,
        height=height,
        url=safe_text(raw_page.get("url"), 4096),
        title=safe_text(raw_page.get("title"), 512),
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def _read_jpeg(path: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or not 4 <= details.st_size <= MAX_FRAME_BYTES:
            raise ValueError("browser frame is outside the allowed size")
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            part = os.read(fd, min(remaining, 64 * 1024))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != details.st_size or not data.startswith(b"\xff\xd8"):
        raise ValueError("browser frame is not a valid JPEG")
    return data


def project_ax_node(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        node_id = bounded_int(row.get("node_id"), minimum=1, maximum=2**63 - 1, name="node_id")
    except ValueError:
        return None
    role = safe_text(row.get("role"), 80)
    if not role:
        return None
    out: dict[str, Any] = {
        "node_id": node_id,
        "role": role,
        "name": safe_text(row.get("name"), 240),
    }
    for key in ("x", "y", "width", "height"):
        if key not in row:
            continue
        try:
            out[key] = bounded_int(
                row[key],
                minimum=0 if key in {"x", "y"} else 1,
                maximum=MAX_COORDINATE,
                name=key,
            )
        except ValueError:
            continue
    return out


def project_cursor(raw: dict[str, Any]) -> dict[str, Any]:
    kind = str(raw.get("kind") or "")
    if kind not in {"click", "type", "scroll", "key"}:
        raise ValueError("browser CLI returned an invalid cursor kind")
    return {
        "x": bounded_int(raw.get("x"), minimum=0, maximum=MAX_COORDINATE, name="cursor x"),
        "y": bounded_int(raw.get("y"), minimum=0, maximum=MAX_COORDINATE, name="cursor y"),
        "kind": kind,
    }


def bounded_int(value: Any, *, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return parsed


def safe_text(value: Any, limit: int) -> str:
    text = str(value or "")
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    return text[:limit]


def owner_id(context: InvocationContext) -> str:
    return str(context.on_behalf_of or context.actor)


def frame_scope(context: InvocationContext, session_name: str) -> tuple[str, str, str]:
    return str(context.tenant_id), owner_id(context), session_name


def frame_scope_for(frame: BrowserFrame) -> tuple[str, str, str]:
    return frame.tenant_id, frame.owner_id, frame.session_name


def clean_frame_id(value: Any) -> str:
    frame_id = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", frame_id):
        raise ValueError("invalid browser frame id")
    return frame_id
