"""The model-endpoint router guard (US-PRIV-01, SEC-12).

Sensitive-classified data may only reach a local (data_class == 'sensitive')
endpoint. The guard resolves the endpoint for a capability and, when the data is
sensitive, refuses any non-local endpoint: it raises ``SensitiveDataMisrouted``
and audits the attempt, so sensitive content never leaves the boundary on a
hosted model call. Standard data is unconstrained.

"Sensitive" is not trusted from the caller alone at this seam (SEC-13): the
kernel's deterministic PII scanner runs over the outbound text payload and a
detection forces the sensitive route, so unclassified PII reaches hosted
endpoints never. The scan CLASSIFIES, it never mutates - see
:func:`outbound_text_classifies_sensitive`.
"""

from __future__ import annotations

from typing import Any

from boltrig.kernel import pii
from boltrig.models import (
    ActionType,
    AuditEvent,
    ModelEndpoint,
    ModelEndpointUnavailable,
    SensitiveDataMisrouted,
    utcnow,
)


def outbound_text_classifies_sensitive(text: str | None) -> bool:
    """True when the kernel's deterministic scanner flags ``text`` as PII-bearing.

    The model-gateway seam consults this so a payload nobody classified still
    routes sensitive (SEC-13): ``pii.redact`` finding anything, or an identity
    pattern via ``contains_identity``, forces the local route. Classification
    ONLY - the text is never rewritten here (redaction at egress is a separate,
    unapproved behaviour change); this answers "where may these bytes go", not
    "which bytes go out". Cheap by construction: one pass of the catalogued
    patterns over a string, nothing binary, nothing recursive. The patterns are
    conservative (a build number can read as an ipv4), so the failure mode of a
    false positive is a routed-local call, never a leak.
    """
    if not text:
        return False
    return pii.redact(text).has_pii or pii.contains_identity(text) is not None


def endpoint_id_for_modality(capability: Any, modality: str) -> str | None:
    """Choose an agent's governed endpoint for one input modality.

    A missing vision override deliberately falls back to the primary endpoint;
    control-plane validation guarantees that explicit single-model bindings are
    multimodal.
    """
    requested = str(modality).strip().lower()
    explicit = capability.endpoint_for(requested)
    if explicit:
        return explicit
    if requested == "vision":
        return capability.vision_model_endpoint or capability.model_endpoint
    return capability.model_endpoint


async def select_model_endpoint(
    store: Any,
    tenant_id: str,
    endpoint_id: str | None,
    *,
    sensitive: bool,
    modality: str | None = None,
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
    ep = await _active_endpoint(
        store, tenant_id, endpoint_id, audit=audit, actor=actor
    )
    requested_modality = str(modality or "").strip().lower()
    if ep is not None and requested_modality and not ep.supports(requested_modality):
        if audit is not None:
            await audit.write(
                AuditEvent(
                    tenant_id=tenant_id,
                    ts=utcnow(),
                    actor=actor,
                    action_type=ActionType.MODEL_CALL,
                    status="model_endpoint_modality_unavailable",
                    detail={
                        "endpoint": endpoint_id or "",
                        "modality": requested_modality,
                    },
                )
            )
        raise ModelEndpointUnavailable(
            f"model endpoint '{endpoint_id}' does not advertise "
            f"{requested_modality} modality"
        )
    if not sensitive:
        return ep
    if ep is not None and ep.data_class == "sensitive":
        return ep
    if sensitive_endpoint_id:
        local = await _active_endpoint(
            store,
            tenant_id,
            sensitive_endpoint_id,
            audit=audit,
            actor=actor,
        )
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


async def _active_endpoint(
    store: Any,
    tenant_id: str,
    endpoint_id: str | None,
    *,
    audit: Any | None,
    actor: str,
) -> ModelEndpoint | None:
    """Resolve one explicit reference without traversing its fallback.

    A missing or retired named row is configuration failure, not permission to
    drop to an environment model or follow a stale fallback reference.
    """
    if not endpoint_id:
        return None
    endpoint = await store.get_model_endpoint(tenant_id, endpoint_id)
    if endpoint is not None and endpoint.is_active:
        return endpoint
    if audit is not None:
        await audit.write(
            AuditEvent(
                tenant_id=tenant_id,
                ts=utcnow(),
                actor=actor,
                action_type=ActionType.MODEL_CALL,
                status="model_endpoint_unavailable",
                detail={
                    "endpoint": endpoint_id,
                    "endpoint_status": (
                        "retired" if endpoint is not None else "missing"
                    ),
                },
            )
        )
    raise ModelEndpointUnavailable(
        f"model endpoint '{endpoint_id}' is "
        f"{'retired' if endpoint is not None else 'missing'}"
    )
