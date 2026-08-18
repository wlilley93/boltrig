"""Reviewed integration catalogue and tenant connection projections."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.models.base import utcnow

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author
from .integration_setup import public_secret_contract, register_integration_setup


async def _enabled_tools(kernel, tenant_id: str, adapter_id: str) -> list[str]:
    enabled: list[str] = []
    for verb in await kernel.store.list_verbs(tenant_id):
        binding = await kernel.store.get_binding(tenant_id, verb.id)
        if binding is not None and binding.target_ref == adapter_id:
            enabled.append(verb.id)
    return sorted(enabled)


async def _enabled_capabilities(kernel, tenant_id: str, adapter_id: str) -> list[str]:
    """The canonical capabilities this connection actually serves.

    ``enabled_tools`` above counts raw verb ids bound to the adapter - the
    SOURCE OPERATIONS. Once a capability layer exists that stops being the
    honest answer to "what can this connection do": two connections can serve
    one capability, and a provider-prefixed verb id is not what the model ever
    sees (SPEC §11.1 site 6). Only APPROVED bindings count, so a proposed
    mapping is invisible here exactly as it is invisible to routing.
    """
    connection_ids = {
        connection.id
        for connection in await kernel.store.list_provider_connections(tenant_id)
        if connection.adapter_id == adapter_id
    }
    if not connection_ids:
        return []
    # UNPINNED, deliberately. `binding.ref` is `crm.contact.search@1`, and every
    # governance path reads the unpinned id: grant_verbs checks it, blocking_names
    # drops the pin, governed_aliases resolves it. Publishing the pinned form made
    # this page's most copyable string the one that matches nothing - paste it
    # into a role scope or a skill's tool_grants and the grant is legal, silent
    # and inert. The version is an addressing detail of one call, not an identity
    # a person acts on.
    return sorted(
        {
            binding.capability_id
            for binding in await kernel.store.list_capability_bindings(tenant_id)
            if binding.connection_id in connection_ids and binding.status == "approved"
        }
    )


def _permitted_tools(principal, tools: list[str]) -> list[str]:
    """The subset of a projection's tools this caller may actually call.

    An author administers integrations and sees the whole list - that is the
    job. For anyone else the projection is narrowed to what their grants reach,
    so the page answers "what can I use" rather than "what has this tenant
    wired up".
    """
    from boltrig.identity.rbac import can_author

    if can_author(principal.role):
        return list(tools)
    return [verb for verb in tools if principal.grants.permits(verb)]


def _may_see(principal, permitted: list[str]) -> bool:
    """Whether a CONNECTION belongs in this caller's list at all.

    Decided from what survived the narrowing, with one exception: an author
    still sees a connection whose tool list is empty, which is how a revoked one
    stays visible to the person who has to manage it.

    This closes the door that made the route_required hardening half a measure.
    Resolving a capability no longer names the tenant's connected systems to an
    ungranted caller, and now neither does asking this route for the list. A
    member with no integration grants sees an empty list, which is the true
    answer rather than an outage (SPEC 11.11).
    """
    from boltrig.identity.rbac import can_author

    return bool(permitted) or can_author(principal.role)


async def _catalogue_view(kernel, tenant_id: str, item) -> dict:
    adapter = (
        await kernel.store.get_adapter(tenant_id, item.adapter_id)
        if item.adapter_id
        else None
    )
    health = (
        kernel.loader.health_of(tenant_id, item.adapter_id)
        if item.adapter_id
        else "unknown"
    )
    available = bool(
        item.certification == "certified"
        and adapter is not None
        and adapter.activated
        and health in {"ok", "degraded"}
    )
    if item.certification != "certified":
        reason = "not_certified"
    elif adapter is None:
        reason = "adapter_not_registered"
    elif not adapter.activated:
        reason = "adapter_not_activated"
    elif health not in {"ok", "degraded"}:
        reason = "adapter_health_unverified" if health == "unknown" else "adapter_down"
    else:
        reason = None
    return {
        "id": item.id,
        "label": item.label,
        "category": item.category,
        "transport": item.transport,
        "auth": list(item.auth),
        "description": item.description,
        "certification": item.certification,
        "setup_copy": item.setup_copy,
        "access_copy": item.access_copy,
        "available": available,
        "availability_reason": reason,
        "setup_supported": bool(available and item.secret_contract is not None),
        "setup_contract": (
            public_secret_contract(item.secret_contract)
            if available
            else None
        ),
        "enabled_tools": (
            await _enabled_tools(kernel, tenant_id, item.adapter_id)
            if item.adapter_id
            else []
        ),
    }


def visible_to(connection, viewer: str) -> bool:
    """May ``viewer`` see this connection at all?

    Org connections are shared and visible to everyone in the tenant. A personal
    one is visible only to its owner. Before scoping there was at most one row
    per adapter and it was always the org's, so this is a new fence for a new
    kind of row rather than a tightening of an old surface -- but it is load
    bearing: accounts[].id is routinely an email address, so an unfenced list
    would hand every member every other member's provider identity.

    This is the OWNERSHIP half of the fence. `_may_see` below is the CAPABILITY
    half, and the two are complementary rather than alternatives: ownership
    keeps one member's provider identity from another, grants keep the tenant's
    wiring from a caller who can use none of it. The list route applies both.
    """
    return connection.level == "org" or connection.scope_id == viewer


async def _connection_view(kernel, tenant_id: str, connection, viewer: str = "") -> dict:
    revoked = connection.health == "revoked"
    enabled = (
        [] if revoked else await _enabled_tools(kernel, tenant_id, connection.adapter_id)
    )
    capabilities = (
        []
        if revoked
        else await _enabled_capabilities(kernel, tenant_id, connection.adapter_id)
    )
    accounts = [
        {
            "id": str(account.get("id") or "")[:200],
            "label": str(account.get("label") or "")[:200],
            "selected": bool(account.get("selected")),
        }
        for account in connection.accounts[:100]
        if isinstance(account, dict)
    ]
    return {
        "id": connection.id,
        "integration_id": connection.integration_id,
        "label": connection.label,
        "health": connection.health,
        "credential_ref_present": bool(connection.credential_ref),
        "level": connection.level,
        "scope_id": connection.scope_id,
        "is_own": connection.level == "user" and connection.scope_id == viewer,
        "accounts": accounts,
        "enabled_tools": enabled,
        "enabled_capabilities": capabilities,
        "last_checked_at": (
            connection.last_checked_at.isoformat()
            if connection.last_checked_at
            else None
        ),
        "created_at": connection.created_at.isoformat(),
    }


def _register_reads(app, P, K) -> None:
    @app.get("/v1/integrations/catalogue")
    async def catalogue(k=K, p=P) -> dict:
        # The catalogue is a SHELF - which integrations exist and whether they
        # are available - and stays visible to every member, because knowing
        # Slack is supported discloses nothing about this tenant. Its
        # enabled_tools does, so that field is narrowed to what the caller may
        # actually call.
        k.loader.health_snapshot()
        items = await k.store.list_integration_catalogue(p.tenant_id)
        views = [await _catalogue_view(k, p.tenant_id, item) for item in items]
        for view in views:
            view["enabled_tools"] = _permitted_tools(p, view["enabled_tools"])
        return {"integrations": views}

    @app.get("/v1/integrations/connections")
    async def connections(k=K, p=P) -> dict:
        # BOTH fences, because they refuse different things. `visible_to`
        # is ownership: a personal connection is its owner's, and accounts[].id
        # is routinely an email address. `_may_see` over the narrowed tool list
        # is capability: a caller who can use none of it has no reason to learn
        # it is there (SPEC 11.11). Dropping either one reopens a door.
        viewer = str(getattr(p, "subject", "") or "")
        rows = await k.store.list_integration_connections(p.tenant_id)
        listed = []
        for row in rows:
            if not visible_to(row, viewer):
                continue
            view = await _connection_view(k, p.tenant_id, row, viewer)
            view["enabled_tools"] = _permitted_tools(p, view["enabled_tools"])
            if _may_see(p, view["enabled_tools"]):
                listed.append(view)
        return {"connections": listed}


def _member_connection_view(connection) -> dict:
    """The deliberately thin projection an administrator sees of somebody else's
    connection: enough to know it exists and to revoke it, and nothing more.

    ``accounts`` is the omission that matters. It carries the member's identity AT
    THE PROVIDER -- routinely a personal email address -- which is why
    :func:`visible_to` hides these rows from everyone but their owner. Offboarding
    needs to know THAT a member connected a provider, never which account they
    used, so widening the fence to administer these rows must not widen it to read
    them. ``enabled_tools`` is left out for a duller reason: it is a property of
    the adapter, identical on every row, and costs a verb scan each time.
    """
    return {
        "id": connection.id,
        "integration_id": connection.integration_id,
        "label": connection.label,
        "health": connection.health,
        "credential_ref_present": bool(connection.credential_ref),
        "level": connection.level,
        "owner": connection.scope_id,
        "last_checked_at": (
            connection.last_checked_at.isoformat() if connection.last_checked_at else None
        ),
        "created_at": connection.created_at.isoformat(),
    }


def _register_member_connections(app, P, K) -> None:
    @app.get("/v1/integrations/member-connections")
    async def member_connections(k=K, p=P) -> dict:
        """Every OTHER member's personal connections, for offboarding.

        The caller's own are excluded rather than merged in: they already appear
        on /v1/integrations/connections, and keeping them out means the revoke
        below can refuse a self-revocation as the fail-closed guard it is instead
        of as a dead end the console can walk a user into.
        """
        require_author(p)
        viewer = str(getattr(p, "subject", "") or "")
        rows = await k.store.list_integration_connections(p.tenant_id)
        return {
            "connections": [
                _member_connection_view(row)
                for row in rows
                if row.level != "org" and row.scope_id != viewer
            ]
        }

    @app.delete("/v1/integrations/member-connections/{connection_id}")
    async def revoke_member_connection(
        connection_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        """Destroy a departing member's sealed credential. Author roles only, and
        the control verb re-checks everything: this route is not the fence."""
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.integration.revoke_member",
            {"connection_id": connection_id},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "revoked", **(output or {})})


def _register_connection_lifecycle(app, P, K) -> None:
    @app.get("/v1/integrations/connections/{connection_id}/health")
    async def connection_health(connection_id: str, k=K, p=P) -> JSONResponse:
        viewer = str(getattr(p, "subject", "") or "")
        connection = await k.store.get_integration_connection(
            p.tenant_id, connection_id
        )
        # not_found rather than forbidden for somebody else's row: a 403 would
        # confirm that a connection with that id exists, and this route both
        # probes the provider and writes the health column.
        if connection is None or not visible_to(connection, viewer):
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if connection.health != "revoked":
            await k.loader.refresh_health()
            record = await k.store.get_adapter(p.tenant_id, connection.adapter_id)
            health = (
                k.loader.health_of(p.tenant_id, connection.adapter_id)
                if record is not None and record.activated
                else "down"
            )
            checked_at = utcnow()
            connection = await k.store.update_integration_connection_health_if_active(
                p.tenant_id,
                connection_id,
                health if health in {"ok", "degraded", "down"} else "pending",
                checked_at,
            )
            if connection is None:
                connection = await k.store.get_integration_connection(
                    p.tenant_id, connection_id
                )
                if connection is None:
                    return JSONResponse(
                        {"status": "error", "reason": "not_found"}, status_code=404
                    )
        return JSONResponse({
            "connection": await _connection_view(k, p.tenant_id, connection, viewer)
        })

    @app.delete("/v1/integrations/connections/{connection_id}")
    async def revoke_connection(
        connection_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        viewer = str(getattr(p, "subject", "") or "")
        existing = await k.store.get_integration_connection(p.tenant_id, connection_id)
        if existing is None or not visible_to(existing, viewer):
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        # An author role administers the ORG's shared connection. A personal one
        # is its owner's to disconnect, and require_author would have stopped the
        # member who created it -- while letting any of the seven author roles
        # revoke somebody else's. The control handler re-checks ownership, since
        # the verb is reachable without this route.
        if existing.level == "org":
            require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.integration.revoke",
            {"connection_id": connection_id},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "revoked", **(output or {})})


def register(app, P, K) -> None:
    _register_reads(app, P, K)
    register_integration_setup(app, P, K, connection_view=_connection_view)
    _register_connection_lifecycle(app, P, K)
    _register_member_connections(app, P, K)
