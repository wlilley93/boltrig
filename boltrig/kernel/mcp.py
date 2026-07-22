"""The kernel's MCP server face (Round Two, Epic MCP).

Granted verbs are advertised as MCP tools, adapter-declared knowledge mappings
are advertised as MCP resources, and every tool or resource read runs the
unchanged dispatch chokepoint (P2, SEC-26). A connection is scoped by a per-run
token (skill grants ∩ tenant ceiling), so a run sees and can call only its own
tools and resources (SEC-23, FR-MCP-02). Credentials are resolved inside the
kernel and never cross this boundary (SEC-27).

This is a thin JSON-RPC 2.0 face (the MCP wire shape: ``initialize``, tools, and
resources); it adds no policy of its own, only translation into
``kernel.invoke`` - so the core stays thin (P1) and dep-light.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote, unquote

from boltrig.adapters.base import McpResourceSpec

from boltrig.models import (
    DegradedMode,
    GrantSet,
    InvocationContext,
    BoltrigError,
    PendingHuman,
    SecurityEventType,
    utcnow,
)

_PROTOCOL_VERSION = "2024-11-05"


def _ok(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


@dataclass(frozen=True)
class RunToken:
    """A run-scoped MCP connection record (least privilege, SEC-23)."""

    lease_id: str
    tenant_id: str
    grants: GrantSet
    run_id: str | None = None
    actor: str = "ephemeral"
    skills: tuple[str, ...] = field(default_factory=tuple)
    # The active WORKSPACE the MCP caller operates in ([2026] VJS-COUNTY 9, D2), so
    # an MCP-initiated audit row carries org/workspace at the SAME depth as a human
    # action. None = no active workspace. Additive with a None default.
    workspace_id: str | None = None
    on_behalf_of: str | None = None
    extra: dict = field(default_factory=dict)
    issued_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None


class McpFace:
    MAX_RUN_TOKEN_TTL_SECONDS = 3600

    def __init__(self, kernel, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._kernel = kernel
        self._tokens: dict[str, RunToken] = {}
        self._resources: dict[tuple[str, str], tuple[McpResourceSpec, ...]] = {}
        self._clock = clock

    def register_resources(
        self,
        tenant_id: str,
        adapter_id: str,
        specs: tuple[McpResourceSpec, ...] | list[McpResourceSpec],
    ) -> None:
        """Register adapter-declared resource mappings as data."""
        self._resources[(tenant_id, adapter_id)] = tuple(specs)

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _lookup(self, token: str | None) -> RunToken | None:
        if not token:
            return None
        key = self._token_key(token)
        record = self._tokens.get(key)
        if record is not None and record.expires_at is not None:
            if self._clock() >= record.expires_at:
                self._tokens.pop(key, None)
                return None
        return record

    # --- token lifecycle (issued by the fleet per run) ---
    def issue_run_token(
        self, tenant_id: str, grants: GrantSet, *, run_id=None, actor="ephemeral",
        skills=(), workspace_id=None, on_behalf_of=None, extra=None, ttl_seconds=300,
    ) -> str:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= self.MAX_RUN_TOKEN_TTL_SECONDS
        ):
            raise ValueError("MCP run-token TTL must be between 1 and 3600 seconds")
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._tokens[self._token_key(token)] = RunToken(
            lease_id=uuid.uuid4().hex, tenant_id=tenant_id, grants=grants, run_id=run_id,
            actor=actor, skills=tuple(skills), workspace_id=workspace_id,
            on_behalf_of=on_behalf_of, extra=dict(extra or {}),
            issued_at=now, expires_at=now + timedelta(seconds=ttl_seconds),
        )
        return token

    def revoke(self, token: str) -> None:
        self._tokens.pop(self._token_key(token), None)

    def is_run_token(self, token: str | None) -> bool:
        """Whether ``token`` is a live run-scoped token (vs a user bearer/PAT)."""
        return self._lookup(token) is not None

    def lookup_run_token(self, token: str | None) -> RunToken | None:
        """Public read of a live run token record (or None), for non-JSON-RPC
        surfaces that authenticate over the SAME run-token seam - the channel
        gateway's outbox links (decision 0003 Phase 2). Same hash-keyed,
        TTL-bound, revocable registry; no second token scheme."""
        return self._lookup(token)

    def _context(
        self, rt: RunToken, *, ip_address: str | None = None, user_agent: str | None = None
    ) -> InvocationContext:
        # D2: the MCP caller's org/workspace + ip/ua populate the SAME context
        # fields a human action carries, so an MCP-initiated audit row is enriched
        # to the same depth (the chokepoint stamps them onto the audit row).
        return InvocationContext(
            tenant_id=rt.tenant_id, grants=rt.grants, actor=rt.actor,
            actor_tier="ephemeral", run_id=rt.run_id, skills_loaded=rt.skills,
            workspace_id=rt.workspace_id, ip_address=ip_address, user_agent=user_agent,
            on_behalf_of=rt.on_behalf_of, extra=dict(rt.extra),
        )

    # --- JSON-RPC dispatch ---
    async def handle(
        self, token: str | None, request: dict, *,
        ip_address: str | None = None, user_agent: str | None = None,
    ) -> dict:
        rt = self._lookup(token)
        if rt is None:
            # D3: a bad/expired MCP run token is a security signal (mcp_auth_failure)
            # on the distinct stream. Fail-safe recording; the -32001 below governs.
            sec = getattr(self._kernel, "security", None)
            if sec is not None:
                # Tenant is unknown for an invalid token; record under a reserved
                # marker so the signal is captured without inventing a tenant.
                await sec.record(
                    "_unauthenticated", SecurityEventType.MCP_AUTH_FAILURE,
                    "invalid_or_expired_run_token",
                    ip_address=ip_address, user_agent=user_agent,
                    detail={"method": str(request.get("method") or "")},
                )
            return _err(request.get("id"), -32001, "invalid or expired run token")
        return await self._dispatch(rt, request, ip_address=ip_address, user_agent=user_agent)

    async def handle_user(
        self, principal, request: dict, *,
        ip_address: str | None = None, user_agent: str | None = None,
    ) -> dict:
        """User-authenticated MCP (US-HEAD-02, SEC-37): a transient connection
        scoped to the user's effective grants (PAT scope ∩ owner grants, or the
        user's role-derived grants). Every call runs the same chokepoint as the
        site - no reduced-security headless path - and is audited as the user, now
        with the caller's org/workspace + ip/ua at the same depth (D2)."""
        rt = RunToken(
            lease_id="user-request", tenant_id=principal.tenant_id, grants=principal.grants,
            run_id=None, actor=principal.subject, skills=(),
            workspace_id=getattr(principal, "active_workspace_id", None),
            on_behalf_of=getattr(principal, "on_behalf_of", None),
            extra={
                "principal_role": getattr(principal, "role", ""),
                "principal_scope": dict(getattr(principal, "scope", {}) or {}),
            },
        )
        # Prefer explicit ip/ua from the route; fall back to what the door stamped
        # on the principal (the principal resolver sets these from the request).
        ip = ip_address or getattr(principal, "ip_address", None)
        ua = user_agent or getattr(principal, "user_agent", None)
        return await self._dispatch(rt, request, ip_address=ip, user_agent=ua)

    async def _dispatch(
        self, rt: "RunToken", request: dict, *,
        ip_address: str | None = None, user_agent: str | None = None,
    ) -> dict:
        # RLS-live: bind the run/user tenant before any RLS-scoped read below
        # (list_verbs, get_tenant_permissions, get_verb). The run-token path never
        # passes through the HTTP principal() binder, so without this the _RlsPool
        # would see a null GUC and fail closed on every tool list/call. No-op for
        # the in-memory store and when RLS is off.
        from boltrig.store.postgres import set_current_tenant

        set_current_tenant(rt.tenant_id)
        rid = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            capabilities: dict = {"tools": {"listChanged": False}}
            if self._resource_specs(rt.tenant_id):
                capabilities["resources"] = {"listChanged": False}
            return _ok(rid, {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": capabilities,
                "serverInfo": {"name": "boltrig-kernel", "version": "0.1.0"},
            })
        if method in ("notifications/initialized", "ping"):
            return _ok(rid, {})
        if method == "tools/list":
            return _ok(rid, {"tools": await self._list_tools(rt)})
        if method == "tools/call":
            return _ok(rid, await self._call_tool(
                rt, params, ip_address=ip_address, user_agent=user_agent
            ))
        if method == "resources/list":
            try:
                resources = await self._list_resources(
                    rt, ip_address=ip_address, user_agent=user_agent
                )
            except BoltrigError as exc:
                return _err(rid, -32002, exc.reason)
            return _ok(rid, {"resources": resources})
        if method == "resources/read":
            try:
                contents = await self._read_resource(
                    rt,
                    str(params.get("uri") or ""),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            except (BoltrigError, ValueError):
                return _err(rid, -32002, "resource not found or not permitted")
            return _ok(rid, {"contents": contents})
        return _err(rid, -32601, f"method not found: {method}")

    def _resource_specs(self, tenant_id: str) -> tuple[McpResourceSpec, ...]:
        return tuple(
            spec
            for (tenant, _adapter), specs in self._resources.items()
            if tenant == tenant_id
            for spec in specs
        )

    async def _visible_resource_specs(
        self, rt: RunToken
    ) -> tuple[McpResourceSpec, ...]:
        permissions = await self._kernel.store.get_tenant_permissions(rt.tenant_id)
        return tuple(
            spec
            for spec in self._resource_specs(rt.tenant_id)
            if permissions.grants.permits(spec.list_verb)
            and permissions.grants.permits(spec.read_verb)
            and rt.grants.permits(spec.list_verb)
            and rt.grants.permits(spec.read_verb)
        )

    async def _invoke_resource_verb(
        self,
        rt: RunToken,
        verb: str,
        params: dict,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> dict:
        definition = await self._kernel.store.get_verb(rt.tenant_id, verb)
        if definition is None:
            raise ValueError("resource verb is unavailable")
        return await self._kernel.invoke(
            definition.noun_id,
            verb,
            params,
            self._context(rt, ip_address=ip_address, user_agent=user_agent),
        )

    async def _list_resources(
        self,
        rt: RunToken,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> list[dict]:
        resources: list[dict] = []
        for spec in await self._visible_resource_specs(rt):
            output = await self._invoke_resource_verb(
                rt,
                spec.list_verb,
                {"limit": 100},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            rows = output.get(spec.collection_key) or []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or not row.get(spec.id_key):
                    continue
                resource = {
                    "uri": spec.uri_prefix + quote(str(row[spec.id_key]), safe=""),
                    "name": str(row.get(spec.name_key) or row[spec.id_key]),
                }
                description = row.get(spec.description_key)
                if description:
                    resource["description"] = str(description)
                resources.append(resource)
        return resources

    async def _read_resource(
        self,
        rt: RunToken,
        uri: str,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> list[dict]:
        for spec in await self._visible_resource_specs(rt):
            if not uri.startswith(spec.uri_prefix):
                continue
            resource_id = unquote(uri[len(spec.uri_prefix):])
            if not resource_id or "/" in resource_id:
                break
            output = await self._invoke_resource_verb(
                rt,
                spec.read_verb,
                {spec.read_id_param: resource_id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            blob = output.get(spec.blob_key)
            media_type = output.get(spec.media_type_key)
            if not isinstance(blob, str) or not isinstance(media_type, str):
                break
            return [{"uri": uri, "mimeType": media_type, "blob": blob}]
        raise ValueError("resource not found")

    async def _list_tools(self, rt: RunToken) -> list[dict]:
        """Granted-only: tenant ceiling ∩ the run's grants (SEC-23, FR-MCP-02)."""
        perms = await self._kernel.store.get_tenant_permissions(rt.tenant_id)
        verbs = await self._kernel.store.list_verbs(rt.tenant_id)
        return [
            {"name": v.id, "description": v.description or v.id, "inputSchema": v.input_schema}
            for v in verbs
            if perms.grants.permits(v.id) and rt.grants.permits(v.id)
        ]

    async def _call_tool(
        self, rt: RunToken, params: dict, *,
        ip_address: str | None = None, user_agent: str | None = None,
    ) -> dict:
        """Translate to ``kernel.invoke`` - the unchanged chokepoint (SEC-26)."""
        name = params.get("name", "")
        args = params.get("arguments") or {}
        verb_def = await self._kernel.store.get_verb(rt.tenant_id, name)
        noun = verb_def.noun_id if verb_def else (name.split(".")[0] if name else "")
        ctx = self._context(rt, ip_address=ip_address, user_agent=user_agent)
        try:
            output = await self._kernel.invoke(
                noun, name, args, ctx, approval_id=params.get("approval_id")
            )
            return {
                "content": [{"type": "text", "text": json.dumps(output)}],
                "isError": False,
                "_boltrig": {"status": "ok", "output": output},
            }
        except PendingHuman as e:
            return {
                "content": [{"type": "text", "text": f"pending approval: {e.hitl_request_id}"}],
                "isError": True,
                "_boltrig": {"status": "pending_human", "hitl_request_id": e.hitl_request_id},
            }
        except DegradedMode as e:
            return {
                "content": [{"type": "text", "text": "degraded"}],
                "isError": True,
                "_boltrig": {"status": "degraded", "output": e.output},
            }
        except BoltrigError as e:
            status = "denied" if e.status_code == 403 else "error"
            return {
                "content": [{"type": "text", "text": e.reason}],
                "isError": True,
                "_boltrig": {"status": status, "reason": e.reason},
            }
