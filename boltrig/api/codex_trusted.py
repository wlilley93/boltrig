"""Composition-root factory for the trusted Codex runtime.

This is the trusted Codex composition ([2026] VJS-CC-VJS 2; the two lawful
postures are defined in decision 0017). The heavy
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
the ``codex`` runtime to ``ScriptRuntime`` exactly as before. The posture wall is
re-asserted again at ``acquire`` and inside ``build_trusted_codex_runtime`` (both
call ``require_codex_trusted_posture``); returning a live provider only when
``codex_trusted`` is set is the first of those gates.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from boltrig.config.settings import Settings

if TYPE_CHECKING:
    import httpx

    from boltrig.fleet.infrastructure.cell_lane import CellLane


def _receipt_identity(
    settings: Settings, *, model_id: str, gateway_base_url: str
) -> str:
    """Opaque identity of non-secret provider composition inputs.

    Paths and the gateway URL influence drift detection but only this digest
    leaves the composition root.  The upstream key is deliberately excluded.
    """

    payload = {
        "schema": "trusted-codex-provider-v1",
        "trusted": bool(settings.codex_trusted),
        "binary": str(settings.codex_binary or ""),
        "stack_root": str(settings.codex_stack_root or ""),
        "model_id": model_id,
        "gateway_base_url": gateway_base_url,
        "auth_helper": os.environ.get("BOLTRIG_CODEX_AUTH_HELPER", ""),
        "cell_lane": bool(os.environ.get("BOLTRIG_CELL_SPAWNER_FD")),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "cp_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _build_cell_lane() -> CellLane | None:
    """The CellLane the enactment was missing ([2026] VJS-CC-VJS 7 J1), or None.

    When the entrypoint privilege-separated it handed this (deliberately dropped)
    API a live spawner socket. Its presence is how per-cell uids reach the PRODUCT
    rather than only the J9 harness: build a CellLane over it and the supervisor
    routes every spawn through the privileged spawner, under a distinct uid. Absent
    it (no capability, or single-tenant), this returns None and the supervisor
    keeps today's in-process spawn, byte-identical. The lane owns a DUP so the raw
    inherited fd stays valid for the per-cell mode check.
    """

    import os
    import socket

    from boltrig.fleet.infrastructure.cell_lane import CellLane
    from boltrig.fleet.infrastructure.cell_privilege import inherited_spawner_socket_fd
    from boltrig.fleet.infrastructure.cell_slots import (
        DECLARED_CELL_SLOTS,
        CellSlotAllocator,
    )

    spawner_fd = inherited_spawner_socket_fd(os.environ)
    if spawner_fd is None:
        return None
    spawner_socket = socket.socket(fileno=os.dup(spawner_fd))
    # Capacity matches the per-cell tmpfs slots declared in docker-compose; a test
    # holds slot_for_index in step with those mounts.
    return CellLane(spawner_socket, CellSlotAllocator(DECLARED_CELL_SLOTS))


def _trusted_config(
    settings: Settings,
    *,
    provider: Any,
    stack_root: Path,
    model_id: str,
    gateway_base_url: str,
) -> dict[str, Any]:
    return {
        "trusted": True,
        "provider": provider,
        "stack_root": stack_root,
        "model_id": model_id,
        "receipt_identity": _receipt_identity(
            settings,
            model_id=model_id,
            gateway_base_url=gateway_base_url,
        ),
    }


def _prove_the_host_can_enforce_the_cell_wall(binary: Path, stack_root: Path) -> None:
    """Prove the read-only sandbox ENGAGES here, before composing anything on it.

    The generated config says ``sandbox_mode = "read-only"`` and our own tests read
    that same line back, which is an assertion about our own bytes. What actually
    refuses a write is Landlock, a kernel LSM this host may not carry, and on a host
    without it the config line stays true while nothing stops a write.

    Proved at composition for the same reason ``assert_cell_isolation_boundary`` is:
    a host that cannot enforce the wall must not construct a live provider at all.
    Raises rather than warns, because a wall reported untested reads to every
    downstream caller exactly like a wall reported working.
    """

    from boltrig.fleet.infrastructure.codex_sandbox_engagement import (
        prove_sandbox_engagement,
    )

    prove_sandbox_engagement(codex_binary=binary, probe_root=stack_root)


def _upstream_client() -> "httpx.AsyncClient":
    """The model-proxy's upstream client, sized for a self-hosted model.

    httpx's DEFAULT timeout is 5s on every leg, and a self-hosted model's
    prompt prefill sits silent longer than that between stream chunks -
    measured 2026-08-20: every live turn died mid-stream at ~5.5s while the
    gateway completed the same call in 13s. The read leg matches the cell's
    own stream idle policy (300s); connect stays tight.
    """
    import httpx

    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)
    )


def build_trusted_codex_config(
    settings: Settings, *, model_id: str, gateway_base_url: str
) -> dict[str, Any] | None:
    """Assemble the trusted read-only Codex provider config, or ``None`` (no-op).

    Returns ``None`` unless ``codex_trusted`` is set AND both the pinned binary and
    the stack root are configured; a missing value is OFF and constructs nothing.
    When all three are present it builds the provider and returns the dict shape
    ``build_trusted_codex_runtime`` consumes: ``{"trusted": True, "provider": ...,
    "stack_root": Path, "model_id": ...}``.
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
    from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
        LinuxModelProxyPeerAttestor,
    )
    from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
        ModelProxyProcessRegistry,
    )

    stack_root = Path(settings.codex_stack_root)
    _prove_the_host_can_enforce_the_cell_wall(Path(settings.codex_binary), stack_root)
    source = ProvisioningCodexPhaseAdmissionSource(stack_root=stack_root, model_id=model_id)
    # D2: the supervisor is constructed with auth=None so the child environment
    # never carries the upstream key; the provider enforces supervisor._auth is None.
    supervisor = CodexCellSupervisor(
        binary=Path(settings.codex_binary), auth=None, cell_lane=_build_cell_lane()
    )
    probe = QuarantinedCodexPreflightProbe()
    grant_store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(grant_store)
    # The SO_PEERCRED ingress ([2026] VJS-CC-VJS 1/3): the registry the supervisor
    # registers each App Server into, and the attestor the per-cell listener uses.
    registry = ModelProxyProcessRegistry()
    attestor = LinuxModelProxyPeerAttestor(registry)
    provider = TrustedProxyCodexPhaseCellProvider(
        source=source,
        supervisor=supervisor,
        probe=probe,
        broker=broker,
        grant_store=grant_store,
        registry=registry,
        attestor=attestor,
        stack_root=stack_root,
        upstream_base_url=gateway_base_url,
        # Dev bifrost is unauth, so an empty key is acceptable; prefer the configured
        # value when present.
        upstream_key=settings.model_gateway_key or "",
        http_client=_upstream_client(),
    )
    # model_id is non-secret admission policy: the resolver refuses a permanent
    # profile whose endpoint differs from the supervised cell's composed model.
    return _trusted_config(
        settings,
        provider=provider,
        stack_root=stack_root,
        model_id=model_id,
        gateway_base_url=gateway_base_url,
    )


__all__ = ["build_trusted_codex_config"]
