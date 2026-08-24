# Risks harvested from SPEC-02-kernel-http-surface.md

RISK: 68 of the 161 state-changing routes never reach the dispatcher, against a
doctrine that names one chokepoint and forbids side doors
([`AGENTS.md:25`](../../../AGENTS.md) `"Do not add side doors."`).

---

RISK: `POST /v1/ai-keys/activate` provisions a caller's key into the external Bifrost
gateway with no dispatch, no HITL gate, no rate limit and no audit row
([`boltrig/kernel/ai_key_proposal_routes.py:184`](../../../boltrig/kernel/ai_key_proposal_routes.py)
`"await BifrostUserGateway().ensure("`).

---

RISK: `activate_ai_key_config` reads raw key MATERIAL out of the store on an HTTP
route rather than inside the kernel's credential resolution
([`boltrig/kernel/ai_key_proposal_routes.py:172`](../../../boltrig/kernel/ai_key_proposal_routes.py)
`"material = await load_ai_key_material(kernel.store, principal.tenant_id, resolution)"`),
against `"Credentials are resolved inside the kernel"` ([`AGENTS.md:35`](../../../AGENTS.md) `"- Credentials are resolved inside the kernel and NEVER handed"`).

---

RISK: the entire call, device, camera and channel-gateway family writes to the DB with
no verb, no grant check at the chokepoint and no per-verb rate limit (bounded:
`rg -c 'kernel\.invoke\(|k\.invoke\(|dispatch_control_route\('` returns 0 for all ten
modules named in Exception 5).

---

RISK: `POST /v1/me/agent` creates or replaces a personal agent with no RBAC guard and
no audit row, while its sibling DELETE is audited
([`boltrig/kernel/platform_routes/personal.py:27`](../../../boltrig/kernel/platform_routes/personal.py)
`"await k.store.upsert_personal_agent(agent)"`).

---

RISK: the production Host-validation guard compares the whole list to `["*"]`
([`boltrig/kernel/web_security.py:297`](../../../boltrig/kernel/web_security.py)
`"if hosts == [\"*\"] and _production_signal(e):"`), so `BOLTRIG_ALLOWED_HOSTS="*,app.example.com"`
passes the fatal check while still handing a wildcard entry to `TrustedHostMiddleware`.

---

RISK: the request-body cap is only applied to POST, PUT and PATCH when no
Content-Length is present ([`boltrig/kernel/web_security.py:221`](../../../boltrig/kernel/web_security.py)
`"_BODY_METHODS = frozenset({\"POST\", \"PUT\", \"PATCH\"})"`), so a chunked DELETE body
is never counted; the app has 19 DELETE routes.

---

RISK: the per-path 25 MiB cap is a prefix match on `scope["path"]`
([`boltrig/kernel/web_security.py:225`](../../../boltrig/kernel/web_security.py)
`"if path.startswith(prefix):"`), so any URL beginning `/v1/knowledge/uploads/`,
including one that resolves to a 404, buffers up to 25 MiB in memory before the router
sees it.

---

RISK: the CORS `allow_headers` allowlist omits two headers the kernel actually reads,
`idempotency-key` ([`boltrig/kernel/control_routes.py:75`](../../../boltrig/kernel/control_routes.py)
`"request.headers.get(\"idempotency-key\")"`) and `x-boltrig-workspace`
([`boltrig/kernel/bearer_principal.py:60`](../../../boltrig/kernel/bearer_principal.py) `"requested_workspace_id=request.headers.get(WORKSPACE_HEADER)"`),
so a cross-origin browser client cannot send an idempotency key or select a workspace,
which is exactly the embedded-console case `bearer_principal.py` was written for
([`:11`](../../../boltrig/kernel/bearer_principal.py) `"An embedded console needs to say which workspace it is showing"`).

---

RISK: `/healthz` is unauthenticated and discloses tenant ids and adapter names in its
response body ([`boltrig/kernel/health_routes.py:37`](../../../boltrig/kernel/health_routes.py)
`"f\"{tenant}/{adapter}\": value"`).

---

