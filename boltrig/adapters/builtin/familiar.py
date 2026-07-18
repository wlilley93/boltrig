"""The familiar's voluntary-expression adapter (source = 'builtin'), binding WL-3.

The desktop familiar has TWO expression paths, and they are deliberately different:

  * AUTONOMIC (the phenotype) is a downstream projection: boltrig/emotion taps the event stream and
    publishes a mood file the surface reads. The creature cannot help how it feels; nothing chooses it.
  * VOLUNTARY (this adapter) is a deliberate act: the agent CHOOSES to express something - to look at
    you, pulse, flinch, celebrate. That is an action, so it goes through the ONE kernel chokepoint as a
    real verb (``familiar.express``) with a binding, a grant check, and an audit row. There is NO direct
    socket from an agent to the surface (WL-3): the ONLY writer of the express channel is this handler,
    and it only ever runs because the kernel dispatched a granted, audited call to it.

The handler writes a tiny transient record to ``$XDG_RUNTIME_DIR/boltrig-express.json`` that the surface
reads and renders as a short decaying gesture layered over the sustained mood. The write is best-effort
and atomic (tmp + os.replace); it never leaves the kernel/adapter boundary and carries no free text
(gesture is a closed enum), so nothing sensitive reaches the observable surface (K-20).

This is a normal capability, NOT part of boltrig/emotion: emotion is strictly downstream of dispatch
(EMO-1), whereas familiar.express IS a dispatch verb. Keeping it here preserves that separation.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.models import InvocationContext

# The closed set of voluntary gestures the surface knows how to render. A closed enum (not free text)
# keeps the express channel content-free and lets the binding reject anything the body cannot perform.
GESTURES = ("look", "pulse", "flinch", "celebrate", "greet", "nod", "recoil", "preen")

_DEFAULT_TTL_S = 2.0
_MAX_TTL_S = 15.0

_EXPRESS_OUT = {
    "type": "object",
    "properties": {
        "gesture": {"type": "string"},
        "delivered": {"type": "boolean"},
    },
    "required": ["gesture", "delivered"],
}


def _express_path() -> str | None:
    """The voluntary-expression channel, colocated with the phenotype in the runtime dir. None when
    there is no runtime dir (headless/CI): the verb still dispatches + audits, delivery is just a no-op."""
    rt = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    return os.path.join(rt, "boltrig-express.json") if rt else None


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    """Tiny atomic write (unique tmp in the same dir + os.replace); the handler runs on the loop thread.

    The file must be world-readable: the emotion relay runs in the kernel container (uid 10001) while
    the desktop surface reads as a different uid, so chmod 0644 before the rename (mkstemp defaults to
    0600). Same shape as the phenotype file the surface already consumes."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".express-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FamiliarExpressAdapter:
    id = "familiar"
    version = "1.0.0"
    runtime = "file"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="familiar.express",
                noun_id="familiar",
                input_schema={
                    "type": "object",
                    "properties": {
                        "gesture": {"type": "string", "enum": list(GESTURES)},
                        "intensity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "ttl_s": {"type": "number", "minimum": 0.0, "maximum": _MAX_TTL_S},
                    },
                    "required": ["gesture"],
                    "additionalProperties": False,
                },
                output_schema=_EXPRESS_OUT,
                consequence="low",
                description="Deliberately express a gesture through the desktop familiar (voluntary).",
                rate_limit={"per": "minute", "max": 120, "scope": "tenant"},
                # cosmetic + transient: never persist/replay a gesture
                idempotency_mode="disabled",
            ),
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if verb != "familiar.express":
            return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

        gesture = params.get("gesture")
        if gesture not in GESTURES:
            return Result.failure(AdapterError(ErrorClass.INVALID, "unknown gesture"))
        intensity = float(params.get("intensity", 0.7))
        intensity = 0.0 if intensity < 0.0 else (1.0 if intensity > 1.0 else intensity)
        ttl = float(params.get("ttl_s", _DEFAULT_TTL_S))
        ttl = 0.0 if ttl < 0.0 else (_MAX_TTL_S if ttl > _MAX_TTL_S else ttl)

        # No clock read here: the surface detects a NEW gesture by the file's mtime and runs it for
        # ttl_s from first-seen (the same mtime-freshness trick it already uses for the phenotype), so
        # the handler stays deterministic and content-free.
        record = {"v": 1, "gesture": gesture, "intensity": intensity, "ttl_s": ttl}

        delivered = False
        path = _express_path()
        if path is not None:
            try:
                _atomic_write(path, record)
                delivered = True
            except Exception:
                delivered = False  # cosmetic delivery is best-effort; the governed act still happened

        return Result.success({"gesture": gesture, "delivered": delivered})

    async def health(self) -> str:
        return "ok"


def build() -> FamiliarExpressAdapter:
    return FamiliarExpressAdapter()
