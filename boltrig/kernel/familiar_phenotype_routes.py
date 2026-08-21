"""GET /v1/familiar/phenotype - the Worker surface's read of the emotion add-on.

Downstream-only by construction: this module reads the same versioned phenotype
FILE the desktop familiar reads (decision 0013), so the kernel keeps exactly one
emotion touch (the relay factory seam) and this module imports nothing from
``boltrig.emotion`` (EMO-1). The response is keys-and-numbers only (EMO-2):
whitelisted scalars, clamped to 0..1, non-finite dropped. Every failure - no
runtime dir, missing file, stale file, malformed JSON, oversized file - answers
with the resting shape rather than an error, because a cosmetic side-channel
must never teach a client to treat its absence as a fault (P9).
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Depends

# Mirrors the desktop reader's constants (beelink familiar main.c): a phenotype
# older than PHENO_FRESH_S falls back to resting; the real file is ~250 bytes.
PHENO_FRESH_S = 5.0
PHENO_MAX_BYTES = 4096

# The ten observable scalars (decision 0013 + the 0024 attachment scalar).
PHENOTYPE_SCALARS = (
    "valence", "arousal", "irritation", "fatigue", "attention",
    "social", "buoyancy", "luminosity", "tension", "attachment",
)

_RESTING: dict[str, Any] = {"v": 1, "fresh": False, "phenotype": None}


def _phenotype_path() -> Path | None:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        return None
    return Path(runtime_dir) / "boltrig-phenotype.json"


def read_phenotype_projection(now: float | None = None) -> dict[str, Any]:
    """Bounded projection of the published phenotype file; resting on ANY failure."""
    moment = time.time() if now is None else now
    path = _phenotype_path()
    if path is None:
        return dict(_RESTING)
    try:
        stat = path.stat()
        if stat.st_size > PHENO_MAX_BYTES or moment - stat.st_mtime > PHENO_FRESH_S:
            return dict(_RESTING)
        document = json.loads(path.read_bytes())
        raw = document.get("phenotype")
        if not isinstance(raw, dict):
            return dict(_RESTING)
        scalars: dict[str, float] = {}
        for key in PHENOTYPE_SCALARS:
            value = raw.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                scalars[key] = min(1.0, max(0.0, float(value)))
        if not scalars:
            return dict(_RESTING)
        return {"v": 1, "fresh": True, "phenotype": scalars}
    except Exception:  # noqa: BLE001 - fail toward resting, never toward a fault
        return dict(_RESTING)


#: The companion the Worker may announce as adopted; a free-text id would let
#: a client write arbitrary strings into the relay stream.
_CHARACTER_ID_MAX = 64


def register_familiar_phenotype_routes(
    app: Any, *, principal_dep: Any, get_kernel: Any = None
) -> None:
    principal = Depends(principal_dep)

    @app.get("/v1/familiar/phenotype")
    async def familiar_phenotype(p=principal):
        """Owner-scoped, cosmetic, read-only; carries no conversation content."""
        return read_phenotype_projection()

    if get_kernel is None:
        return

    # The two WRITE affordances publish plain relay events; the emotion relay's
    # tap interprets them, so this module still imports nothing from
    # ``boltrig.emotion`` (EMO-1) and a deployment without the emotion add-on
    # accepts them as inert frames. Both are cosmetic and tenant-scoped: the
    # reset clears the companion's accumulated mood (never memory or data),
    # and the adoption announcement is the explicit novelty affordance - its
    # appraisal is throttled per (tenant, kind) by the relay's event map, so
    # flicking skins in Settings cannot pump the mood.
    kernel = Depends(get_kernel)

    @app.post("/v1/familiar/emotion/reset")
    async def familiar_emotion_reset(p=principal, k=kernel):
        k.events.publish(p.tenant_id, "emotion", {"type": "emotion_reset"})
        return {"status": "ok"}

    @app.post("/v1/familiar/emotion/adopted")
    async def familiar_emotion_adopted(body: dict, p=principal, k=kernel):
        character = body.get("character")
        if not isinstance(character, str) or not character.strip():
            return {"status": "error", "reason": "character is required"}
        if len(character) > _CHARACTER_ID_MAX:
            return {"status": "error", "reason": "character id is too long"}
        k.events.publish(
            p.tenant_id,
            "emotion",
            {"type": "character_adopted", "character": character.strip()},
        )
        return {"status": "ok"}
