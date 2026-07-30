"""Governed control-plane mutations behind the kernel dispatch chokepoint.

Every ``control.*`` operation is an ordinary adapter verb, so validation,
caller grants, HITL, idempotency, rate limits, and audit run in the same fixed
order as every external action. Compatibility HTTP routes delegate here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import InvocationContext

from .control_operations import (
    activate_adapter_record,
    create_invitation_record,
    deactivate_user_record,
    generate_adapter_record,
    revoke_invitation_record,
    safe_consequence,
    set_binding_record,
    update_user_record,
    upsert_noun_record,
    upsert_skill_record,
    upsert_verb_record,
)
from .control_notifications import (
    route_notification_record,
    test_notification_record,
)
from .control_profiles import execute_profile_operation
from .permanent_fleet import execute_permanent_fleet_operation
from .control_registry_operations import execute_registry_operation
from .control_mcp import register_mcp_consumer
from .control_mcp_lifecycle import execute_mcp_lifecycle_operation
from .control_lifecycle import execute_adapter_lifecycle
from .control_integrations import execute_integration_operation
from .control_safety import ControlConflict
from .control_specs import control_specs
from .control_compat import execute_compat_operation
from .control_budget import execute_budget_operation
from .control_work import execute_work_operation
from .control_workflow_dispatch import execute_workflow_control

__all__ = ["ControlPlaneAdapter", "build_control_plane_adapter", "register_mcp_consumer",
           "safe_consequence", "set_binding_record", "upsert_noun_record",
           "upsert_skill_record", "upsert_verb_record"]

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
        credentials: Any = None,
    ) -> None:
        self._store = store
        self._loader = loader
        self._registry = registry
        self._admin = admin
        self._workflows = workflows
        self._credentials = credentials

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
        return await execute_workflow_control(
            self._store, self._workflows, self._loader, verb, params, context
        )

    async def _profiles(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        return await execute_profile_operation(
            self._store, self._loader, verb, params, context
        )

    async def _permanent_fleet(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        if verb == "control.permanent_fleet.apply" and self._admin is None:
            return self._unavailable("admin config")
        return await execute_permanent_fleet_operation(
            self._store, verb, params, context, admin=self._admin
        )

    async def _registry_records(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        return await execute_registry_operation(
            self._store, self._loader, verb, params, context
        )

    async def _adapters(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        tenant = context.tenant_id
        if verb in {
            "control.adapter.activate",
            "control.adapter.deactivate",
            "control.adapter.delete",
        }:
            from .control_rehydrate import is_mcp_consumer

            adapter_id = str(params.get("adapter_id") or "")
            record = await self._store.get_adapter(tenant, adapter_id)
            if record is not None and is_mcp_consumer(record):
                raise ControlConflict(
                    "external MCP servers use control.mcp_server lifecycle controls"
                )
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
                self._store, self._loader, self._registry, tenant, params["adapter_id"],
                reviewer=reviewer, credentials=self._credentials,
            )
            return Result.success({"id": params["adapter_id"], "activated": True, "verbs": verbs})
        if verb in {"control.adapter.deactivate", "control.adapter.delete"}:
            return await execute_adapter_lifecycle(
                self._store, self._loader, self._credentials, verb, params, context
            )
        if verb != "control.mcp_server.register":
            return None
        if self._loader is None:
            return self._unavailable("adapter loader")
        consumer = await register_mcp_consumer(
            self._store,
            self._loader,
            tenant,
            params,
            actor=context.actor,
            credentials=self._credentials,
        )
        return Result.success({"registered": "mcp_server", "id": consumer.id, "activated": False})

    async def _mcp_lifecycle(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        return await execute_mcp_lifecycle_operation(
            self._store,
            self._loader,
            self._registry,
            self._credentials,
            verb,
            params,
            context,
        )

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
        if verb == "control.notification.test":
            delivery = await test_notification_record(
                self._store, tenant, params["id"], context=context
            )
            return Result.success(delivery)
        return None

    async def _integrations(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        return await execute_integration_operation(
            self._store, self._loader, self._credentials, verb, params, context
        )

    async def _compatibility(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        output = await execute_compat_operation(self._store, verb, params, context)
        return None if output is None else Result.success(output)

    async def _budgets(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        output = await execute_budget_operation(self._store, verb, params, context)
        return None if output is None else Result.success(output)

    async def _work(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result | None:
        output = await execute_work_operation(
            self._store, self._loader, verb, params, context
        )
        return None if output is None else Result.success(output)

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
            self._permanent_fleet,
            self._registry_records,
            self._mcp_lifecycle,
            self._adapters,
            self._integrations,
            self._administration,
            self._budgets,
            self._work,
            self._compatibility,
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
    credentials: Any = None,
) -> ControlPlaneAdapter:
    return ControlPlaneAdapter(
        store, loader=loader, registry=registry, admin=admin,
        workflows=workflows, credentials=credentials,
    )
