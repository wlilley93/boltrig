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


def register_familiar_phenotype_routes(app: Any, *, principal_dep: Any) -> None:
    principal = Depends(principal_dep)

    @app.get("/v1/familiar/phenotype")
    async def familiar_phenotype(p=principal):
        """Owner-scoped, cosmetic, read-only; carries no conversation content."""
        return read_phenotype_projection()
