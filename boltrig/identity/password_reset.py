"""Password-recovery secrets and the injected delivery boundary.

The reset token is a bearer credential: only its SHA-256 digest crosses the
store seam. The one plaintext copy is carried by ``PasswordResetNotice`` to the
application-composed notifier and is deliberately excluded from ``repr``.
"""

from __future__ import annotations

import hashlib
import inspect
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Protocol


RESET_TOKEN_TTL = timedelta(minutes=30)


def generate_password_reset_token() -> str:
    return f"boltrig_reset_{secrets.token_urlsafe(32)}"


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PasswordResetNotice:
    """The single delivery-only representation that may contain the secret."""

    email: str
    token: str = field(repr=False)
    expires_at: datetime


class PasswordResetNotifier(Protocol):
    def __call__(self, notice: PasswordResetNotice) -> bool | None | Awaitable[bool | None]: ...


async def deliver_password_reset(
    notifier: PasswordResetNotifier, notice: PasswordResetNotice
) -> bool:
    """Run a sync or async notifier and make an explicit ``False`` fail closed."""

    result = notifier(notice)
    if inspect.isawaitable(result):
        result = await result
    return result is not False
