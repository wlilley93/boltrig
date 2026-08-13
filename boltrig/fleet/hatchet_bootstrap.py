"""Composition-owned resources for the durable Hatchet worker."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("boltrig.fleet.hatchet_app")


def _build_process_spawner(kernel, manifest, codex_config, model_catalogue):
    from .spawn import build_spawner

    if manifest is None:
        return build_spawner(
            kernel,
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=None,
        )
    return build_spawner(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint,
        spawn_rules=manifest.spawn_rules,
    )


async def _default_bootstrap() -> dict[str, Any]:
    """Build the worker-owned kernel, spawner, and org pump on its running loop."""
    from boltrig.addons import active_addons
    from boltrig.api.bootstrap import (
        _DEFAULT_TENANT,
        _build_shared_codex_config,
        _find_manifest,
        _publish_birth_profile_startup,
        build_kernel_async,
        wire_hitl_resume,
    )
    from boltrig.api.codex_execution import build_codex_execution_stack
    from boltrig.config import load_manifest, load_settings
    from boltrig.config.permanent_fleet import (
        effective_manifest_from_desired,
        record_permanent_fleet_startup_observation,
    )

    from .pump import build_org
    from boltrig.api.model_runtime_composition import compose_process_model_runtime

    manifest_path, manifest_snapshot, codex_config, model_catalogue = (
        compose_process_model_runtime(
            find_manifest=_find_manifest,
            load_manifest=load_manifest,
            build_codex_config=_build_shared_codex_config,
        )
    )
    addons_snapshot = active_addons()
    desired_overlay_applied = False
    sensitive_endpoint_id = (
        manifest_snapshot.models.sensitive_endpoint if manifest_snapshot else None
    )
    kernel = await build_kernel_async(
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        manifest_snapshot=manifest_snapshot,
        manifest_path=manifest_path,
    )
    manifest = manifest_snapshot
    if manifest is not None:
        try:
            manifest = await effective_manifest_from_desired(kernel.store, manifest)
            desired_overlay_applied = True
        except Exception as exc:
            log.warning("manifest load failed (%s); using the default org", exc)
            manifest = None
    tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT
    spawner = _build_process_spawner(kernel, manifest, codex_config, model_catalogue)
    pump = build_org(
        kernel,
        spawner,
        manifest,
        codex_execution=build_codex_execution_stack(load_settings(), kernel.store),
    )
    await _publish_birth_profile_startup(
        kernel,
        process_kind="hatchet",
        manifest=manifest,
        addons_snapshot=addons_snapshot,
        codex_config=codex_config,
        sensitive_endpoint_id=manifest.models.sensitive_endpoint if manifest else None,
    )
    if desired_overlay_applied:
        await record_permanent_fleet_startup_observation(
            kernel.store,
            tenant,
            os.environ.get("HOSTNAME") or "fleet-worker",
        )
    wire_hitl_resume(kernel, pump=pump)
    return {"kernel": kernel, "pump": pump, "spawner": spawner}
