"""Unauthenticated liveness and deployment-readiness routes."""

from __future__ import annotations

import asyncio

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.kernel import Kernel


def register_health_routes(app, *, get_kernel) -> None:
    readiness_service_lock = asyncio.Lock()

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
