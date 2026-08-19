"""Self-scoped identity: who the caller is, and where they may act.

``GET /v1/me`` is the contract a HOST APPLICATION reads instead of trusting its
own session. Opbox is the first: it stops owning identity and asks Boltrig on
each request who this person is, which org and workspace they are in, and which
workspaces they may switch to. Everything here is the caller's OWN record, so
it discloses nothing they could not already reach.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse


def register_org_discovery_routes(
    app: Any, *, principal_dep: Any, get_kernel: Any
) -> None:
    principal = Depends(principal_dep)
    kernel = Depends(get_kernel)

    @app.get("/v1/me")  # type: ignore[untyped-decorator]
    async def me(request: Request, k: Any = kernel, p: Any = principal) -> JSONResponse:
        """The resolved caller, as the kernel already understands them.

        A projection of the Principal, which the resolver has already built and
        re-authorised: ``active_workspace_id`` in particular is re-checked
        against CURRENT membership on every request, so a revoked membership
        disappears here without anything having to expire.

        ``credential_kind`` is reported because it CHANGES WHAT THE CALLER MAY
        DO: a PAT can select a workspace by header but cannot switch the active
        ORG, which needs a first-party session. A host rendering a switcher has
        to know which of the two it is holding rather than discovering it from a
        400.
        """
        user = await k.store.get_user(p.tenant_id, p.subject)
        workspaces = await k.store.list_workspaces_for_user(p.tenant_id, p.subject)
        return JSONResponse(
            {
                "subject": p.subject,
                "email": getattr(user, "email", None),
                "display_name": getattr(user, "display_name", None),
                "tenant_id": p.tenant_id,
                "role": p.role,
                "actor_tier": p.actor_tier,
                "credential_kind": getattr(p, "credential_kind", "machine"),
                "active_workspace_id": p.active_workspace_id,
                "workspaces": [
                    {
                        "id": w.id,
                        "name": w.name,
                        "slug": w.slug,
                        "active": w.id == p.active_workspace_id,
                    }
                    for w in workspaces
                ],
            }
        )

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
