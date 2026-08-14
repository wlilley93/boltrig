"""Compose the deployment-owned password-reset delivery adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from boltrig.identity.mailersend_password_reset import (
    MailerSendPasswordResetConfig,
    MailerSendPasswordResetNotifier,
)


_PROVIDER = "BOLTRIG_PASSWORD_RESET_PROVIDER"
_KEY = "BOLTRIG_MAILERSEND_API_KEY"
_FROM_EMAIL = "BOLTRIG_PASSWORD_RESET_FROM_EMAIL"
_FROM_NAME = "BOLTRIG_PASSWORD_RESET_FROM_NAME"
_PUBLIC_ORIGIN = "BOLTRIG_PASSWORD_RESET_PUBLIC_ORIGIN"
_CONFIG_FIELDS = (_KEY, _FROM_EMAIL, _FROM_NAME, _PUBLIC_ORIGIN)


def compose_password_reset_delivery(
    env: Mapping[str, str] | None = None,
    *,
    transport: Any = None,
) -> tuple[Any, Any]:
    """Return notifier+probe or fail startup on partial/unknown configuration."""

    source = os.environ if env is None else env
    provider = str(source.get(_PROVIDER) or "").strip().lower()
    configured = any(str(source.get(name) or "").strip() for name in _CONFIG_FIELDS)
    if not provider:
        if configured:
            raise RuntimeError("password-reset delivery is partially configured")
        return None, None
    if provider != "mailersend":
        raise RuntimeError("unsupported password-reset delivery provider")

    missing = [
        name
        for name in (_KEY, _FROM_EMAIL, _PUBLIC_ORIGIN)
        if not str(source.get(name) or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "password-reset delivery is missing required setting(s): " + ", ".join(missing)
        )
    config = MailerSendPasswordResetConfig(
        api_key=str(source[_KEY]),
        from_email=str(source[_FROM_EMAIL]),
        from_name=str(source.get(_FROM_NAME) or "Boltrig"),
        public_origin=str(source[_PUBLIC_ORIGIN]),
    )
    notifier = MailerSendPasswordResetNotifier(config, transport=transport)
    return notifier, notifier.readiness_probe


__all__ = ["compose_password_reset_delivery"]
