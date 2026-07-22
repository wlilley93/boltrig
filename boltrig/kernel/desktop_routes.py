"""Desktop-hands pull surface (decision 0016, DH-1).

The host-side executor's ONLY interface to pending desktop commands. The kernel
cannot reach the compositor, so a granted ``desktop.*`` dispatch lands in the
shared HandsRegistry and the executor pulls it here:

  - ``GET  /v1/hands/commands``                    - claim + return pending commands
  - ``POST /v1/hands/commands/{cmd_id}/receipt``   - report the execution receipt

Both routes require the normal authenticated principal (SEC-01) - unlike the
channel ingress there is no signature path, the executor is a first-class
caller. Claiming is mark-on-read inside the registry: a returned command is
already claimed, so a second poll (or a second executor) can never receive and
double-execute it. Every receipt is audited (SEC-16) so the host-side execution
is kernel-recorded alongside the dispatch that authorised it.
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse

from boltrig.models import ActionType, AuditEvent, utcnow

# The closed receipt-status set the adapter maps onto its output schema.
RECEIPT_STATUSES = ("ok", "error")

_MAX_ERROR_LEN = 240


async def _audit(kernel, p, verb: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, noun="desktop", verb=verb, status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


def register_desktop_routes(app, *, principal_dep, get_kernel, registry) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    def _hands(k):
        # ``registry`` is either the shared instance (tests / explicit wiring) or
        # a resolver pulling it off the live kernel: the factory path builds the
        # kernel on the serving loop, AFTER routes are registered, so it cannot
        # be captured as an instance here.
        return registry(k) if callable(registry) else registry

    @app.get("/v1/hands/commands")
    async def hands_commands(k=K, p=P) -> JSONResponse:
        reg = _hands(k)
        if reg is None:
            return JSONResponse({"error": "hands_unavailable"}, status_code=503)
        # Claim-on-return: pending() filters expired/unclaimed, claim() marks
        # each returned command so only THIS poll gets it. No awaits between the
        # two, so the read+mark is atomic on the kernel loop.
        claimed = []
        for cmd in reg.pending():
            if reg.claim(cmd["id"]) is not None:
                claimed.append(cmd)
        return JSONResponse({"commands": claimed})

    @app.post("/v1/hands/commands/{cmd_id}/receipt")
    async def hands_receipt(cmd_id: str, body: dict, k=K, p=P) -> JSONResponse:
        reg = _hands(k)
        if reg is None:
            return JSONResponse({"error": "hands_unavailable"}, status_code=503)
        status = str(body.get("status") or "")
        if status not in RECEIPT_STATUSES:
            return JSONResponse(
                {"status": "error", "reason": "status must be ok|error"}, status_code=400
            )
        receipt = {"status": status}
        for key in ("result", "side_effects", "error"):
            if key in body:
                receipt[key] = body[key]
        if not reg.complete(cmd_id, receipt):
            # unknown or expired id (the dispatch already timed out, or the id
            # was never issued): refuse, and do not audit a no-op as execution
            return JSONResponse({"error": "not_found"}, status_code=404)
        detail = {"command": cmd_id, "receipt_status": status}
        if isinstance(receipt.get("error"), str):
            detail["error"] = receipt["error"][:_MAX_ERROR_LEN]
        await _audit(k, p, "desktop.hands.receipt", detail)
        return JSONResponse({"status": "ok"})
