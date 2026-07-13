"""Governed control-plane mutations behind the kernel dispatch chokepoint.

Every ``control.*`` operation is an ordinary adapter verb, so validation,
caller grants, HITL, idempotency, rate limits, and audit run in the same fixed
order as every external action. Compatibility HTTP routes delegate here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import AgentCapability, InvocationContext, ModelEndpoint

from .control_operations import (
    activate_adapter_record,
    create_invitation_record,
    deactivate_user_record,
    generate_adapter_record,
    register_mcp_consumer,
    revoke_invitation_record,
    route_notification_record,
    safe_consequence,
    schedule_workflow_record,
    set_binding_record,
    update_user_record,
    upsert_noun_record,
    upsert_skill_record,
    upsert_verb_record,
    upsert_workflow_record,
)
from .control_safety import ControlConflict
from .control_specs import control_specs

__all__ = [
    "ControlPlaneAdapter",
    "build_control_plane_adapter",
    "register_mcp_consumer",
    "safe_consequence",
    "set_binding_record",
    "upsert_noun_record",
    "upsert_skill_record",
    "upsert_verb_record",
]

ControlHandler = Callable[[str, dict[str, Any], InvocationContext], Awaitable[Result | None]]


def _user_view(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "scope": user.scope,
        "status": user.status,
        "source": user.source,
        "source_group": user.source_group,
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
    }


class ControlPlaneAdapter:
    """The complete caller-discoverable ``control.*`` adapter."""

    id = "control"
    version = "0.2.0"
    runtime = "script"
    source = "builtin"

    def __init__(
        self,
        store: Any,
        *,
        loader: Any = None,
        registry: Any = None,
        admin: Any = None,
        workflows: Any = None,
    ) -> None:
        self._store = store
        self._loader = loader
        self._registry = registry
        self._admin = admin
        self._workflows = workflows

    def set_admin(self, admin: Any) -> None:
        self._admin = admin

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    def set_workflows(self, workflows: Any) -> None:
        self._workflows = workflows

    def describe(self) -> list[VerbSpec]:
        return control_specs()

    def readiness_collaborators(self, kernel: Any) -> dict[str, bool]:
        """Report actual composition-root wiring without executing mutations."""
        return {
            "store": self._store is kernel.store,
            "loader": self._loader is kernel.loader,
            "registry": self._registry is kernel.registry,
            "admin": self._admin is not None,
            "workflows": self._workflows is not None,
        }

    async def approval_context(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> dict[str, Any] | None:
        """Bind approvals to mutable control resources, not just request fields."""
        from .control_approval import control_approval_context

        return await control_approval_context(self._store, self._loader, verb, params, context)

    def _unavailable(self, collaborator: str) -> Result:
        return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, f"{collaborator} not wired"))

    async def _workflow(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb in {"control.workflow.schedule", "control.workflow.trigger"}:
            from .control_approval import require_unchanged_approval_context

            await require_unchanged_approval_context(
                self._store, self._loader, verb, params, context
            )
        if verb == "control.workflow.upsert":
            workflow = await upsert_workflow_record(
                self._store, tenant, params, workspace_id=context.workspace_id
            )
            return Result.success({"upserted": "workflow", "id": workflow.id})
        if verb == "control.workflow.schedule":
            schedule = await schedule_workflow_record(
                self._store, tenant, params, workspace_id=context.workspace_id
            )
            return Result.success({"id": params["workflow_id"], "schedule": schedule})
        if verb not in {"control.workflow.trigger", "control.workflow.execute"}:
            return None
        if self._workflows is None:
            return self._unavailable("workflow library")
        workflow_id, inputs = params["workflow_id"], params.get("inputs", {})
        if verb.endswith(".trigger"):
            output = await self._workflows.trigger(
                tenant,
                workflow_id,
                inputs,
                active_workspace_id=context.workspace_id,
                context=context,
            )
        else:
            output = await self._workflows.execute(tenant, workflow_id, inputs, context)
            await self._record_workflow_stats(tenant, workflow_id, output)
        return Result.success(output)

    async def _record_workflow_stats(
        self, tenant: str, workflow_id: str, output: dict[str, Any]
    ) -> None:
        run_id = output.get("run_id")
        if not run_id:
            return
        try:
            await self._store.record_workflow_run(
                tenant, workflow_id, run_id, output.get("status", "")
            )
        except Exception:
            pass  # observability cannot invalidate an already-completed run

    async def _profiles(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb == "control.capability.upsert":
            capability = AgentCapability(
                name=params["name"],
                tenant_id=tenant,
                runtime=params["runtime"],
                supported_skills=params.get("supported_skills", ["*"]),
                max_depth=int(params.get("max_depth", 1)),
                is_ephemeral=bool(params.get("is_ephemeral", True)),
                cost_tier=params.get("cost_tier", "standard"),
                model_endpoint=params.get("model_endpoint"),
            )
            await self._store.upsert_capability(capability)
            return Result.success({"upserted": "capability", "id": capability.name})
        if verb != "control.model_endpoint.upsert":
            return None
        endpoint = ModelEndpoint(
            id=params["id"],
            tenant_id=tenant,
            kind=params["kind"],
            model=params["model"],
            base_url=params.get("base_url"),
            fallback=params.get("fallback"),
            data_class=params.get("data_class", "standard"),
        )
        await self._store.upsert_model_endpoint(endpoint)
        return Result.success({"upserted": "model_endpoint", "id": endpoint.id})

    async def _registry_records(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb == "control.skill.upsert":
            skill = await upsert_skill_record(self._store, tenant, params)
            return Result.success({"upserted": "skill", "id": skill.id, "version": skill.version})
        if verb == "control.noun.define":
            noun = await upsert_noun_record(self._store, tenant, params)
            return Result.success({"upserted": "noun", "id": noun.id})
        if verb == "control.verb.define":
            defined_verb = await upsert_verb_record(self._store, tenant, params)
            return Result.success(
                {
                    "upserted": "verb",
                    "id": defined_verb.id,
                    "consequence": defined_verb.consequence.value,
                }
            )
        if verb == "control.binding.set":
            binding = await set_binding_record(self._store, tenant, params["verb_id"], params)
            return Result.success(
                {
                    "upserted": "binding",
                    "verb": binding.verb_id,
                    "target": binding.target_ref,
                }
            )
        return None

    async def _adapters(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb == "control.adapter.generate":
            if self._loader is None:
                return self._unavailable("adapter loader")
            adapter = await generate_adapter_record(
                self._store, self._loader, tenant, params, actor=context.actor
            )
            return Result.success(
                {
                    "id": adapter.id,
                    "activated": False,
                    "verbs": [item.verb_id for item in adapter.describe()],
                }
            )
        if verb == "control.adapter.activate":
            from .control_approval import require_unchanged_approval_context

            await require_unchanged_approval_context(
                self._store, self._loader, verb, params, context
            )
            if self._loader is None or self._registry is None:
                return self._unavailable("adapter registry")
            reviewer = str(context.extra.get("approved_by") or "")
            if not reviewer:
                return Result.failure(
                    AdapterError(
                        ErrorClass.UNAUTHORISED,
                        "adapter activation requires the recorded HITL reviewer",
                    )
                )
            verbs = await activate_adapter_record(
                self._store,
                self._loader,
                self._registry,
                tenant,
                params["adapter_id"],
                reviewer=reviewer,
            )
            return Result.success({"id": params["adapter_id"], "activated": True, "verbs": verbs})
        if verb != "control.mcp_server.register":
            return None
        if self._loader is None:
            return self._unavailable("adapter loader")
        consumer = await register_mcp_consumer(
            self._store,
            self._loader,
            tenant,
            {"id": params["id"], "url": params.get("url")},
            actor=context.actor,
        )
        return Result.success({"registered": "mcp_server", "id": consumer.id, "activated": False})

    async def _administration(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb in {"control.config.upsert", "control.config.rollback"}:
            if self._admin is None:
                return self._unavailable("admin config")
            if verb.endswith(".upsert"):
                revision = await self._admin.update_section(
                    params["section"], params.get("value"), context.actor
                )
                return Result.success(
                    {
                        "upserted": "config",
                        "section": params["section"],
                        "revision": revision.id,
                    }
                )
            value = await self._admin.rollback(
                params["section"], int(params["revision_id"]), context.actor
            )
            return Result.success({"section": params["section"], "value": value})
        if verb == "control.user.update":
            user = await update_user_record(self._store, tenant, params, context=context)
            return Result.success({"user": _user_view(user)})
        if verb == "control.user.deactivate":
            user = await deactivate_user_record(
                self._store, tenant, params["user_id"], context=context
            )
            return Result.success({"user": _user_view(user)})
        if verb == "control.invitation.create":
            invitation, secret = await create_invitation_record(
                self._store, tenant, params, context=context
            )
            return Result.success(
                {"id": invitation.id, "email": invitation.email, "invite_token": secret}
            )
        if verb == "control.invitation.revoke":
            invitation = await revoke_invitation_record(
                self._store, tenant, params["invite_id"], context=context
            )
            # Return id only: the compat route wraps this as {status: ok, **out},
            # so an extra "status" key here would clobber the route's ok status.
            return Result.success({"id": invitation.id})
        if verb == "control.notification.route":
            preference = await route_notification_record(
                self._store, tenant, params, context=context
            )
            return Result.success({"id": preference.id})
        return None

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        handlers: tuple[ControlHandler, ...] = (
            self._workflow,
            self._profiles,
            self._registry_records,
            self._adapters,
            self._administration,
        )
        try:
            for handler in handlers:
                result = await handler(verb, params, context)
                if result is not None:
                    return result
        except PermissionError as exc:
            return Result.failure(AdapterError(ErrorClass.UNAUTHORISED, str(exc)))
        except LookupError as exc:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, str(exc)))
        except ControlConflict as exc:
            return Result.failure(AdapterError(ErrorClass.CONFLICT, str(exc)))
        except (TypeError, ValueError) as exc:
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
        except KeyError as exc:
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, f"control dependency missing: {exc}")
            )
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return "ok"


def build_control_plane_adapter(
    store: Any,
    *,
    loader: Any = None,
    registry: Any = None,
    admin: Any = None,
    workflows: Any = None,
) -> ControlPlaneAdapter:
    return ControlPlaneAdapter(
        store,
        loader=loader,
        registry=registry,
        admin=admin,
        workflows=workflows,
    )
