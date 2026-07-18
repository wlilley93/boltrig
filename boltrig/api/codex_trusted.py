"""Composition-root factory for the trusted read-only Codex runtime.

This is the trusted read-only Codex composition ([2026] VJS-CC-VJS 2). The heavy
provider (``TrustedProxyCodexPhaseCellProvider``) imports the fleet
``infrastructure`` layer and ``httpx``, which the architecture gate
(``scripts/check_architecture.py``) forbids ``boltrig/fleet/*`` from reaching
outward. So the provider is assembled HERE, at the ``boltrig/api/`` composition
boundary, and the resulting ``codex_config`` dict is INJECTED down into
``RuntimeResolver`` (mirroring how ``build_codex_execution_stack`` sits at this
same boundary for the same reason).

Off by default = a total no-op: with ``BOLTRIG_CODEX_TRUSTED`` unset (or the
binary / stack root unconfigured) ``build_trusted_codex_config`` returns ``None``,
``RuntimeResolver._codex_config`` returns ``None``, and ``build_runtime`` degrades
the ``codex`` runtime to ``ScriptRuntime`` exactly as before. The dev/prod wall is
re-asserted again at ``acquire`` and inside ``build_trusted_codex_runtime`` (both
call ``require_codex_trusted_posture``); returning a live provider only when
``codex_trusted`` is set is the first of those gates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boltrig.config.settings import Settings


def build_trusted_codex_config(
    settings: Settings, *, model_id: str, gateway_base_url: str
) -> dict[str, Any] | None:
    """Assemble the trusted read-only Codex provider config, or ``None`` (no-op).

    Returns ``None`` unless ``codex_trusted`` is set AND both the pinned binary and
    the stack root are configured; a missing value is OFF and constructs nothing.
    When all three are present it builds the provider and returns the dict shape
    ``build_trusted_codex_runtime`` consumes: ``{"trusted": True, "provider": ...,
    "stack_root": Path}``.
    """
    if not (settings.codex_trusted and settings.codex_binary and settings.codex_stack_root):
        return None

    # Lazy imports so the flag-off path never pulls in the infrastructure layer or
    # httpx (mirrors build_codex_execution_stack's lazy imports). Only reached on.
    import httpx

    from boltrig.fleet.application.model_proxy_grants import (
        PhaseScopedModelProxyGrantBroker,
    )
    from boltrig.fleet.infrastructure.codex_cell_provisioning import (
        ProvisioningCodexPhaseAdmissionSource,
    )
    from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
    from boltrig.fleet.infrastructure.codex_runtime_preflight import (
        QuarantinedCodexPreflightProbe,
    )
    from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
        TrustedProxyCodexPhaseCellProvider,
    )
    from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
        MemoryModelProxyGrantStore,
    )

    stack_root = Path(settings.codex_stack_root)
    source = ProvisioningCodexPhaseAdmissionSource(stack_root=stack_root, model_id=model_id)
    # D2: the supervisor is constructed with auth=None so the child environment
    # never carries the upstream key; the provider enforces supervisor._auth is None.
    supervisor = CodexCellSupervisor(binary=Path(settings.codex_binary), auth=None)
    probe = QuarantinedCodexPreflightProbe()
    grant_store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(grant_store)
    provider = TrustedProxyCodexPhaseCellProvider(
        source=source,
        supervisor=supervisor,
        probe=probe,
        broker=broker,
        grant_store=grant_store,
        upstream_base_url=gateway_base_url,
        # Dev bifrost is unauth, so an empty key is acceptable; prefer the configured
        # value when present.
        upstream_key=settings.model_gateway_key or "",
        http_client=httpx.AsyncClient(),
    )
    return {"trusted": True, "provider": provider, "stack_root": stack_root}


__all__ = ["build_trusted_codex_config"]
