"""Local, data-only camera capability knowledge cache."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

from .discovery import CameraDiscovery


class CameraCacheError(ValueError):
    pass


class CameraKnowledgeCache:
    """Persist discovery summaries, never raw frames, serials, or code."""

    def __init__(self, path: str | Path, *, max_entries: int = 128) -> None:
        if max_entries < 1 or max_entries > 1024:
            raise CameraCacheError("invalid_camera_cache_bound")
        self.path = Path(path)
        self.max_entries = max_entries

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "cameras": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CameraCacheError("camera_cache_unreadable") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise CameraCacheError("camera_cache_schema_invalid")
        cameras = raw.get("cameras")
        if not isinstance(cameras, dict) or len(cameras) > self.max_entries:
            raise CameraCacheError("camera_cache_entries_invalid")
        return raw

    def record(self, discovery: CameraDiscovery) -> dict[str, Any]:
        document = self.read()
        cameras = document["cameras"]
        summary = discovery.as_dict()
        # The cache is a summary boundary. It deliberately omits any future raw
        # probe payload rather than relying on callers to redact it first.
        summary.pop("warnings", None)
        cameras[discovery.camera_id] = summary
        while len(cameras) > self.max_entries:
            del cameras[next(iter(cameras))]
        self._atomic_write(document)
        return summary

    def get(self, camera_id: str) -> dict[str, Any] | None:
        document = self.read()
        value = document["cameras"].get(camera_id)
        return value if isinstance(value, dict) else None

    def bind(
        self,
        *,
        hardware_key: str,
        usb_vid: int,
        usb_pid: int,
        fingerprint: str,
    ) -> str:
        """Return a local opaque binding, replacing it on hardware change.

        ``hardware_key`` is supplied by the platform layer and is never stored
        raw. It may contain an OS media identity or serial locally, but the
        cache stores only its digest and the immutable descriptor fingerprint.
        """
        if not isinstance(hardware_key, str) or not hardware_key or len(hardware_key) > 1024:
            raise CameraCacheError("invalid_camera_hardware_key")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise CameraCacheError("invalid_camera_fingerprint")
        document = self.read()
        key_digest = hashlib.sha256(hardware_key.encode("utf-8")).hexdigest()
        bindings = document.setdefault("bindings", {})
        if not isinstance(bindings, dict):
            raise CameraCacheError("camera_cache_bindings_invalid")
        existing = bindings.get(key_digest)
        existing_id = (
            existing.get("camera_id")
            if isinstance(existing, dict)
            else existing
        )
        existing_fingerprint = existing.get("fingerprint") if isinstance(existing, dict) else None
        existing_vid = existing.get("vid") if isinstance(existing, dict) else None
        existing_pid = existing.get("pid") if isinstance(existing, dict) else None
        if (
            isinstance(existing_id, str)
            and existing_fingerprint == fingerprint
            and existing_vid == f"0x{usb_vid:04x}"
            and existing_pid == f"0x{usb_pid:04x}"
        ):
            return existing_id
        camera_id = "camera_" + secrets.token_hex(16)
        bindings[key_digest] = {
            "camera_id": camera_id,
            "vid": f"0x{usb_vid:04x}",
            "pid": f"0x{usb_pid:04x}",
            "fingerprint": fingerprint,
        }
        self._atomic_write(document)
        return camera_id

    def _atomic_write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".camera-cache-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
