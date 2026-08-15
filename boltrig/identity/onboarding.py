"""Versioned first-run onboarding state for user accounts.

Only the current completion version unlocks the private Worker workspace.  A
missing marker is therefore unfinished rather than a legacy bypass: the client
keeps chat unavailable until onboarding has been completed and persisted.
"""

from __future__ import annotations

import logging

from boltrig.models import UserSetting


ONBOARDING_SETTING_KEY = "setup.onboarding_version"
ONBOARDING_VERSION = 1


logger = logging.getLogger(__name__)


async def seed_user_onboarding(store, tenant_id: str, user_id: str) -> bool:
    """Mark a new user for setup explicitly."""

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
        # Account creation remains independent from presentation-state storage,
        # but a missing marker is deliberately fail-closed in Worker: chat is not
        # mounted until setup state can be read and completed.
        logger.warning("new-user onboarding marker could not be stored")
        return False
    return True
