"""Platform-service composition kept separate from the ASGI bootstrap facade."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Sequence

from boltrig.config import load_settings
from boltrig.config.spawn_rules import SpawnRule

log = logging.getLogger("boltrig.bootstrap")


def _platform_policy_inputs(
    manifest: Any,
    settings: Any,
    codex_config: dict[str, object] | None,
    spawn_rules: Sequence[SpawnRule],
) -> dict[str, Any]:
    from boltrig.observability.identity_policy import compose_identity_policy

    return {
        "model_policy": manifest.models if manifest is not None else None,
        "spawn_rules": tuple(spawn_rules),
        "hitl_policy": manifest.hitl if manifest is not None else None,
        "privacy_policy": manifest.privacy if manifest is not None else None,
        "user_defaults": (
            {
                "locale": manifest.locale_default,
                "timezone": manifest.timezone_default,
            }
            if manifest is not None
            else {}
        ),
        # Projection receives composition truth only, never provider details.
        "codex_trusted_provider_configured": codex_config is not None,
        "identity_policy": compose_identity_policy(manifest, settings),
    }


def _bind_distill_eval(kernel: Any, tenant: str, eval_runner: Any) -> None:
    """The distill adapter's craft gate uses the composition-owned EvalRunner
    (never constructing its own spawner - the CODEX-COMPOSITION-1 source gate);
    injected late like ``control.set_admin`` below."""
    distill = kernel.loader.peek(tenant, "distill")
    if distill is not None and hasattr(distill, "set_eval"):
        distill.set_eval(eval_runner)


def _build_platform_services(
    kernel: Any,
    *,
    manifest: Any,
    manifest_path: str | None,
    codex_config: dict[str, object] | None,
    sensitive_endpoint_id: str | None,
    spawn_rules: Sequence[SpawnRule],
    default_tenant: str,
    resume_held_write: Callable[..., Any],
    wire_hitl_resume: Callable[..., None],
    wire_memory_projection_executor: Callable[..., None],
    password_reset_notifier: Any = None,
    password_reset_readiness_probe: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build the services shared by platform routes and governed control verbs."""

    from boltrig.api.codex_execution import build_codex_execution_stack
    from boltrig.api.readiness import ReadinessService
    from boltrig.config.admin import AdminConfig
    from boltrig.fleet import build_spawner, register_workers
    from boltrig.fleet.eval import EvalRunner
    from boltrig.fleet.model_gateway_status import ModelGatewayStatusProvider
    from boltrig.fleet.stack_tool_status import StackToolStatusProvider
    from boltrig.workflows import WorkflowLibrary

    settings = load_settings()
    tenant = manifest.tenant_id if manifest is not None else default_tenant
    spawner = build_spawner(
        kernel,
        codex_config=codex_config,
        sensitive_endpoint_id=sensitive_endpoint_id,
        spawn_rules=spawn_rules,
    )
    executor = register_workers(kernel)
    log.info(
        "workflow executor: %s (durable=%s)",
        type(executor).__name__,
        executor.durable,
    )
    try:
        from boltrig.fleet.hatchet_app import register_boltrig_tasks

        register_boltrig_tasks(executor, kernel, spawner=spawner)
        wire_memory_projection_executor(kernel, tenant, executor)
    except Exception:
        log.warning("boltrig task registration failed", exc_info=True)
    wire_hitl_resume(kernel, executor=executor, resume_held_write=resume_held_write)

    admin = AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path)
    workflows = WorkflowLibrary(kernel.store, executor=executor, kernel=kernel)
    control = kernel.loader.peek(tenant, "control")
    if control is not None and hasattr(control, "set_admin"):
        control.set_admin(admin)
    if control is not None and hasattr(control, "set_workflows"):
        control.set_workflows(workflows)

    eval_runner = EvalRunner(kernel, spawner, workflows=workflows)
    _bind_distill_eval(kernel, tenant, eval_runner)
    status = StackToolStatusProvider(ModelGatewayStatusProvider())
    codex_execution = build_codex_execution_stack(settings, kernel.store)
    return {
        "admin": admin,
        "eval": eval_runner,
        "spawner": spawner,
        **_platform_policy_inputs(manifest, settings, codex_config, spawn_rules),
        "codex_execution": codex_execution,
        "workflows": workflows,
        "password_reset_notifier": password_reset_notifier,
        "password_reset_readiness_probe": password_reset_readiness_probe,
        "status": status,
        "readiness": ReadinessService(
            kernel,
            tenant_id=tenant,
            executor=executor,
            status_provider=status,
            password_reset_notifier=password_reset_notifier,
            password_reset_probe=password_reset_readiness_probe,
        ),
    }


def make_platform_factory(
    *,
    manifest: Any,
    manifest_path: str | None,
    codex_config: dict[str, object] | None,
    sensitive_endpoint_id: str | None,
    spawn_rules: Sequence[SpawnRule],
    default_tenant: str,
    resume_held_write: Callable[..., Any],
    wire_hitl_resume: Callable[..., None],
    wire_memory_projection_executor: Callable[..., None],
    password_reset_notifier: Any = None,
    password_reset_readiness_probe: Callable[..., Any] | None = None,
) -> Callable[[Any], dict[str, Any]]:
    """Bind immutable boot inputs while leaving the kernel lifespan-late."""

    return functools.partial(
        _build_platform_services,
        manifest=manifest,
        manifest_path=manifest_path,
        codex_config=codex_config,
        sensitive_endpoint_id=sensitive_endpoint_id,
        spawn_rules=spawn_rules,
        default_tenant=default_tenant,
        resume_held_write=resume_held_write,
        wire_hitl_resume=wire_hitl_resume,
        wire_memory_projection_executor=wire_memory_projection_executor,
        password_reset_notifier=password_reset_notifier,
        password_reset_readiness_probe=password_reset_readiness_probe,
    )


__all__ = ["make_platform_factory"]
