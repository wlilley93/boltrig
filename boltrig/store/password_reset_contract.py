"""Password-recovery persistence contract (SEC-AUTH-RECOVERY-01)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models.access import PasswordResetResult, PasswordResetToken


class PasswordResetStoreContract(Protocol):
    async def replace_password_reset_token(self, token: PasswordResetToken) -> bool:
        """Replace a user's active token, only for a recoverable active account."""
        ...

    async def invalidate_password_reset_token(self, tenant_id: str, token_hash: str) -> bool:
        """Delete the exact token after a failed delivery."""
        ...

    async def reset_password_with_token(
        self,
        tenant_id: str,
        token_hash: str,
        password_hash: str,
        now: datetime,
    ) -> PasswordResetResult | None:
        """Atomically consume, rotate password, clear clamp, and revoke sessions."""
        ...

    async def revoke_user_sessions(
        self, tenant_id: str, user_id: str, *, keep_token_hash: str | None = None
    ) -> int:
        """Revoke the identity's other sessions after a self-service rotation."""
        ...
