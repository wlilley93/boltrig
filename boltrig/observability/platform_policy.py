"""Compose authenticated platform-policy projections outside the route module."""

from __future__ import annotations

from typing import Any

from boltrig.observability.background_jobs import background_job_platform_fields
from boltrig.observability.codex_admission import codex_admission_projection
from boltrig.observability.identity_policy import identity_policy_projection
from boltrig.observability.langfuse_status import langfuse_delivery_projection
from boltrig.observability.memory_projection_delivery import (
    memory_projection_delivery_fields,
)
from boltrig.observability.network_policy import effective_network_policy


async def platform_policy_fields(
    kernel: Any,
    tenant_id: str,
    *,
    codex_execution: Any = None,
    codex_trusted_provider_configured: bool = False,
    spawner: Any = None,
    identity_policy: Any = None,
) -> dict[str, Any]:
    return {
        **(await background_job_platform_fields(kernel.store, tenant_id)),
        **(await memory_projection_delivery_fields(kernel, tenant_id)),
        "network_policy": effective_network_policy(kernel, tenant_id),
        "codex_admission": codex_admission_projection(
            codex_execution,
            trusted_provider_configured=(
                codex_trusted_provider_configured is True
            ),
        ),
        "langfuse_delivery": langfuse_delivery_projection(spawner),
        "identity_policy": identity_policy_projection(identity_policy),
    }


__all__ = ["platform_policy_fields"]
