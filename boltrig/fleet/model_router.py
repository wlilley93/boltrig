"""The model-endpoint router guard (US-PRIV-01, SEC-12).

Sensitive-classified data may only reach a local (data_class == 'sensitive')
endpoint. The guard resolves the endpoint for a capability and, when the data is
sensitive, refuses any non-local endpoint: it raises ``SensitiveDataMisrouted``
and audits the attempt, so sensitive content never leaves the boundary on a
hosted model call. Standard data is unconstrained.
"""

from __future__ import annotations

from typing import Any

from boltrig.models import (
    ActionType,
    AuditEvent,
    ModelEndpoint,
    SensitiveDataMisrouted,
    utcnow,
)


async def select_model_endpoint(
    store: Any,
    tenant_id: str,
    endpoint_id: str | None,
    *,
    sensitive: bool,
    sensitive_endpoint_id: str | None = None,
    audit: Any | None = None,
    actor: str = "model-router",
) -> ModelEndpoint | None:
    """Resolve the endpoint to use, enforcing sensitive->local routing (SEC-12).

    Returns the endpoint (or None when the capability needs none) for standard
    data. For sensitive data it returns a sensitive endpoint (the capability's
    own if local, else the configured ``sensitive_endpoint_id``) or raises
    ``SensitiveDataMisrouted`` after auditing the misroute.
    """
    ep = await store.get_model_endpoint(tenant_id, endpoint_id) if endpoint_id else None
    if not sensitive:
        return ep
    if ep is not None and ep.data_class == "sensitive":
        return ep
    if sensitive_endpoint_id:
        local = await store.get_model_endpoint(tenant_id, sensitive_endpoint_id)
        if local is not None and local.data_class == "sensitive":
            return local
    if audit is not None:
        await audit.write(
            AuditEvent(
                tenant_id=tenant_id,
                ts=utcnow(),
                actor=actor,
                action_type=ActionType.MODEL_CALL,
                status="sensitive_data_misrouted",
                detail={
                    "endpoint": endpoint_id or "",
                    "data_class": ep.data_class if ep else "unknown",
                },
            )
        )
    raise SensitiveDataMisrouted(
        f"sensitive data may not route to non-local endpoint '{endpoint_id}'"
    )
