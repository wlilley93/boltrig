"""``MailerSendPasswordResetNotifier`` provides bounded MailerSend delivery.

Only this adapter sees the plaintext reset bearer.  It posts to MailerSend's
fixed HTTPS origin, never follows redirects or environment proxy settings, and
returns a boolean so the recovery route can invalidate an undelivered token.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .password_reset import PasswordResetNotice


_API_ORIGIN = "https://api.mailersend.com"
_EMAIL_PATH = "/v1/email"
_QUOTA_PATH = "/v1/api-quota"
_TOTAL_TIMEOUT_SECONDS = 5.0
_PROBE_BODY_LIMIT = 16 * 1024
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
)


def _mailbox(value: str, *, field_name: str) -> str:
    result = value.strip()
    if not 3 <= len(result) <= 320 or _EMAIL.fullmatch(result) is None:
        raise ValueError(f"{field_name} must be one bounded ASCII email address")
    return result


def _public_origin(value: str) -> str:
    if len(value) > 2048:
        raise ValueError("password-reset public origin is too long")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.port not in (None, 443)
    ):
        raise ValueError("password-reset public origin must be one canonical HTTPS origin")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    return f"https://{host}"


@dataclass(frozen=True)
class MailerSendPasswordResetConfig:
    api_key: str = field(repr=False)
    from_email: str
    public_origin: str
    from_name: str = "Boltrig"

    def __post_init__(self) -> None:
        key = self.api_key.strip()
        if not 24 <= len(key) <= 4096 or any(char.isspace() for char in key):
            raise ValueError("MailerSend API key is malformed")
        name = self.from_name.strip()
        if not 1 <= len(name) <= 80 or any(ord(char) < 32 for char in name):
            raise ValueError("password-reset sender name is malformed")
        object.__setattr__(self, "api_key", key)
        object.__setattr__(self, "from_email", _mailbox(self.from_email, field_name="sender"))
        object.__setattr__(self, "public_origin", _public_origin(self.public_origin))
        object.__setattr__(self, "from_name", name)


class MailerSendPasswordResetNotifier:
    """Send one reset notice and expose a read-only token/quota probe."""

    def __init__(
        self,
        config: MailerSendPasswordResetConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_API_ORIGIN,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Boltrig-password-recovery/1",
            },
            timeout=httpx.Timeout(_TOTAL_TIMEOUT_SECONDS, connect=2.0),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        )

    async def __call__(self, notice: PasswordResetNotice) -> bool:
        try:
            recipient = _mailbox(notice.email, field_name="recipient")
            reset_url = (
                f"{self._config.public_origin}/#/reset-password?token="
                f"{quote(notice.token, safe='')}"
            )
            payload = {
                "from": {
                    "email": self._config.from_email,
                    "name": self._config.from_name,
                },
                "to": [{"email": recipient}],
                "subject": "Reset your Boltrig password",
                "text": (
                    "A password reset was requested for your Boltrig account.\n\n"
                    f"Open this one-time link within 30 minutes:\n{reset_url}\n\n"
                    "If you did not request this, you can ignore this message."
                ),
                "settings": {
                    "track_clicks": False,
                    "track_opens": False,
                    "track_content": False,
                },
                "tags": ["password-reset"],
            }
            async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
                async with self._client() as client:
                    async with client.stream("POST", _EMAIL_PATH, json=payload) as response:
                        message_id = response.headers.get("x-message-id", "")
                        paused = response.headers.get("x-send-paused", "").lower() == "true"
                        return (
                            response.status_code == 202
                            and not paused
                            and 1 <= len(message_id) <= 256
                            and message_id.isascii()
                            and message_id.isprintable()
                        )
        except Exception:
            # Provider exceptions can contain request material.  The caller records
            # only the bounded accepted/not-sent outcome.
            return False

    async def readiness_probe(self) -> bool:
        """Validate the configured token and usable quota without sending mail."""

        try:
            async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
                async with self._client() as client:
                    async with client.stream("GET", _QUOTA_PATH) as response:
                        if response.status_code != 200:
                            return False
                        body = await _bounded_json(response)
            quota = body.get("quota")
            remaining = body.get("remaining")
            return (
                isinstance(quota, int)
                and not isinstance(quota, bool)
                and quota > 0
                and isinstance(remaining, int)
                and not isinstance(remaining, bool)
                and remaining > 0
            )
        except Exception:
            return False


async def _bounded_json(response: httpx.Response) -> dict[str, Any]:
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding not in ("", "identity"):
        raise ValueError("compressed readiness response refused")
    if response.is_stream_consumed:
        raw = response.content
        if len(raw) > _PROBE_BODY_LIMIT:
            raise ValueError("readiness response too large")
    else:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_raw():
            total += len(chunk)
            if total > _PROBE_BODY_LIMIT:
                raise ValueError("readiness response too large")
            chunks.append(chunk)
        raw = b"".join(chunks)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("readiness response must be an object")
    return value


__all__ = [
    "MailerSendPasswordResetConfig",
    "MailerSendPasswordResetNotifier",
]
