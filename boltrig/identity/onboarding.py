"""Versioned first-run onboarding state for newly created accounts.

The absence of this setting means "legacy account" rather than "unfinished".
That distinction keeps an upgrade from putting every existing user back through
setup while still making invite/initiate-created accounts deterministic.
"""

from __future__ import annotations

import logging

from boltrig.models import UserSetting


ONBOARDING_SETTING_KEY = "setup.onboarding_version"
ONBOARDING_VERSION = 1


logger = logging.getLogger(__name__)


async def seed_user_onboarding(store, tenant_id: str, user_id: str) -> bool:
    """Mark a new user for setup without making an account depend on a UX flag."""

    try:
        await store.upsert_user_setting(
            UserSetting(
                tenant_id=tenant_id,
                user_id=user_id,
                key=ONBOARDING_SETTING_KEY,
                value=0,
            )
        )
    except Exception:
        # This marker is presentation state. An unavailable settings store must
        # not consume an invitation while preventing its new account from being
        # used; the missing marker safely means the flow is skipped.
        logger.warning("new-user onboarding marker could not be stored")
        return False
    return True
