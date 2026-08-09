"""Composition helper for the optional sleep-distillation subsystem.

Mirrors :mod:`boltrig.memory.bootstrap`: the adapter needs the store, audit
writer and cost accountant, so it is composed here from the manifest's
``distill:`` section rather than the ``adapters:`` module_ref list. Disabled
(the default) costs nothing and registers nothing.

Manifest shape::

    distill:
      enabled: true
      sidecar_url: http://host.orb.internal:8930     # trainer/scorer (fixed, operator-owned)
      serve_url: http://host.orb.internal:8931/v1    # candidate chat serving (mlx_lm.server)
      base_pin: mlx-community/Qwen2.5-7B-Instruct-4bit@main

``serve_url`` unset leaves the register lane fully working and makes the
craft gate refuse typed (the trainer serves no chat completions).
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
    serve_url = str(
        distill_cfg.get("serve_url")
        or os.environ.get("BOLTRIG_DISTILL_SERVE_URL")
        or ""
    ) or None
    adapter = DistillAdapter(
        kernel.store,
        audit=kernel.audit,
        cost=kernel.cost,
        base_pin=base_pin,
        base_url=sidecar_url,
        serve_url=serve_url,  # unset => craft gate refuses typed
    )
    await kernel.register_adapter(tenant_id, adapter)
    log.info("distill subsystem enabled (base_pin=%s)", base_pin)
