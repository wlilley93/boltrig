"""Authenticated redacted process birth-profile observation."""

from __future__ import annotations

from typing import Any

from boltrig.config.birth_profile import birth_profile_view


def register(app, P, K) -> None:
    @app.get("/v1/birth-profile")
    async def get_birth_profile(k=K, p=P) -> dict[str, Any]:
        return await birth_profile_view(k.store, p.tenant_id)


__all__ = ["register"]
