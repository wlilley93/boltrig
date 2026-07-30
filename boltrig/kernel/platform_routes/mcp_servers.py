"""Author-only external-MCP lifecycle, snapshot, and probe projections."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.config.control_mcp_lifecycle import (
    owned_tool_snapshot,
    snapshot_digest,
)
from boltrig.config.control_rehydrate import consumer_spec, is_mcp_consumer
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import MCP_MAX_TOOL_SNAPSHOT

from ._shared import require_author

MAX_MCP_SERVERS = 200
MAX_MCP_TOOLS = MCP_MAX_TOOL_SNAPSHOT
MAX_MCP_PROBE_HISTORY = 20
_HEALTH = frozenset({"ok", "degraded", "down", "unknown"})


def _endpoint_origin(raw: str | None) -> str | None:
    """Return only scheme + host + port; credentials, path and query stay private."""
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    shown_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{shown_host}:{port}" if port is not None else shown_host
    return f"{parsed.scheme.lower()}://{netloc}"


def _receipt_view(receipt) -> dict:
    return {
        "probe_id": receipt.probe_id,
        "checked_at": receipt.observed_at.isoformat(),
        "outcome": receipt.outcome,
        "failure_code": receipt.failure_code,
        "tool_count": receipt.tool_count,
    }


def _available_actions(
    state: str, *, endpoint_configured: bool
) -> list[str]:
    if state == "retired":
        return ["restore", "delete"]
    if state == "active":
        return (
            ["probe", "deactivate"]
            if endpoint_configured
            else ["deactivate"]
        )
    return (
        ["probe", "activate", "update", "retire", "delete"]
        if endpoint_configured
        else ["update", "retire", "delete"]
    )


async def _publication_status(kernel, tenant_id: str, lifecycle) -> str:
    if lifecycle.tools_observed_at is None:
        return "never_discovered"
    if lifecycle.state == "retired":
        return "retired"
    if lifecycle.state == "inactive":
        return "inactive"
    published = await owned_tool_snapshot(
        kernel.store, tenant_id, lifecycle.server_id
    )
    return (
        "published"
        if snapshot_digest(published)
        == snapshot_digest(lifecycle.last_known_tools)
        else "drifted"
    )


def _operability(
    *,
    state: str,
    loaded: bool,
    endpoint_configured: bool,
    health: str,
    publication_status: str,
) -> dict:
    if state == "retired":
        return {"status": "unavailable", "reason": "retired"}
    if not endpoint_configured:
        return {"status": "unavailable", "reason": "endpoint_not_configured"}
    if state != "active":
        return {"status": "unavailable", "reason": "pending_activation"}
    if publication_status == "drifted":
        return {"status": "degraded", "reason": "tool_catalogue_drift"}
    if not loaded:
        return {"status": "unavailable", "reason": "adapter_instance_unavailable"}
    if health == "ok":
        return {"status": "ready", "reason": None}
    if health == "degraded":
        return {"status": "degraded", "reason": "adapter_degraded"}
    if health == "down":
        return {"status": "unavailable", "reason": "adapter_down"}
    return {"status": "degraded", "reason": "health_unverified"}


async def _server_view(kernel, tenant_id: str, record, lifecycle) -> dict:
    spec = consumer_spec(record.spec_ref)
    origin = _endpoint_origin(spec.get("url"))
    loaded = kernel.loader.peek(tenant_id, record.id) is not None
    cached = kernel.loader.health_of(tenant_id, record.id) if loaded else "unknown"
    cached_health = cached if cached in _HEALTH else "unknown"
    latest = await kernel.store.get_latest_mcp_probe_receipt(
        tenant_id, record.id
    )
    if latest is not None:
        health = "ok" if latest.outcome == "succeeded" else "down"
        health_source = "durable_probe"
        checked_at = latest.observed_at.isoformat()
    elif cached_health != "unknown":
        health = cached_health
        health_source = "cached_adapter_probe"
        checked_at = None
    else:
        health = "unknown"
        health_source = "unverified"
        checked_at = None
    publication = await _publication_status(kernel, tenant_id, lifecycle)
    credential_id = spec.get("credential_id")
    if not spec.get("credential_binding_explicit"):
        credential_id = f"{record.id}-mcp-token"
    credential_configured = bool(
        credential_id
        and await kernel.store.has_credential_ref(tenant_id, credential_id)
    )
    return {
        "id": record.id,
        "version": record.version,
        "source": record.source,
        "config_revision": getattr(lifecycle, "config_revision", 1),
        "state": "inert" if lifecycle.state == "inactive" else lifecycle.state,
        "activated": lifecycle.state == "active",
        "runtime_loaded": loaded,
        "endpoint": {
            "origin": origin,
            "path_redacted": bool(
                (urlsplit(spec["url"]).path or "").strip("/")
            )
            if origin
            else False,
            "internal_egress_allowed": bool(spec.get("allow_internal")),
        },
        "credential_configured": credential_configured,
        "recorded_health": record.health.value,
        "health": {
            "status": health,
            "source": health_source,
            "checked_at": checked_at,
        },
        "last_probe": None if latest is None else _receipt_view(latest),
        "tool_snapshot": {
            "status": (
                "never_discovered"
                if lifecycle.tools_observed_at is None
                else "snapshot"
            ),
            "observed_at": (
                lifecycle.tools_observed_at.isoformat()
                if lifecycle.tools_observed_at
                else None
            ),
            "count": len(lifecycle.last_known_tools),
            "publication_status": publication,
        },
        "operability": _operability(
            state=lifecycle.state,
            loaded=loaded,
            endpoint_configured=origin is not None,
            health=health,
            publication_status=publication,
        ),
        "available_actions": _available_actions(
            lifecycle.state, endpoint_configured=origin is not None
        ),
    }


def _tool_view(tool, server_id: str) -> dict:
    return {
        "id": f"{server_id}.{tool.name}",
        "name": tool.name,
        "description": tool.description,
        "consequence": tool.consequence,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }


async def _mcp_record(kernel, tenant_id: str, server_id: str):
    record = await kernel.store.get_adapter(tenant_id, server_id)
    lifecycle = await kernel.store.get_mcp_server_lifecycle(
        tenant_id, server_id
    )
    if (
        record is None
        or lifecycle is None
        or not is_mcp_consumer(record)
    ):
        return None
    return record, lifecycle


def _register_reads(app, P, K) -> None:
    @app.get("/v1/mcp/servers")
    async def list_mcp_servers(k=K, p=P) -> dict:
        require_author(p)
        records = {
            row.id: row
            for row in await k.store.list_adapters(p.tenant_id)
            if is_mcp_consumer(row)
        }
        lifecycles = await k.store.list_mcp_server_lifecycles(p.tenant_id)
        rows = [
            (records[lifecycle.server_id], lifecycle)
            for lifecycle in lifecycles
            if lifecycle.server_id in records
        ]
        rows.sort(key=lambda item: item[0].id)
        page = rows[:MAX_MCP_SERVERS]
        return {
            "servers": [
                await _server_view(k, p.tenant_id, record, lifecycle)
                for record, lifecycle in page
            ],
            "truncated": len(rows) > len(page),
        }

    @app.get("/v1/mcp/servers/{server_id}")
    async def get_mcp_server(
        server_id: str, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        pair = await _mcp_record(k, p.tenant_id, server_id)
        if pair is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        record, lifecycle = pair
        tools = list(lifecycle.last_known_tools[:MAX_MCP_TOOLS])
        history = await k.store.list_mcp_probe_receipts(
            p.tenant_id, server_id, limit=MAX_MCP_PROBE_HISTORY
        )
        return JSONResponse(
            {
                "server": await _server_view(
                    k, p.tenant_id, record, lifecycle
                ),
                "tools": [
                    _tool_view(tool, server_id) for tool in tools
                ],
                "tools_status": (
                    "snapshot"
                    if lifecycle.tools_observed_at is not None
                    else "never_discovered"
                ),
                "tools_truncated": (
                    len(lifecycle.last_known_tools) > len(tools)
                ),
                "probe_history": [
                    _receipt_view(receipt) for receipt in history
                ],
                "probe_history_truncated": False,
            }
        )


def _register_lifecycle(app, P, K) -> None:
    async def dispatch(
        server_id: str, action: str, request: Request, k, p
    ) -> JSONResponse:
        require_author(p)
        if await _mcp_record(k, p.tenant_id, server_id) is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        output, pending = await dispatch_control_route(
            k,
            p,
            f"control.mcp_server.{action}",
            {"server_id": server_id},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/mcp/servers/{server_id}/probe")
    async def probe(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "probe", request, k, p)

    @app.post("/v1/mcp/servers/{server_id}/activate")
    async def activate(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "activate", request, k, p)

    @app.post("/v1/mcp/servers/{server_id}/deactivate")
    async def deactivate(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "deactivate", request, k, p)

    @app.post("/v1/mcp/servers/{server_id}/retire")
    async def retire(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "retire", request, k, p)

    @app.post("/v1/mcp/servers/{server_id}/restore")
    async def restore(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "restore", request, k, p)

    @app.put("/v1/mcp/servers/{server_id}")
    async def update(
        server_id: str,
        body: dict,
        request: Request,
        k=K,
        p=P,
    ) -> JSONResponse:
        require_author(p)
        if await _mcp_record(k, p.tenant_id, server_id) is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.mcp_server.update",
            {"server_id": server_id, **body},
            request=request,
        )
        return pending or JSONResponse(
            {"status": "ok", **(output or {})}
        )

    @app.delete("/v1/mcp/servers/{server_id}")
    async def delete(
        server_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await dispatch(server_id, "delete", request, k, p)


def register(app, P, K) -> None:
    _register_reads(app, P, K)
    _register_lifecycle(app, P, K)
