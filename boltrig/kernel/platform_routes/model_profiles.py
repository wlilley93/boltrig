"""Caller-visible model profile choices.

Routing internals and credentials deliberately remain in server-held policy.
"""

from __future__ import annotations

from boltrig.config.model_profile_views import visible_model_profiles


def register(app, principal_dep, get_kernel) -> None:
    @app.get("/v1/model-profiles")
    async def list_model_profiles(p=principal_dep) -> dict:
        return {"profiles": visible_model_profiles()}
