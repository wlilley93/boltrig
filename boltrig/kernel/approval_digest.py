"""Context-independent canonical action digest for post-dispatch materialisation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .hitl import canonical_approval_value


def approval_action_digest(*, noun: str, verb: str, params: dict[str, Any]) -> str:
    canonical = json.dumps(
        canonical_approval_value(
            {"version": 1, "noun": noun, "verb": verb, "params": params}
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
