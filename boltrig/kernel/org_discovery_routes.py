"""Self-scoped organisation discovery for first-party session switching."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse


def register_org_discovery_routes(
    app: Any, *, principal_dep: Any, get_kernel: Any
) -> None:
    principal = Depends(principal_dep)
    kernel = Depends(get_kernel)

    @app.get("/v1/me/orgs")  # type: ignore[untyped-decorator]
    async def my_organisations(
        request: Request, k: Any = kernel, p: Any = principal
    ) -> JSONResponse:
        """List session switch candidates only from ``list_orgs_for_email`` for
        the caller identity.

        The global identity index is enumeration metadata, not authority. Every
        selection still goes through ``POST /v1/me/active-org``, which binds the
        target tenant and re-authorises its live membership before switching.
        PAT callers cannot switch a session and therefore see only their bound
        organisation.
        """

        session = getattr(request.state, "boltrig_session", None)
        if session is None:
            ids = [p.tenant_id]
        else:
            ids = await k.store.list_orgs_for_email(p.subject)
            if not ids:
                ids = [p.tenant_id]
        return JSONResponse(
            {
                "organisations": [
                    {"id": org_id, "active": org_id == p.tenant_id}
                    for org_id in sorted(set(ids))
                ]
            }
        )


__all__ = ["register_org_discovery_routes"]
