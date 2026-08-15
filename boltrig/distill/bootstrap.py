"""Composition helper for the optional sleep-distillation subsystem.

Mirrors :mod:`boltrig.memory.bootstrap`: the adapter needs the store, audit
writer and cost accountant, so it is composed here from the manifest's
``distill:`` section rather than the ``adapters:`` module_ref list. Disabled
(the default) costs nothing and registers nothing.

Manifest shape::

    distill:
      enabled: true
      sidecar_url: http://host.orb.internal:8930     # trainer/scorer (fixed, operator-owned)
      base_pin: mlx-community/Qwen2.5-7B-Instruct-4bit@main

The register lane remains available. The craft lane refuses typed until an
inactive candidate can enter the governed Codex/Bifrost admission path; an
operator-supplied provider URL is deliberately not a routing seam.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from boltrig.config.environment import is_truthy

log = logging.getLogger("boltrig.bootstrap")

_DEFAULT_SIDECAR_URL = "http://host.orb.internal:8930"


def _bool(value: Any) -> bool:
    return value is True or is_truthy(str(value))


async def register_distill(kernel: Any, tenant_id: str, distill_cfg: Any) -> None:
    """Register distill.* behind the dispatcher when the section enables it."""
    if not distill_cfg or not _bool(distill_cfg.get("enabled")):
        return
    base_pin = str(distill_cfg.get("base_pin") or "").strip()
    if not base_pin:
        # No pin, no training: every corpus digest folds the base pin in, so
        # an unpinned base would make promotion state underivable. Fail toward
        # off, never toward a guessable default (the emotion-addon posture).
        log.warning("distill enabled but base_pin missing; not registering")
        return
    from boltrig.distill.adapter import DistillAdapter

    sidecar_url = str(
        distill_cfg.get("sidecar_url")
        or os.environ.get("BOLTRIG_DISTILL_URL")
        or _DEFAULT_SIDECAR_URL
    )
    adapter = DistillAdapter(
        kernel.store,
        audit=kernel.audit,
        cost=kernel.cost,
        base_pin=base_pin,
        base_url=sidecar_url,
        # a 7B nightly train routinely outlives the default HTTP timeout
        timeout=float(distill_cfg.get("timeout_seconds") or 1800),
    )
    await kernel.register_adapter(tenant_id, adapter)
    log.info("distill subsystem enabled (base_pin=%s)", base_pin)
