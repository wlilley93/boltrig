"""``boltrig mint-token`` - mint a Personal Access Token for an EXISTING user.

The box-level twin of the ``POST /v1/me/tokens`` route (SEC-34): a PAT lets a
first-party identity drive the kernel API (chat, tool stream, HITL) without an
interactive session, which is what a headless client or a live smoke test needs.
Running it needs shell on the host, so it is trusted at the box boundary and does
not require a CSRF-guarded session - but it is NOT a privilege escalation: the
token is capped at the user's CURRENT ORG grants (``current_grants_for_user``),
and the runtime re-check in ``resolve_pat_principal`` re-applies a cap at use time
even if the user's grants later shrink.

The mint cap is deliberately stated as the ORG cap and no longer as "exactly as
the route is", which it never was. The route resolves through the session, so its
cap is the org grants NARROWED by the active workspace role; this has no session
and no active workspace, so it cannot compute that ceiling at mint time. The
difference used to be load-bearing - a viewer got a write-capable token here and a
read-only one from the route - and is not any more, because
``resolve_pat_principal`` now applies the workspace ceiling at USE time on both
paths. A token minted here can therefore be broader on paper than it will ever be
in effect, which is the safe direction, and is why the wording matters.

It never creates an identity or a grant: the user must already exist (mirrors
``set-password``). The secret is printed ONCE and only its sha256 is stored; the
mint is audited keys-only (id + name + effective scope, never the secret).
"""

from __future__ import annotations

import asyncio
import inspect
import sys

from boltrig.models import ActionType, AuditEvent, utcnow


async def _run_mint_token(
    email: str,
    tenant: str,
    *,
    name: str,
    scope: list[str] | None,
    ttl_days: int | None,
) -> int:
    from boltrig.api.bootstrap import build_store
    from boltrig.identity.provisioning import current_grants_for_user
    from boltrig.identity.tokens import mint_pat
    from boltrig.kernel.audit import AuditWriter
    from boltrig.store.postgres import set_current_tenant

    email = email.strip().lower()
    if not email or "@" not in email:
        print("mint-token: a valid --email is required", file=sys.stderr)
        return 2
    name = (name or "").strip()
    if not name:
        print("mint-token: a --name for the token is required", file=sys.stderr)
        return 2

    store = await build_store()
    try:
        set_current_tenant(tenant)  # bind before any RLS-scoped read/write
        user = await store.get_user(tenant, email)
        if user is None:
            print(
                f"mint-token: no user '{email}' in tenant '{tenant}'; this mints a "
                "token for an EXISTING identity, it does not create one.",
                file=sys.stderr,
            )
            return 3
        # The user's current grants are the cap (SEC-34): an explicit --scope is
        # narrowed to what the user actually holds; absent, the token inherits the
        # user's own allow set. It can never be minted above the user.
        grants = current_grants_for_user(user)
        pat, secret = await mint_pat(
            store, tenant_id=tenant, user_id=email, name=name,
            requested_scope=scope, user_grants=grants, ttl_days=ttl_days,
        )
        await AuditWriter(store).write(
            AuditEvent(
                tenant_id=tenant, ts=utcnow(), actor=email, actor_tier="human",
                action_type=ActionType.TOOL_CALL, verb="token.mint", status="ok",
                detail={"id": pat.id, "name": name, "scope": list(pat.scope)},
            )
        )
        # The secret is shown ONCE. Print it on its own line, unadorned, so it is
        # trivially capturable (`... | tail -1`) and never re-derivable afterwards.
        print(
            f"mint-token: minted PAT '{name}' for '{email}' in tenant '{tenant}'\n"
            f"  id:      {pat.id}\n"
            f"  scope:   {', '.join(pat.scope) or '(none)'}\n"
            f"  expires: {pat.expires_at.isoformat() if pat.expires_at else '(never)'}\n"
            f"  secret (shown once, store it now):",
            file=sys.stderr,
        )
        print(secret)
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def mint_token(
    email: str,
    *,
    tenant: str,
    name: str,
    scope: list[str] | None,
    ttl_days: int | None,
) -> int:
    """Synchronous entrypoint for the CLI."""
    return asyncio.run(
        _run_mint_token(email, tenant, name=name, scope=scope, ttl_days=ttl_days)
    )
