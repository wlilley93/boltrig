"""``boltrig initiate`` - seat the founding OWNER ([2026] VJS-COUNTY 7, D7).

Invite-only login needs a first inviter. This bootstrap seats exactly one founding
OWNER (role ``superadmin``, org-wide scope) with a first-party password, so the
owner can then create the invitations that make the console self-sustaining.

It is IDEMPOTENT and REFUSES TO RUN TWICE: if any owner-tier user already exists in
the tenant it exits non-zero without touching anything, so a second run can never
mint a second founder or reset the first owner's password. The password is read
from ``--password``, else ``BOLTRIG_INIT_PASSWORD``, else an interactive prompt; it
is hashed with argon2id and stored apart from the identity row, never logged.

KNOWN LIMIT - the "refusing to run twice" guard is a read-then-write. It lists
users, decides, then upserts, with no transaction spanning the two and no
uniqueness on "at most one owner-tier user per tenant" (`id` IS the email, and
schema.sql gives users a PRIMARY KEY (tenant_id, id) plus a NON-unique email
index). Two runs started concurrently with DIFFERENT emails therefore both read
an empty list and both seat a superadmin. The SEQUENTIAL refusal is real and is
tested, including the different-email case - which is precisely what makes the
race look covered. Accepted rather than closed: running this at all needs shell
on the host, the boundary this command already sits behind, and closing it wants
a partial unique index or an advisory lock.
"""

from __future__ import annotations

from dataclasses import replace

import asyncio
import getpass
import inspect
import os
import sys

from boltrig.identity import hash_password, validate_password_strength
from boltrig.identity.passwords import WeakPassword
from boltrig.models import (
    ActionType,
    AuditEvent,
    OrgMember,
    User,
    Workspace,
    WorkspaceMember,
    utcnow,
)

# The owner tier. superadmin is the console's owner role (reserved for roster
# management); org-admin is the equivalent under the IdP-role vocabulary.
_OWNER_ROLE = "superadmin"
_OWNER_TIERS = frozenset({"superadmin", "org-admin", "admin"})


def _slugify(name: str) -> str:
    """A url-safe handle from a display name (lowercase, hyphenated, ascii-ish)."""
    out = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "default"


async def _run(
    email: str,
    password: str,
    tenant: str,
    *,
    org_name: str | None = None,
    workspace_name: str | None = None,
) -> int:
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
            # D7: this credential was typed at provisioning time, so it is in a
            # shell history and usually in a runbook too. It must not survive as
            # the live prod gate; the resolver clamps this account to the
            # change-password surface until it is rotated.
            must_change_password=True,
        )
        await store.upsert_user(user)
        await store.set_password_credential(tenant, email, hash_password(password))

        # Seed the default org + workspace + OWNER memberships ([2026] VJS-COUNTY 8,
        # D7): invite-only tenancy needs a founding org/workspace and the owner seated
        # into both. Idempotent - ensure_default_org is a no-op if the org exists, and
        # the member/workspace creates are ON CONFLICT DO NOTHING.
        from boltrig.identity.tenancy import ensure_default_org

        org = await ensure_default_org(store, tenant, name=org_name)
        await store.add_org_member(
            OrgMember(user_id=email, tenant_id=tenant, role=_OWNER_ROLE, created_at=now)
        )
        ws_name = workspace_name or org.name
        # A deterministic default workspace id so a re-run seats into the same one.
        ws_id = f"ws_{_slugify(ws_name)}"
        existing_ws = await store.get_workspace(tenant, ws_id)
        if existing_ws is None:
            await store.create_workspace(
                Workspace(
                    id=ws_id, tenant_id=tenant, name=ws_name,
                    slug=f"{_slugify(ws_name)}-{tenant[:6]}", created_at=now, updated_at=now,
                )
            )
        await store.add_workspace_member(
            WorkspaceMember(
                user_id=email, workspace_id=ws_id, tenant_id=tenant,
                role="owner", created_at=now,
            )
        )

        # Audit the owner seed keys-only (D8): the email, never the password.
        await AuditWriter(store).write(
            AuditEvent(
                tenant_id=tenant, ts=now, actor=email, actor_tier="human",
                action_type=ActionType.TOOL_CALL, verb="auth.initiate", status="ok",
                detail={"email": email, "role": _OWNER_ROLE,
                        "org": org.name, "workspace": ws_name},
            )
        )
        print(f"initiate: seated founding OWNER '{email}' (role {_OWNER_ROLE}) "
              f"in org '{org.name}' / workspace '{ws_name}' (tenant '{tenant}').")
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def initiate(
    email: str,
    *,
    password: str | None,
    tenant: str,
    org_name: str | None = None,
    workspace_name: str | None = None,
) -> int:
    """Synchronous entrypoint for the CLI. Resolves the password then runs once."""
    secret = password or os.environ.get("BOLTRIG_INIT_PASSWORD")
    if not secret:
        secret = getpass.getpass("Owner password: ")
        confirm = getpass.getpass("Confirm password: ")
        if secret != confirm:
            print("initiate: passwords did not match", file=sys.stderr)
            return 2
    return asyncio.run(
        _run(email, secret, tenant, org_name=org_name, workspace_name=workspace_name)
    )


async def _run_set_password(email: str, password: str, tenant: str) -> int:
    """Set (or reset) the first-party password of an EXISTING user.

    The bridge from an SSO / Cloudflare-Access identity to session auth ([2026]
    VJS-COUNTY 7): the user must already exist (this is not a signup - it never
    creates an identity or a grant), and its argon2id hash is stored apart from the
    identity row, never logged. Box-level operation (running it needs shell on the
    host), audited keys-only. Idempotent: re-running rotates the password.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        print("set-password: a valid --email is required", file=sys.stderr)
        return 2
    try:
        validate_password_strength(password)
    except WeakPassword as exc:
        print(f"set-password: {exc}", file=sys.stderr)
        return 2

    from boltrig.api.bootstrap import build_store
    from boltrig.kernel.audit import AuditWriter
    from boltrig.store.postgres import set_current_tenant

    store = await build_store()
    try:
        set_current_tenant(tenant)
        user = await store.get_user(tenant, email)
        if user is None:
            print(f"set-password: no user '{email}' in tenant '{tenant}'; this sets a "
                  "password for an EXISTING identity, it does not create one.",
                  file=sys.stderr)
            return 3
        await store.set_password_credential(tenant, email, hash_password(password))
        # Rotating the credential IS the rotation D7 requires, so this discharges
        # the flag - otherwise the operator path out of the clamp would not be one.
        if user.must_change_password:
            await store.upsert_user(replace(user, must_change_password=False))
        await AuditWriter(store).write(
            AuditEvent(
                tenant_id=tenant, ts=utcnow(), actor=email, actor_tier="human",
                action_type=ActionType.TOOL_CALL, verb="auth.set_password", status="ok",
                detail={"email": email},
            )
        )
        print(f"set-password: password set for '{email}' in tenant '{tenant}'. They can "
              "now log in with BOLTRIG_AUTH_MODE=session.")
        return 0
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def set_password(email: str, *, password: str | None, tenant: str) -> int:
    """Synchronous entrypoint: resolve the password (flag / env / prompt) then run."""
    secret = password or os.environ.get("BOLTRIG_INIT_PASSWORD")
    if not secret:
        secret = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")
        if secret != confirm:
            print("set-password: passwords did not match", file=sys.stderr)
            return 2
    return asyncio.run(_run_set_password(email, secret, tenant))
