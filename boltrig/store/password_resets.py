"""In-memory and PostgreSQL password-recovery store implementations."""

from __future__ import annotations

import hmac
from dataclasses import replace
from datetime import datetime

from boltrig.models.access import PasswordResetResult, PasswordResetToken


class PasswordResetStoreMem:
    def _reset_tokens(self) -> dict[tuple[str, str], PasswordResetToken]:
        tokens = getattr(self, "_password_reset_tokens", None)
        if tokens is None:
            tokens = {}
            self._password_reset_tokens = tokens
        return tokens

    async def replace_password_reset_token(self, token: PasswordResetToken) -> bool:
        user = self._users.get((token.tenant_id, token.user_id))
        if (
            user is None
            or user.status != "active"
            or (token.tenant_id, token.user_id) not in self._password_creds
        ):
            return False
        self._reset_tokens()[(token.tenant_id, token.user_id)] = token
        return True

    async def invalidate_password_reset_token(self, tenant_id: str, token_hash: str) -> bool:
        tokens = self._reset_tokens()
        for key, token in tuple(tokens.items()):
            if key[0] == tenant_id and hmac.compare_digest(token.token_hash, token_hash):
                del tokens[key]
                return True
        return False

    async def reset_password_with_token(
        self,
        tenant_id: str,
        token_hash: str,
        password_hash: str,
        now: datetime,
    ) -> PasswordResetResult | None:
        # No await occurs between the claim and all dependent writes, so this is
        # one event-loop-atomic transition and only one concurrent redeemer wins.
        found = None
        tokens = self._reset_tokens()
        for key, token in tokens.items():
            if key[0] == tenant_id and hmac.compare_digest(token.token_hash, token_hash):
                found = (key, token)
                break
        if found is None:
            return None
        key, token = found
        user = self._users.get((tenant_id, token.user_id))
        if (
            token.consumed_at is not None
            or token.expires_at <= now
            or user is None
            or user.status != "active"
            or (tenant_id, token.user_id) not in self._password_creds
        ):
            return None

        tokens[key] = replace(token, consumed_at=now)
        self._password_creds[(tenant_id, token.user_id)] = password_hash
        if user.must_change_password:
            self._users[(tenant_id, token.user_id)] = replace(user, must_change_password=False)
        revoked = 0
        for session in self._sessions.values():
            if (
                session.tenant_id == tenant_id
                and session.user_id == token.user_id
                and not session.revoked
            ):
                session.revoked = True
                revoked += 1
        for challenge_key, challenge in tuple(self._tfa_challenges.items()):
            if challenge.tenant_id == tenant_id and challenge.user_id == token.user_id:
                del self._tfa_challenges[challenge_key]
        return PasswordResetResult(user_id=token.user_id, revoked_sessions=revoked)

    async def revoke_user_sessions(
        self, tenant_id: str, user_id: str, *, keep_token_hash: str | None = None
    ) -> int:
        """Revoke the identity's OTHER sessions (self-service password rotation).

        The reset path revokes everything inside its CTE because its caller is
        unauthenticated; the rotate path is authenticated, so the CALLER's
        session survives via ``keep_token_hash`` while every other session -
        including an attacker's from a phished password - dies with the old
        credential."""
        revoked = 0
        for session in self._sessions.values():
            if (
                session.tenant_id == tenant_id
                and session.user_id == user_id
                and not session.revoked
                and (keep_token_hash is None
                     or not hmac.compare_digest(session.token_hash, keep_token_hash))
            ):
                session.revoked = True
                revoked += 1
        return revoked


class PasswordResetStorePG:
    async def replace_password_reset_token(self, token: PasswordResetToken) -> bool:
        row = await self._pool.fetchrow(
            """INSERT INTO password_reset_tokens
                 (tenant_id, user_id, token_hash, expires_at, created_at, consumed_at)
               SELECT $1,$2,$3,$4,$5,$6
               WHERE EXISTS (
                 SELECT 1 FROM users u
                 JOIN user_credentials c
                   ON c.tenant_id=u.tenant_id AND c.user_id=u.id
                 WHERE u.tenant_id=$1 AND u.id=$2 AND u.status='active'
               )
               ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                 token_hash=EXCLUDED.token_hash,
                 expires_at=EXCLUDED.expires_at,
                 created_at=EXCLUDED.created_at,
                 consumed_at=NULL
               RETURNING user_id""",
            token.tenant_id,
            token.user_id,
            token.token_hash,
            token.expires_at,
            token.created_at,
            token.consumed_at,
        )
        return row is not None

    async def invalidate_password_reset_token(self, tenant_id: str, token_hash: str) -> bool:
        row = await self._pool.fetchrow(
            """DELETE FROM password_reset_tokens
               WHERE tenant_id=$1 AND token_hash=$2 RETURNING user_id""",
            tenant_id,
            token_hash,
        )
        return row is not None

    async def revoke_user_sessions(
        self, tenant_id: str, user_id: str, *, keep_token_hash: str | None = None
    ) -> int:
        rows = await self._pool.fetch(
            """UPDATE user_sessions s
                  SET revoked=true
                 WHERE s.tenant_id=$1 AND s.user_id=$2 AND NOT s.revoked
                   AND ($3::text IS NULL OR s.token_hash IS DISTINCT FROM $3)
               RETURNING s.id""",
            tenant_id,
            user_id,
            keep_token_hash,
        )
        return len(rows)

    async def reset_password_with_token(
        self,
        tenant_id: str,
        token_hash: str,
        password_hash: str,
        now: datetime,
    ) -> PasswordResetResult | None:
        # One data-modifying CTE is one database transaction even through the
        # RLS-aware pool facade: token claim, credential rotation, clamp clear,
        # session revocation, and stale 2FA challenge deletion cannot split.
        row = await self._pool.fetchrow(
            """WITH claimed AS (
                 UPDATE password_reset_tokens pr
                    SET consumed_at=$4
                  WHERE pr.tenant_id=$1
                    AND pr.token_hash=$2
                    AND pr.consumed_at IS NULL
                    AND pr.expires_at > $4
                    AND EXISTS (
                      SELECT 1 FROM users u
                      WHERE u.tenant_id=pr.tenant_id
                        AND u.id=pr.user_id
                        AND u.status='active'
                    )
                  RETURNING pr.user_id
               ),
               credential AS (
                 UPDATE user_credentials c
                    SET password_hash=$3, updated_at=$4
                   FROM claimed
                  WHERE c.tenant_id=$1 AND c.user_id=claimed.user_id
                  RETURNING c.user_id
               ),
               cleared_flag AS (
                 UPDATE users u
                    SET must_change_password=false
                   FROM credential
                  WHERE u.tenant_id=$1 AND u.id=credential.user_id
                  RETURNING u.id
               ),
               revoked AS (
                 UPDATE user_sessions s
                    SET revoked=true
                   FROM credential
                  WHERE s.tenant_id=$1
                    AND s.user_id=credential.user_id
                    AND NOT s.revoked
                  RETURNING s.id
               ),
               cleared_challenges AS (
                 DELETE FROM two_factor_challenges c
                  USING credential
                  WHERE c.tenant_id=$1 AND c.user_id=credential.user_id
                  RETURNING c.token_hash
               )
               SELECT credential.user_id,
                      (SELECT count(*) FROM revoked) AS revoked_sessions
                 FROM credential, cleared_flag""",
            tenant_id,
            token_hash,
            password_hash,
            now,
        )
        if row is None:
            return None
        return PasswordResetResult(
            user_id=row["user_id"], revoked_sessions=int(row["revoked_sessions"])
        )
