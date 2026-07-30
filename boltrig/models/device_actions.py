"""Canonical bounded device actions shared by dispatch and lease persistence."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PATH_BYTES = 1024
MAX_ARG_BYTES = 4096
MAX_ARGS = 64
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _relative_path(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value.encode()) > MAX_PATH_BYTES:
        raise ValueError("invalid_relative_path")
    if "\\" in value or "\x00" in value or value.startswith("/"):
        raise ValueError("invalid_relative_path")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("invalid_relative_path")
    return PurePosixPath(*raw_parts).as_posix()


def _normalise_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number in device action")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalise_json(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = unicodedata.normalize("NFC", raw_key)
            if key in out:
                raise ValueError("normalised key collision in device action")
            out[key] = _normalise_json(item)
        return out
    raise ValueError("non-JSON device action")


def _action_digest(*, verb: str, params: dict[str, Any]) -> str:
    canonical = json.dumps(
        _normalise_json(
            {"noun": "device", "params": params, "verb": verb, "version": 1}
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_device_action(
    device_id: str, root_id: str, verb: str, raw: object
) -> tuple[dict[str, Any], str]:
    """Validate one relative-path/argv action and bind its exact dispatch digest."""
    if not isinstance(raw, dict):
        raise ValueError("action_must_be_object")
    action: dict[str, Any]
    if verb == "device.file.read":
        if set(raw) - {"relative_path", "max_bytes"}:
            raise ValueError("unknown_action_field")
        max_bytes = raw.get("max_bytes", 1_048_576)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise ValueError("invalid_max_bytes")
        if max_bytes < 1 or max_bytes > MAX_FILE_BYTES:
            raise ValueError("invalid_max_bytes")
        action = {
            "relative_path": _relative_path(raw.get("relative_path")),
            "max_bytes": max_bytes,
        }
    elif verb == "device.file.write":
        if set(raw) - {"relative_path", "content_digest", "byte_size", "overwrite"}:
            raise ValueError("unknown_action_field")
        digest = raw.get("content_digest")
        size = raw.get("byte_size")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("invalid_content_digest")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
            raise ValueError("invalid_byte_size")
        if not isinstance(raw.get("overwrite", False), bool):
            raise ValueError("invalid_overwrite")
        action = {
            "relative_path": _relative_path(raw.get("relative_path")),
            "content_digest": digest,
            "byte_size": size,
            "overwrite": raw.get("overwrite", False),
        }
    elif verb == "device.command.run":
        if set(raw) - {"argv", "cwd_relative", "timeout_seconds"}:
            raise ValueError("unknown_action_field")
        argv = raw.get("argv")
        if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_ARGS:
            raise ValueError("invalid_argv")
        if any(
            not isinstance(arg, str) or not arg or "\x00" in arg
            or len(arg.encode()) > MAX_ARG_BYTES
            for arg in argv
        ):
            raise ValueError("invalid_argv")
        timeout = raw.get("timeout_seconds", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ValueError("invalid_timeout")
        action = {
            "argv": list(argv),
            "cwd_relative": _relative_path(raw.get("cwd_relative"), optional=True),
            "timeout_seconds": timeout,
        }
    else:
        raise ValueError("unsupported_device_verb")
    params = {"device_id": device_id, "root_id": root_id, **action}
    return action, _action_digest(verb=verb, params=params)


__all__ = [
    "MAX_ARG_BYTES",
    "MAX_ARGS",
    "MAX_FILE_BYTES",
    "MAX_PATH_BYTES",
    "canonical_device_action",
]
