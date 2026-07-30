"""Best-effort process-birth evidence publication."""

from __future__ import annotations

import logging
from typing import Any

from boltrig.kernel import Kernel

log = logging.getLogger("boltrig.bootstrap")


async def publish_birth_profile_startup(
    kernel: Kernel,
    *,
    process_kind: str,
    manifest: Any,
    addons_snapshot: Any,
    codex_config: dict[str, object] | None,
    sensitive_endpoint_id: str | None,
    default_tenant: str,
) -> bool:
    """Publish bounded startup evidence without turning it into liveness."""

    from boltrig.config.birth_profile import record_birth_profile_startup

    tenant_id = manifest.tenant_id if manifest is not None else default_tenant
    try:
        await record_birth_profile_startup(
            kernel.store,
            tenant_id=tenant_id,
            process_kind=process_kind,
            manifest=manifest,
            addons=addons_snapshot,
            codex_config=codex_config,
            sensitive_endpoint_id=sensitive_endpoint_id,
        )
    except Exception:
        log.warning(
            "birth-profile startup receipt unavailable (process=%s)",
            process_kind,
            exc_info=True,
        )
        return False
    return True


__all__ = ["publish_birth_profile_startup"]
