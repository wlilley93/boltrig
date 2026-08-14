"""Versioned first-run onboarding state for newly created accounts.

The absence of this setting means "legacy account" rather than "unfinished".
That distinction keeps an upgrade from putting every existing user back through
setup while still making invite/initiate-created accounts deterministic.
"""

from __future__ import annotations

from boltrig.models import UserSetting


ONBOARDING_SETTING_KEY = "setup.onboarding_version"
ONBOARDING_VERSION = 1


async def require_user_onboarding(store, tenant_id: str, user_id: str) -> None:
    """Mark a newly created user as needing the current onboarding flow."""

    await store.upsert_user_setting(
        UserSetting(
            tenant_id=tenant_id,
            user_id=user_id,
            key=ONBOARDING_SETTING_KEY,
            value=0,
        )
    )
