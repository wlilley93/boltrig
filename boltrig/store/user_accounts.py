"""User-account store domain (arc-1 structural partial): users, personal access
tokens, invitations and first-party password credentials - extracted verbatim
from ``store/postgres.py`` + ``store/memory.py``. PG host: ``self._pool``; Mem
host: ``self._users``/``_pats``/``_invites``/``_password_creds``. Public surface
unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import PersonalAccessToken, User, UserInvitation

from .rows import _invitation, _pat, _user


class UserAccountsStorePG:
    """User/PAT/invitation/password-credential methods for ``PostgresStore``."""

    async def upsert_user(self, u: User):
        await self._pool.execute(
            """INSERT INTO users (id, tenant_id, email, display_name, groups, role, scope,
                                  status, source, source_group, last_seen_at, created_at,
                                  must_change_password)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 email=EXCLUDED.email, display_name=EXCLUDED.display_name,
                 groups=EXCLUDED.groups, role=EXCLUDED.role, scope=EXCLUDED.scope,
                 status=EXCLUDED.status, source=EXCLUDED.source,
                 source_group=EXCLUDED.source_group, last_seen_at=EXCLUDED.last_seen_at,
                 must_change_password=EXCLUDED.must_change_password""",
            u.id, u.tenant_id, u.email, u.display_name, u.groups, u.role, u.scope,
            u.status, u.source, u.source_group, u.last_seen_at, u.created_at,
            u.must_change_password,
        )

    async def get_user(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM users WHERE tenant_id=$1 AND id=$2", tenant_id, user_id
        )
        return _user(row)

    async def list_users(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM users WHERE tenant_id=$1 ORDER BY created_at DESC", tenant_id
        )
        return [_user(r) for r in rows]

    async def add_pat(self, p: PersonalAccessToken):
        await self._pool.execute(
            """INSERT INTO personal_access_tokens
               (id, tenant_id, user_id, name, token_hash, scope, created_at,
                expires_at, last_used_at, revoked)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            p.id, p.tenant_id, p.user_id, p.name, p.token_hash, p.scope, p.created_at,
            p.expires_at, p.last_used_at, p.revoked,
        )

    async def get_pat(self, tenant_id, pat_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM personal_access_tokens WHERE tenant_id=$1 AND id=$2",
            tenant_id, pat_id,
        )
        return _pat(row)

    async def get_pat_by_hash(self, token_hash):
        row = await self._pool.fetchrow(
            "SELECT * FROM personal_access_tokens WHERE token_hash=$1", token_hash
        )
        return _pat(row)

    async def list_pats(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM personal_access_tokens WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC""",
            tenant_id, user_id,
        )
        return [_pat(r) for r in rows]

    async def update_pat(self, p: PersonalAccessToken):
        await self._pool.execute(
            """UPDATE personal_access_tokens SET last_used_at=$3, revoked=$4
               WHERE tenant_id=$1 AND id=$2""",
            p.tenant_id, p.id, p.last_used_at, p.revoked,
        )

    async def add_invitation(self, inv: UserInvitation):
        await self._pool.execute(
            """INSERT INTO user_invitations
               (id, tenant_id, email, intended_role, intended_scope, invited_by,
                created_at, expires_at, status, token_hash,
                workspace_id, provision_workspace_name, provision_org_name)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            inv.id, inv.tenant_id, inv.email, inv.intended_role, inv.intended_scope,
            inv.invited_by, inv.created_at, inv.expires_at, inv.status, inv.token_hash,
            inv.workspace_id, inv.provision_workspace_name, inv.provision_org_name,
        )

    async def claim_invitation_by_token_hash(self, tenant_id, token_hash, now):
        row = await self._pool.fetchrow(
            """UPDATE user_invitations SET status='accepted'
               WHERE tenant_id=$1 AND token_hash=$2 AND status='pending'
                 AND (expires_at IS NULL OR expires_at > $3)
               RETURNING *""",
            tenant_id, token_hash, now,
        )
        return _invitation(row)

    async def consume_invitation(self, tenant_id, inv_id):
        # Atomic single-use consume (D1): pending -> accepted, True only for the
        # winner. RETURNING makes the CAS observable across concurrent redeemers.
        row = await self._pool.fetchrow(
            """UPDATE user_invitations SET status='accepted'
               WHERE tenant_id=$1 AND id=$2 AND status='pending'
               RETURNING id""",
            tenant_id, inv_id,
        )
        return row is not None

    async def set_password_credential(self, tenant_id, user_id, password_hash):
        await self._pool.execute(
            """INSERT INTO user_credentials (tenant_id, user_id, password_hash, updated_at)
               VALUES ($1,$2,$3, now())
               ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                 password_hash=EXCLUDED.password_hash, updated_at=now()""",
            tenant_id, user_id, password_hash,
        )

    async def get_password_credential(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT password_hash FROM user_credentials WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return None if row is None else row["password_hash"]

    async def get_invitation(self, tenant_id, inv_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_invitations WHERE tenant_id=$1 AND id=$2", tenant_id, inv_id
        )
        return _invitation(row)

    async def list_invitations(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM user_invitations WHERE tenant_id=$1 ORDER BY created_at DESC",
            tenant_id,
        )
        return [_invitation(r) for r in rows]

    async def find_pending_invitation(self, tenant_id, email):
        row = await self._pool.fetchrow(
            """SELECT * FROM user_invitations
               WHERE tenant_id=$1 AND status='pending' AND lower(email)=lower($2)
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id, email,
        )
        return _invitation(row)

    async def update_invitation(self, inv: UserInvitation):
        await self._pool.execute(
            "UPDATE user_invitations SET status=$3 WHERE tenant_id=$1 AND id=$2",
            inv.tenant_id, inv.id, inv.status,
        )


class UserAccountsStoreMem:
    """User/PAT/invitation/password-credential methods for ``InMemoryStore``."""

    async def upsert_user(self, user):
        self._users[(user.tenant_id, user.id)] = user

    async def get_user(self, tenant_id, user_id):
        return self._users.get((tenant_id, user_id))

    async def list_users(self, tenant_id):
        return [u for (t, _), u in self._users.items() if t == tenant_id]

    async def add_pat(self, pat):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._pats.setdefault((pat.tenant_id, pat.id), pat)

    async def get_pat(self, tenant_id, pat_id):
        return self._pats.get((tenant_id, pat_id))

    async def get_pat_by_hash(self, token_hash):
        # The secret carries identity; lookup is by hash across tenants (the hash
        # is globally unique). Constant-time compare so the lookup does not leak a
        # hash prefix via timing (CRYPTO-04).
        import hmac as _hmac

        for pat in self._pats.values():
            if _hmac.compare_digest(pat.token_hash, token_hash):
                return pat
        return None

    async def list_pats(self, tenant_id, user_id):
        return [p for (t, _), p in self._pats.items() if t == tenant_id and p.user_id == user_id]

    async def update_pat(self, pat):
        # Narrow writer (mirrors the PG UPDATE): only last_used_at + revoked are
        # ever written back; a missing row is a no-op, never an insert.
        existing = self._pats.get((pat.tenant_id, pat.id))
        if existing is not None:
            existing.last_used_at = pat.last_used_at
            existing.revoked = pat.revoked

    async def add_invitation(self, inv):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._invites.setdefault((inv.tenant_id, inv.id), inv)

    async def get_invitation(self, tenant_id, inv_id):
        return self._invites.get((tenant_id, inv_id))

    async def list_invitations(self, tenant_id):
        return [i for (t, _), i in self._invites.items() if t == tenant_id]

    async def find_pending_invitation(self, tenant_id, email):
        target = email.strip().lower()
        matches = [
            inv
            for (t, _), inv in self._invites.items()
            if t == tenant_id and inv.status == "pending" and inv.email.strip().lower() == target
        ]
        # Newest first, matching the PG ORDER BY created_at DESC LIMIT 1.
        return max(matches, key=lambda i: i.created_at, default=None)

    async def claim_invitation_by_token_hash(self, tenant_id, token_hash, now):
        """Atomically claim one pending, unexpired first-party invite bearer."""
        import hmac as _hmac

        for (t, _), inv in self._invites.items():
            if (
                t == tenant_id
                and inv.status == "pending"
                and inv.token_hash
                and _hmac.compare_digest(inv.token_hash, token_hash)
                and (inv.expires_at is None or inv.expires_at > now)
            ):
                inv.status = "accepted"
                return replace(inv)
        return None

    async def consume_invitation(self, tenant_id, inv_id):
        # Atomic single-use consume (mirrors consume_hitl): pending -> accepted,
        # True only for the winner. The in-memory store is single-threaded per
        # event loop, so the read-modify-write is already atomic.
        inv = self._invites.get((tenant_id, inv_id))
        if inv is None or inv.status != "pending":
            return False
        inv.status = "accepted"
        return True

    async def update_invitation(self, inv):
        # Narrow writer (mirrors the PG UPDATE): only status is ever written
        # back; a missing row is a no-op, never an insert.
        existing = self._invites.get((inv.tenant_id, inv.id))
        if existing is not None:
            existing.status = inv.status

    async def set_password_credential(self, tenant_id, user_id, password_hash):
        self._password_creds[(tenant_id, user_id)] = password_hash

    async def get_password_credential(self, tenant_id, user_id):
        return self._password_creds.get((tenant_id, user_id))
