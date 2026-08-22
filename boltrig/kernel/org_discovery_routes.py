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

#: How many verbs one question may name. A host batches the checks a page needs
#: rather than asking per tool, so the bound has to be generous; it exists so an
#: unbounded list cannot turn a self-scoped read into arbitrary work.
MAX_PERMIT_QUESTIONS = 200


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

    @app.post("/v1/me/permits")  # type: ignore[untyped-decorator]
    async def me_permits(body: dict, k: Any = kernel, p: Any = principal) -> JSONResponse:
        """Whether this caller may run each named verb."""
        return await answer_permit_questions(k.store, p, body)

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


async def answer_permit_questions(store: Any, principal: Any, body: dict[str, Any]) -> JSONResponse:
    """Whether this caller may run each named verb.

    AN ASK, NOT A DUMP, and the distinction is the point. Returning the caller's
    raw allow/deny patterns would be one round trip instead of many, and it would
    make every host reimplement ``GrantSet.permits``: deny-dominance, terminal
    wildcards, and the nothing-matched-is-deny floor. A second implementation of
    an authority predicate is the worst place in the system for a subtle
    divergence, because the failure is a host granting what this kernel would
    have refused. The patterns stay here and the verdict travels.

    BOTH AUTHORITIES, exactly as the dispatcher composes them: the tenant ceiling
    AND the caller's own grants (US-IAM-04). Answering on either alone is how an
    upper bound gets mistaken for a selection, which is the reasoning
    ``capability_offer.offer_candidates`` records at its own seam. The caller's
    grants arrive already narrowed by their workspace role, so a workspace member
    does not get an org answer.

    A caller asking about THEMSELVES, so it discloses nothing they could not
    learn by trying the verb; it only lets them learn it without a failed write.
    """
    verbs, refusal = _permit_questions(body)
    if refusal is not None:
        return refusal
    ceiling = await store.get_tenant_permissions(principal.tenant_id)
    return JSONResponse(
        {
            "tenant_id": principal.tenant_id,
            "active_workspace_id": principal.active_workspace_id,
            "verbs": {
                verb: bool(
                    ceiling.grants.permits(verb) and principal.grants.permits(verb)
                )
                for verb in verbs
            },
        }
    )


def _permit_questions(
    body: dict[str, Any],
) -> tuple[list[str], JSONResponse | None]:
    """The asked-about verbs, or the refusal that says why there are none."""
    raw = body.get("verbs")
    if not isinstance(raw, list) or not raw:
        return [], JSONResponse(
            {"status": "error", "reason": "verbs must be a non-empty list"},
            status_code=400,
        )
    if len(raw) > MAX_PERMIT_QUESTIONS:
        return [], JSONResponse(
            {"status": "error", "reason": "too_many_verbs"}, status_code=400
        )
    verbs = [str(item) for item in raw]
    # Patterns are refused rather than evaluated. ``permits`` takes a verb id;
    # asking "do I hold control.*" is a different question with a different
    # answer, and quietly treating a pattern as an id would answer the wrong one
    # confidently.
    if any("*" in verb for verb in verbs):
        return [], JSONResponse(
            {"status": "error", "reason": "verb patterns are not questions"},
            status_code=400,
        )
    return verbs, None
