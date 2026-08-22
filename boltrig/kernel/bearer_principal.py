"""Resolving a bearer to a Principal, and the workspace it is acting in.

Split out of ``create_app``, which sits at its structural ratchet, and the
split earns its keep: this is the one place a headless caller's WORKSPACE is
decided, which is a security question rather than plumbing.

WHY A BEARER MAY NOW NAME A WORKSPACE. The routes that switch an active context
(``POST /v1/me/active-context`` and ``/v1/me/active-org``) refuse anything
without a first-party session, so a PAT could never select one. A PAT bound its
workspace only when the owner belonged to exactly one, which means a person who
runs two businesses from one account had every headless call run unscoped. An
embedded console needs to say which workspace it is showing, and a per-workspace
agent roster has nothing to key off without it.

WHY A BAD WORKSPACE REFUSES RATHER THAN FALLS BACK. With no active workspace
``effective_grants_for_request`` returns the owner's org grants UN-NARROWED. A
silent fallback would therefore answer a request naming a workspace the caller
cannot reach by WIDENING their authority, which is the wrong direction to fail.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

# The header a headless caller uses to say which workspace it is acting in. The
# dev resolver already reads this name (kernel/app.py), so promoting it here
# keeps one spelling across both paths rather than inventing a second.
WORKSPACE_HEADER = "x-boltrig-workspace"


def bearer_token(request: Request) -> str | None:
    """The ``Authorization: Bearer`` value, or None."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


async def resolve_principal(request: Request, resolver: Any, get_kernel: Any) -> Any:
    """A personal access token, else the configured resolver.

    Headless parity (US-HEAD-02, SEC-37): a PAT bearer resolves to its owner's
    effective grants (PAT scope intersected with the owner's current grants) and
    flows through the same chokepoint as the site. Anything else falls through to
    the configured resolver (OIDC in prod, headers in dev).
    """
    from boltrig.identity.tokens import (
        WorkspaceNotPermitted,
        looks_like_pat,
        resolve_pat_principal,
    )

    token = bearer_token(request)
    if not (token and looks_like_pat(token)):
        return await resolver(request)
    try:
        principal = await resolve_pat_principal(
            get_kernel(request).store,
            token,
            requested_workspace_id=request.headers.get(WORKSPACE_HEADER),
        )
    except WorkspaceNotPermitted as exc:
        # 403, not 404. The token authenticated; only the membership check in
        # ``resolve_active_workspace`` refused, and answering 404 instead would
        # disclose which workspace ids exist by the difference between the two
        # replies.
        raise HTTPException(status_code=403, detail="not a member of that workspace") from exc
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid or expired access token")
    return principal
