"""ASGI entrypoint. Run with: uvicorn boltrig.api.asgi:app

The app is built once at import from settings + the manifest (see bootstrap).

Logging is configured HERE and BEFORE ``build_app()``, because uvicorn configures
only its own loggers and leaves root handler-less: without this the whole boot -
including adapter rehydration, which reports success at INFO - is discarded, and
the WARNINGs that survive print through ``logging.lastResort`` with no timestamp
and no logger name.
"""

from __future__ import annotations

import logging

from .logging_config import configure_logging

configure_logging()

from boltrig.addons import active_addons  # noqa: E402  (logging must be live first)

# Resolve the configured addons at BOOT so a bad value is a startup failure.
# ``active_addons`` raises on a name nothing registers, and it is otherwise first
# reached from the adapter's tool listing - i.e. mid-turn, intermittently, long
# after the deployment that caused it. Failing here makes it loud and immediate.
_ADDONS = active_addons()
logging.getLogger(__name__).info(
    "addons active: %s", ", ".join(f"{a.name}/{a.version}" for a in _ADDONS) or "(none)"
)

from .bootstrap import build_app  # noqa: E402  (logging must be live first)

app = build_app()
