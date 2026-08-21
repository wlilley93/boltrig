"""The unauthenticated routes, all of them, in one file.

Liveness, deployment readiness, and the product's own name. Kept together
deliberately: "what can be reached without a session" is a question somebody
has to be able to answer by reading one file, and a second module of public
routes elsewhere is how that answer stops being reliable.
"""

from __future__ import annotations

import asyncio

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.branding import product_identity
from boltrig.kernel import Kernel


def register_health_routes(app, *, get_kernel) -> None:
    readiness_service_lock = asyncio.Lock()

    @app.get("/v1/branding")
    async def branding() -> dict:
        # Unauthenticated because the sign-in screen is the first surface that
        # needs the product's name and it renders before anyone has a session.
        # It discloses which shape this deployment is, which the login page's
        # own branding would show anyway.
        return product_identity()

    @app.get("/healthz")
    async def healthz(k: Kernel = Depends(get_kernel)) -> dict:
        health = k.loader.health_snapshot()
        return {
            "status": "ok",
            "adapters": {
                f"{tenant}/{adapter}": value for (tenant, adapter), value in health.items()
            },
        }

    @app.get("/readyz")
    async def readyz(
        request: Request,
        k: Kernel = Depends(get_kernel),
    ) -> JSONResponse:
        from boltrig.api.readiness import ReadinessService

        service = getattr(request.app.state, "readiness_service", None)
        if service is None:
            async with readiness_service_lock:
                service = getattr(request.app.state, "readiness_service", None)
                if service is None:
                    platform = getattr(request.app.state, "platform", {}) or {}
                    service = platform.get("readiness")
                    if service is None:
                        service = ReadinessService(
                            k,
                            status_provider=platform.get("status"),
                            password_reset_notifier=platform.get("password_reset_notifier"),
                            password_reset_probe=platform.get("password_reset_readiness_probe"),
                        )
                    request.app.state.readiness_service = service
        report = await service.check()
        return JSONResponse(
            report,
            status_code=200 if report.get("status") == "ready" else 503,
        )


__all__ = ["register_health_routes"]
