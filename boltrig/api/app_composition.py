"""Top-level API application composition."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from boltrig.kernel import Kernel

log = logging.getLogger("boltrig.bootstrap")


def _make_kernel_factory(
    *,
    build_kernel_async: Callable[..., Any],
    publish_birth_profile_startup: Callable[..., Any],
    codex_config: dict[str, object] | None,
    model_catalogue: Any,
    sensitive_endpoint_id: str | None,
    manifest: Any,
    manifest_path: str | None,
    addons: Any,
) -> Callable[[], Any]:
    async def kernel_factory() -> Kernel:
        kernel = await build_kernel_async(
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=sensitive_endpoint_id,
            manifest_snapshot=manifest,
            manifest_path=manifest_path,
        )
        effective_manifest = await _effective_manifest(kernel, manifest)
        if manifest is not None and effective_manifest is None:
            return kernel
        await publish_birth_profile_startup(
            kernel,
            process_kind="api",
            manifest=effective_manifest,
            addons_snapshot=addons,
            codex_config=codex_config,
            sensitive_endpoint_id=sensitive_endpoint_id,
        )
        return kernel

    return kernel_factory


def compose_api_app(
    *,
    addons_snapshot: Any,
    password_reset_notifier: Any,
    password_reset_readiness_probe: Any,
    default_tenant: str,
    build_shared_codex_config: Callable[[], dict[str, object] | None],
    find_manifest: Callable[[], str | None],
    load_manifest: Callable[[str], Any],
    build_chat_wiring: Callable[..., tuple[Any, Any]],
    build_kernel_async: Callable[..., Any],
    make_app_spawner: Callable[..., Any],
    select_principal_resolver: Callable[[Any], Any],
    publish_birth_profile_startup: Callable[..., Any],
    wire_hitl_resume: Callable[..., None],
    wire_memory_projection_executor: Callable[..., None],
):
    """Compose lazy process resources while preserving one shared Codex provider."""

    from boltrig.addons import active_addons
    from boltrig.api.model_runtime_composition import compose_process_model_runtime
    from boltrig.api.platform_bootstrap import make_platform_factory
    from boltrig.kernel.app import create_app

    addons = active_addons() if addons_snapshot is None else addons_snapshot
    manifest_path, manifest, codex_config, model_catalogue = (
        compose_process_model_runtime(
            find_manifest=find_manifest,
            load_manifest=load_manifest,
            build_codex_config=build_shared_codex_config,
        )
    )
    spawn_rules: Sequence[Any] = manifest.spawn_rules if manifest is not None else ()
    sensitive_endpoint_id = manifest.models.sensitive_endpoint if manifest is not None else None
    chat_factory, resume_held_write = build_chat_wiring(
        codex_config,
        spawn_rules,
        sensitive_endpoint_id,
        model_catalogue,
    )
    platform_factory = make_platform_factory(
        manifest=manifest,
        manifest_path=manifest_path,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        spawn_rules=spawn_rules,
        default_tenant=default_tenant,
        resume_held_write=resume_held_write,
        wire_hitl_resume=wire_hitl_resume,
        wire_memory_projection_executor=wire_memory_projection_executor,
        password_reset_notifier=password_reset_notifier,
        password_reset_readiness_probe=password_reset_readiness_probe,
    )

    kernel_factory = _make_kernel_factory(
        build_kernel_async=build_kernel_async,
        publish_birth_profile_startup=publish_birth_profile_startup,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        manifest=manifest,
        manifest_path=manifest_path,
        addons=addons,
    )

    return create_app(
        kernel_factory=kernel_factory,
        spawner_factory=lambda kernel: make_app_spawner(
            kernel,
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=sensitive_endpoint_id,
            spawn_rules=spawn_rules,
        ),
        principal_resolver=select_principal_resolver(manifest),
        chat_factory=chat_factory,
        platform_factory=platform_factory,
    )


async def _effective_manifest(kernel: Kernel, manifest: Any) -> Any:
    if manifest is None:
        return None
    from boltrig.config.permanent_fleet import effective_manifest_from_desired

    try:
        return await effective_manifest_from_desired(kernel.store, manifest)
    except Exception:
        log.warning(
            "API birth-profile effective manifest unavailable; startup receipt not published",
            exc_info=True,
        )
        return None


__all__ = ["compose_api_app"]
