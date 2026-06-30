"""ASGI entrypoint. Run with: uvicorn boltrig.api.asgi:app

The app is built once at import from settings + the manifest (see bootstrap).
"""

from __future__ import annotations

from .bootstrap import build_app

app = build_app()
