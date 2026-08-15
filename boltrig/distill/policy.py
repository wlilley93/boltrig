"""Organisation-owned consent for automated overnight distillation."""

from __future__ import annotations

from typing import Any

OVERNIGHT_ENABLED_SETTING = "behaviour.overnight.enabled"


async def overnight_enabled(store: Any, tenant_id: str) -> bool:
    """Fail toward off when the organisation or its setting is absent/corrupt."""

    organisation = await store.get_org(tenant_id)
    if organisation is None or not isinstance(organisation.settings, dict):
        return False
    return organisation.settings.get(OVERNIGHT_ENABLED_SETTING) is True
