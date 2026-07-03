"""``boltrig initiate`` - seat the founding OWNER ([2026] VJS-COUNTY 7, D7).

Invite-only login needs a first inviter. This bootstrap seats exactly one founding
OWNER (role ``superadmin``, org-wide scope) with a first-party password, so the
owner can then create the invitations that make the console self-sustaining.

It is IDEMPOTENT and REFUSES TO RUN TWICE: if any owner-tier user already exists in
the tenant it exits non-zero without touching anything, so a second run can never
mint a second founder or reset the first owner's password. The password is read
from ``--password``, else ``BOLTRIG_INIT_PASSWORD``, else an interactive prompt; it
is hashed with argon2id and stored apart from the identity row, never logged.
"""

from __future__ import annotations

import asyncio
import getpass
import inspect
import os
import sys

from boltrig.identity import hash_password, validate_password_strength
from boltrig.identity.passwords import WeakPassword
from boltrig.models import ActionType, AuditEvent, User, utcnow

# The owner tier. superadmin is the console's owner role (reserved for roster
# management); org-admin is the equivalent under the IdP-role vocabulary.
_OWNER_ROLE = "superadmin"
_OWNER_TIERS = frozenset({"superadmin", "org-admin", "admin"})


async def _run(email: str, password: str, tenant: str) -> int:
    from boltrig.api.bootstrap import build_store
    from boltrig.kernel.audit import AuditWriter
    from boltrig.store.postgres import set_current_tenant

    email = email.strip().lower()
    if not email or "@" not in email:
        print("initiate: a valid --email is required", file=sys.stderr)
        return 2
    try:
        validate_password_strength(password)
    except WeakPassword as exc:
        print(f"initiate: {exc}", file=sys.stderr)
        return 2

    store = await build_store()
    try:
        set_current_tenant(tenant)  # bind before any RLS-scoped read/write
        # Idempotent + run-once: refuse if an owner already exists (D7).
        existing = await store.list_users(tenant)
        owner = next((u for u in existing if u.role in _OWNER_TIERS), None)
        if owner is not None:
            print(
                f"initiate: an owner already exists for tenant '{tenant}' "
                f"(user '{owner.id}', role '{owner.role}'); refusing to run twice.",
                file=sys.stderr,
            )
            return 3

        now = utcnow()
        user = User(
            id=email, tenant_id=tenant, email=email, role=_OWNER_ROLE,
            scope={"all": True}, status="active", source="initiate",
            last_seen_at=now, created_at=now,
        )
        await store.upsert_user(user)
        await store.set_password_credential(tenant, email, hash_password(password))
        # Audit the owner seed keys-only (D8): the email, never the password.
        await AuditWriter(store).write(
            AuditEvent(
                tenant_id=tenant, ts=now, actor=email, actor_tier="human",
                action_type=ActionType.TOOL_CALL, verb="auth.initiate", status="ok",
                detail={"email": email, "role": _OWNER_ROLE},
            )
        )
        print(f"initiate: seated founding OWNER '{email}' (role {_OWNER_ROLE}) "
              f"in tenant '{tenant}'.")
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def initiate(email: str, *, password: str | None, tenant: str) -> int:
    """Synchronous entrypoint for the CLI. Resolves the password then runs once."""
    secret = password or os.environ.get("BOLTRIG_INIT_PASSWORD")
    if not secret:
        secret = getpass.getpass("Owner password: ")
        confirm = getpass.getpass("Confirm password: ")
        if secret != confirm:
            print("initiate: passwords did not match", file=sys.stderr)
            return 2
    return asyncio.run(_run(email, secret, tenant))