RISK: cookie deletion at logout is written with `path="/"`
([`boltrig/api/auth_routes.py:544`](../../../boltrig/api/auth_routes.py)
`"resp.delete_cookie(SESSION_COOKIE, path=\"/\")"`) and then rewritten by
`MountPathCookieMiddleware` using the CURRENT request's forwarded prefix
([`boltrig/kernel/web_security.py:159`](../../../boltrig/kernel/web_security.py)
`"scoped = [scope_set_cookie(c, prefix) for c in cookies]"`); if the prefix or its
trust flag changes between login and logout, the delete targets a different Path and
the live session cookie survives in the browser.

---

RISK: `MountPathCookieMiddleware` and `SecurityHeadersMiddleware` are
`BaseHTTPMiddleware` subclasses wrapping SSE routes; the ASGI-level body cap was
explicitly rewritten to avoid blocking SSE GETs
([`boltrig/kernel/web_security.py:248`](../../../boltrig/kernel/web_security.py)
`"Methods that do not carry a body can skip the buffering path."`), but no equivalent note or
test exists for the two `BaseHTTPMiddleware` layers that stream every event through a
queue.

---

RISK: 81 routes enforce authorship in the transport with `require_author(p)`, which
contradicts this area's own stated design that no policy lives here
([`boltrig/kernel/app.py:4`](../../../boltrig/kernel/app.py) `"no policy lives in this module"`,
against [`boltrig/kernel/platform_routes/_shared.py:17`](../../../boltrig/kernel/platform_routes/_shared.py)
`"def require_author(p) -> None:"`). For the six routes that both call it and never
dispatch, it is the ONLY authorisation.

---

RISK: 17 state-changing routes neither dispatch nor write an audit row, including
`DELETE /v1/trajectory/{run_id}` (a verbatim record purge, deliberately available to
any reader per [`boltrig/kernel/trajectory_routes.py:104`](../../../boltrig/kernel/trajectory_routes.py)
`"Deliberately available to whoever can read it"`) and `PUT /v1/conversations/{conversation_id}/queue`.

---

RISK: `WEB-02/03/05/06`, `RES-01`, `US-HEAD-02`, `SEC-02`, `K-3` and `IAM-09` are cited
in this area's source as if they were invariants but are not declared in
`tests/invariants.yaml`, so the ratchet cannot notice their removal.

---

RISK: the mount-path cookie scoping, a security control with its own 11-test file, is
bound to no invariant id (`rg -c 'pytest.mark.invariant' tests/security/test_mount_path_cookie_scope.py`
returns 0).

---

RISK: an invalid MCP run token yields HTTP 200 with a JSON-RPC error rather than 401
([`boltrig/kernel/app.py:401`](../../../boltrig/kernel/app.py) `"result = await k.mcp.handle(run_token, body"`,
[`boltrig/kernel/mcp.py:177`](../../../boltrig/kernel/mcp.py) `"return _err(request.get(\"id\"), -32001, \"invalid or expired run"`), so an HTTP-level
monitor or WAF sees authentication failures as successes.

---

RISK: `POST /v1/skills/{skill_id}/test-spawn` is registered twice, once plain and once
with `{skill_id:path}` ([`boltrig/kernel/platform_routes/skill_write_routes.py:88`](../../../boltrig/kernel/platform_routes/skill_write_routes.py) `"async def test_spawn("`
and [`:93`](../../../boltrig/kernel/platform_routes/skill_write_routes.py)); the
`:path` converter matches slashes, so the two overlap and only the first-registered
wins for a single-segment id.

---

RISK: `_ensure_control_plane` will BUILD and register a control-plane adapter at
request time if none exists ([`boltrig/kernel/control_routes.py:30`](../../../boltrig/kernel/control_routes.py)
`"from boltrig.config.control_plane import build_control_plane_adapter"`), so a
misconfigured production composition silently self-heals into a working write path
instead of failing loudly.

---

RISK: `SameSite` drops to `None` for any origin that is BOTH in
`DESKTOP_WEBVIEW_ORIGINS` and in `BOLTRIG_CORS_ORIGINS`
([`boltrig/api/desktop_session_auth.py:30`](../../../boltrig/api/desktop_session_auth.py)
`"return origin in DESKTOP_WEBVIEW_ORIGINS and origin in configured"`), and that env
var is read directly from `os.environ` inside the predicate rather than from the
config layer, so it can drift from what `install_security` was given.
