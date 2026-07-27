"""ASGI entrypoint. Run with: uvicorn boltrig.api.asgi:app

The app is built once at import from settings + the manifest (see bootstrap).

Logging is configured HERE and BEFORE ``build_app()``, because uvicorn configures
only its own loggers and leaves root handler-less: without this the whole boot -
including adapter rehydration, which reports success at INFO - is discarded, and
the WARNINGs that survive print through ``logging.lastResort`` with no timestamp
and no logger name.
"""

from __future__ import annotations

from .logging_config import configure_logging

configure_logging()

from .bootstrap import build_app  # noqa: E402  (logging must be live first)

app = build_app()
