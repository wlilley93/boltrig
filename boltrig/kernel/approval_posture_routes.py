"""Authenticated self-service routes for delegated agent-tool approval posture."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from boltrig.config.dev_posture import is_interactive_credential

from .approval_posture import (
    ApprovalPosture,
    approval_posture_for,
    approval_posture_view,
    persist_approval_posture,
)


def register_approval_posture_routes(app, P, K, audit) -> None:
    @app.get("/v1/me/approval-posture")
    async def get_approval_posture(k=K, p=P) -> dict:
        posture, source = await approval_posture_for(k.store, p.tenant_id, p.subject)
        return approval_posture_view(posture, source)

    @app.put("/v1/me/approval-posture")
    async def put_approval_posture(body: dict, k=K, p=P) -> JSONResponse:
        if p.actor_tier != "human" or not is_interactive_credential(p.credential_kind):
            return JSONResponse(
                {
                    "status": "denied",
                    "reason": "an interactive human session is required",
                },
                status_code=403,
            )
        try:
            posture = ApprovalPosture(body.get("posture"))
        except (TypeError, ValueError):
            return JSONResponse(
                {"status": "error", "reason": "invalid approval posture"},
                status_code=400,
            )
        if posture == ApprovalPosture.FULL_ACCESS and body.get("confirm") != "full_access":
            return JSONResponse(
                {"status": "error", "reason": "full access requires confirmation"},
                status_code=400,
            )
        await persist_approval_posture(k.store, p.tenant_id, p.subject, posture)
        await audit(k, p, "approval_posture.update", {"posture": posture.value})
        return JSONResponse(
            {"status": "ok", **approval_posture_view(posture, "user_override")}
        )
