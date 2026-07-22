"""Registering an external MCP server as a governed adapter (US-MCP-03).

A consumed server registers INERT, pending the review gate (SEC-22), and its
bearer goes on the CREDENTIAL SEAM as a reference rather than onto the adapter
instance: the kernel then resolves it per call at dispatch and hands it to
``execute`` (SEC-04/05, K-20 - credentials resolve inside the kernel only). This
mirrors the manifest adapter-credential path in ``manifest.py``.
"""

from __future__ import annotations

import json
from typing import Any

from .control_operations import ensure_adapter_id_available, record_inert_adapter
from .control_safety import ControlConflict

__all__ = ["bind_mcp_credential", "build_mcp_consumer", "register_mcp_consumer"]


def build_mcp_consumer(params: dict[str, Any]) -> Any:
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter

    return McpConsumerAdapter(
        params["id"],
        url=params.get("url"),
        # The reviewed opt-in for an operator-vetted INTERNAL server (SEC-61
        # waiver); absent/anything-but-true reads as the guarded default.
        allow_internal=bool(params.get("allow_internal")),
    )


async def bind_mcp_credential(
    store: Any, credentials: Any, tenant_id: str, adapter_id: str, params: dict[str, Any]
) -> str | None:
    """Put an MCP server's bearer on the credential seam (refs only, SEC-04).

    ``credential_ref`` NAMES the secret (a secret-store key); the secret store
    holds the material. Raw secret material is refused outright: it would park a
    static token outside the kernel and, on the control-plane route, put a
    plaintext secret through an audited verb param.
    """
    from boltrig.config.manifest import CredentialRef

    for legacy in ("token", "credential"):
        if params.get(legacy):
            raise ControlConflict(
                f"'{legacy}' passes raw secret material; use 'credential_ref' "
                "(a secret-store key) so the kernel resolves it per call"
            )
    ref = params.get("credential_ref")
    if not ref:
        return None
    cred = CredentialRef(
        id=params.get("credential_id") or f"{adapter_id}-mcp-token",
        store=params.get("credential_store", "env"),
        ref=ref,
        kind=params.get("credential_kind", "api_key"),
    )
    await store.set_credential_ref(tenant_id, cred.id, cred.as_ref())
    credentials.bind_adapter_credential(tenant_id, adapter_id, cred.id)
    return cred.id


async def register_mcp_consumer(
    store: Any,
    loader: Any,
    tenant_id: str,
    params: dict[str, Any],
    *,
    actor: str,
    credentials: Any = None,
) -> Any:
    await ensure_adapter_id_available(store, loader, tenant_id, params["id"])
    consumer = build_mcp_consumer(params)
    # The row's spec_ref is what boot rehydration rebuilds the consumer FROM,
    # so it now persists the server url AND its reviewed egress posture as a
    # small JSON object (read back by control_rehydrate.consumer_spec, which
    # also reads the pre-flag plain-url rows). A registration without a url
    # can never be rehydrated.
    spec_ref = None
    if params.get("url"):
        spec_ref = json.dumps(
            {"url": params["url"], "allow_internal": bool(params.get("allow_internal"))}
        )
    await record_inert_adapter(
        store, tenant_id, consumer, created_by=actor, spec_ref=spec_ref
    )
    if credentials is not None:
        await bind_mcp_credential(store, credentials, tenant_id, consumer.id, params)
    if loader.peek(tenant_id, consumer.id) is not None:
        raise ControlConflict("adapter id became live during registration")
    loader.register(tenant_id, consumer)
    return consumer
