"""User-auth store domain (arc-1 structural partial): TOTP enrolment, recovery
codes, two-factor challenges, per-user settings and sessions - extracted
verbatim from ``store/postgres.py`` + ``store/memory.py``. PG host:
``self._pool``; Mem host: ``self._totp``/``_recovery``/``_tfa_challenges``/
``_settings``/``_sessions``. Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import TwoFactorChallenge, UserSession, UserSetting, UserTotp

from .rls_pool import _apply_guc
from .rows import _session, _setting, _tfa_challenge, _user_totp
from .tenant_scope import pool_assumes_app_role


class UserAuthStorePG:
    """TOTP/settings/session methods for ``PostgresStore``."""

    async def set_user_totp(self, totp: UserTotp) -> None:
        await self._pool.execute(
            """INSERT INTO user_totp (tenant_id, user_id, secret_ref, enrolled, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5, now())
               ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                 secret_ref=EXCLUDED.secret_ref, enrolled=EXCLUDED.enrolled, updated_at=now()""",
            totp.tenant_id, totp.user_id, totp.secret_ref, totp.enrolled, totp.created_at,
        )

    async def get_user_totp(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_totp WHERE tenant_id=$1 AND user_id=$2", tenant_id, user_id
        )
        return _user_totp(row)

    async def delete_user_totp(self, tenant_id, user_id) -> None:
        await self._pool.execute(
            "DELETE FROM user_totp WHERE tenant_id=$1 AND user_id=$2", tenant_id, user_id
        )

    async def set_recovery_codes(self, tenant_id, user_id, code_hashes) -> None:
        # Replace the whole set atomically: clear then insert the fresh hashes.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
                await conn.execute(
                    "DELETE FROM user_recovery_codes WHERE tenant_id=$1 AND user_id=$2",
                    tenant_id, user_id,
                )
                for h in code_hashes:
                    await conn.execute(
                        """INSERT INTO user_recovery_codes (tenant_id, user_id, code_hash)
                           VALUES ($1,$2,$3)
                           ON CONFLICT (tenant_id, user_id, code_hash) DO NOTHING""",
                        tenant_id, user_id, h,
                    )

    async def consume_recovery_code(self, tenant_id, user_id, code_hash) -> bool:
        # Atomic single-use CAS: flip an unused hash to used, True only for the
        # winner (RETURNING makes it observable across concurrent redeemers).
        row = await self._pool.fetchrow(
            """UPDATE user_recovery_codes SET used_at=now()
               WHERE tenant_id=$1 AND user_id=$2 AND code_hash=$3 AND used_at IS NULL
               RETURNING code_hash""",
            tenant_id, user_id, code_hash,
        )
        return row is not None

    async def count_active_recovery_codes(self, tenant_id, user_id) -> int:
        row = await self._pool.fetchrow(
            """SELECT count(*) AS n FROM user_recovery_codes
               WHERE tenant_id=$1 AND user_id=$2 AND used_at IS NULL""",
            tenant_id, user_id,
        )
        return int(row["n"]) if row is not None else 0

    async def clear_recovery_codes(self, tenant_id, user_id) -> None:
        await self._pool.execute(
            "DELETE FROM user_recovery_codes WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )

    async def add_two_factor_challenge(self, challenge: TwoFactorChallenge) -> None:
        await self._pool.execute(
            """INSERT INTO two_factor_challenges (tenant_id, token_hash, user_id, expires_at, created_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (tenant_id, token_hash) DO NOTHING""",
            challenge.tenant_id, challenge.token_hash, challenge.user_id,
            challenge.expires_at, challenge.created_at,
        )

    async def get_two_factor_challenge(self, tenant_id, token_hash):
        row = await self._pool.fetchrow(
            "SELECT * FROM two_factor_challenges WHERE tenant_id=$1 AND token_hash=$2",
            tenant_id, token_hash,
        )
        return _tfa_challenge(row)

    async def consume_two_factor_challenge(self, tenant_id, token_hash) -> bool:
        # Atomic single-use: delete-if-present, True only for the winner.
        row = await self._pool.fetchrow(
            """DELETE FROM two_factor_challenges
               WHERE tenant_id=$1 AND token_hash=$2 RETURNING token_hash""",
            tenant_id, token_hash,
        )
        return row is not None

    async def upsert_user_setting(self, s: UserSetting):
        await self._pool.execute(
            """INSERT INTO user_settings (tenant_id, user_id, key, value, updated_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (tenant_id, user_id, key) DO UPDATE SET
                 value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
            s.tenant_id, s.user_id, s.key, s.value, s.updated_at,
        )

    async def list_user_settings(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            "SELECT * FROM user_settings WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return [_setting(r) for r in rows]

    async def add_session(self, s: UserSession):
        await self._pool.execute(
            """INSERT INTO user_sessions (id, tenant_id, user_id, client, created_at,
                                          last_seen_at, revoked, token_hash, expires_at,
                                          csrf_token, active_workspace_id, active_org_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            s.id, s.tenant_id, s.user_id, s.client, s.created_at, s.last_seen_at, s.revoked,
            s.token_hash, s.expires_at, s.csrf_token, s.active_workspace_id, s.active_org_id,
        )

    async def list_sessions(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM user_sessions WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC""",
            tenant_id, user_id,
        )
        return [_session(r) for r in rows]

    async def get_session(self, tenant_id, session_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_sessions WHERE tenant_id=$1 AND id=$2", tenant_id, session_id
        )
        return _session(row)

    async def get_session_by_token_hash(self, tenant_id, token_hash):
        # First-party session ([2026] VJS-COUNTY 7, D2): tenant-scoped (RLS-safe)
        # lookup of a session by its cookie-secret hash.
        row = await self._pool.fetchrow(
            "SELECT * FROM user_sessions WHERE tenant_id=$1 AND token_hash=$2",
            tenant_id, token_hash,
        )
        return _session(row)

    async def update_session(self, s: UserSession):
        # Carries the rotating secret hash / bounded expiry / CSRF token too (D6),
        # so a refresh (rotate_session) and a touch both persist through one path.
        await self._pool.execute(
            """UPDATE user_sessions SET client=$3, last_seen_at=$4, revoked=$5,
                                        token_hash=$6, expires_at=$7, csrf_token=$8,
                                        active_workspace_id=$9, active_org_id=$10
               WHERE tenant_id=$1 AND id=$2""",
            s.tenant_id, s.id, s.client, s.last_seen_at, s.revoked,
            s.token_hash, s.expires_at, s.csrf_token, s.active_workspace_id, s.active_org_id,
        )


class UserAuthStoreMem:
    """TOTP/settings/session methods for ``InMemoryStore``."""

    async def set_user_totp(self, totp: UserTotp) -> None:
        self._totp[(totp.tenant_id, totp.user_id)] = totp

    async def get_user_totp(self, tenant_id, user_id):
        return self._totp.get((tenant_id, user_id))

    async def delete_user_totp(self, tenant_id, user_id) -> None:
        self._totp.pop((tenant_id, user_id), None)

    async def set_recovery_codes(self, tenant_id, user_id, code_hashes) -> None:
        # Replace the whole set; each hash starts unused (False).
        self._recovery[(tenant_id, user_id)] = {h: False for h in code_hashes}

    async def consume_recovery_code(self, tenant_id, user_id, code_hash) -> bool:
        # Atomic single-use (mirrors consume_invitation): only an unused matching
        # hash flips to used (True) and returns True. A missing or already-used hash
        # returns False (fail-closed). The read-modify-write does not await, so it is
        # atomic on the single-threaded event loop.
        codes = self._recovery.get((tenant_id, user_id))
        if not codes or codes.get(code_hash) is not False:
            return False
        codes[code_hash] = True
        return True

    async def count_active_recovery_codes(self, tenant_id, user_id) -> int:
        codes = self._recovery.get((tenant_id, user_id)) or {}
        return sum(1 for used in codes.values() if not used)

    async def clear_recovery_codes(self, tenant_id, user_id) -> None:
        self._recovery.pop((tenant_id, user_id), None)

    async def add_two_factor_challenge(self, challenge: TwoFactorChallenge) -> None:
        self._tfa_challenges[(challenge.tenant_id, challenge.token_hash)] = challenge

    async def get_two_factor_challenge(self, tenant_id, token_hash):
        return self._tfa_challenges.get((tenant_id, token_hash))

    async def consume_two_factor_challenge(self, tenant_id, token_hash) -> bool:
        # Atomic single-use: delete-if-present, True only for the winner (the pop is
        # a single non-awaiting op, atomic on the single-threaded event loop).
        return self._tfa_challenges.pop((tenant_id, token_hash), None) is not None

    async def upsert_user_setting(self, setting):
        self._settings[(setting.tenant_id, setting.user_id, setting.key)] = setting

    async def list_user_settings(self, tenant_id, user_id):
        return [s for (t, u, _), s in self._settings.items() if t == tenant_id and u == user_id]

    async def add_session(self, session):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._sessions.setdefault((session.tenant_id, session.id), session)

    async def list_sessions(self, tenant_id, user_id):
        return [
            s for (t, _), s in self._sessions.items() if t == tenant_id and s.user_id == user_id
        ]

    async def get_session(self, tenant_id, session_id):
        return self._sessions.get((tenant_id, session_id))

    async def get_session_by_token_hash(self, tenant_id, token_hash):
        # First-party session ([2026] VJS-COUNTY 7, D2): match a session by its
        # cookie-secret hash, constant-time, tenant-scoped.
        import hmac as _hmac

        for (t, _), s in self._sessions.items():
            if t == tenant_id and s.token_hash and _hmac.compare_digest(s.token_hash, token_hash):
                return s
        return None

    async def update_session(self, session):
        self._sessions[(session.tenant_id, session.id)] = session
