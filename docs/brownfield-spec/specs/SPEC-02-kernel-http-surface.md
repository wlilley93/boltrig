---
area: 02 The kernel HTTP surface
id-block: BT-REQ-0200 to BT-REQ-0299
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: spec-02-kernel-http-surface
date: 2026-08-24
---

# SPEC-02: The kernel HTTP surface

## Bound of this reading

The inventory below is **exhaustive, not sampled**, for route REGISTRATION. Every
route was extracted by parsing the AST of all 114 `.py` files under
`boltrig/kernel/` (including the 41-module `platform_routes/` package) and
collecting two registration forms:

- decorator form: `@app.<method>("<literal path>")`, 246 occurrences;
- programmatic form: `app.add_api_route("<path>", endpoint, methods=[...])`,
  42 call sites, four of which sit inside `for` loops over a literal tuple and
  expand to ten routes rather than four.

Total: **294 routes on the kernel ASGI app**. A third form, `include_router` or
`app.mount`, does not occur (bounded: `rg -n 'add_api_route|include_router|app.mount'
boltrig/kernel/ -g '*.py'`, 2026-08-24, pinned tree, 42 hits, all `add_api_route`).
Routes whose path is not a string literal do not occur outside the four loops named
above.

The same `create_app` also registers 12 routes owned by `boltrig/api/` (login,
logout, refresh, 2FA, invite, password, CSRF). Those are **out of this area** and
appear here only where the kernel surface depends on them, so the app's true total
is 306.

**Body depth is sampled, not exhaustive.** Every route's handler was read at the
AST level (signature, decorator kwargs, transitive same-module call set, store
call names, dispatcher markers, audit markers). Handler PROSE was read in full for
`app.py`, `web_security.py`, `bearer_principal.py`, `control_routes.py`,
`app_bodies.py`, `health_routes.py`, `desktop_routes.py`, `channel_inbound_routes.py`,
`workflow_trigger_public_routes.py`, the four gateway modules, `conversation_account_routes.py`,
`approval_posture_routes.py`, `familiar_phenotype_routes.py`, `ai_key_routes.py`,
`platform_routes/personal.py`, `platform_routes/memory.py`, `platform_routes/admin.py`,
`platform_routes/eval_routes.py`, `platform_routes/integration_setup.py`,
`memory_routes.py` / `memory_mutation_routes.py` / `memory_read_routes.py`,
`access_routes.py` (context and token blocks), `trajectory_routes.py`, and
`conversation_live_routes.py`. Where a claim rests on a body not read in prose it
is tagged UNCERTAIN.

---

## 2. Purpose

The kernel HTTP surface is the ASGI front door of the Boltrig kernel: one FastAPI
application, built by `create_app`, that authenticates a caller into a `Principal`
and hands typed requests to the kernel, the fleet, or the store. Its stated design
is that it is a dumb mouth over a smart engine, holding no policy of its own
([`boltrig/kernel/app.py:1`](../../../boltrig/kernel/app.py) `"a thin transport over the engine"`,
and `"Multiple front doors ... are dumb mouths over one smart engine: no policy lives in this module"`).
A second module, `web_security.py`, wraps that application in four pieces of edge
hardening (security headers, CORS allowlist, Host validation, request-body cap)
plus a cookie-path rewriter.

## 3. Boundaries

**Owns.** The ASGI app object and its middleware stack; the `Principal` dataclass
and the `PrincipalResolver` protocol; the canonical error envelope; the typed
request bodies in `app_bodies.py`; the registration graph of all 294 routes; the
`dispatch_control_route` compatibility helper.

**Must not touch.** `kernel/` may not import `fleet/` or sidecars
([`AGENTS.md:41`](../../../AGENTS.md) `"Respect the import boundary"`).
The surface honours this by INJECTION rather than import: the conversational
service arrives as `chat_service` or `chat_factory` and is read off
`request.app.state.chat` ([`boltrig/kernel/app.py:411`](../../../boltrig/kernel/app.py)
`"chat_svc = getattr(request.app.state, \"chat\", None)"`); the spawner likewise
([`boltrig/kernel/app.py:532`](../../../boltrig/kernel/app.py) `"spawner_fn = getattr(request.app.state, \"spawner\", None)"`);
platform services arrive as a dict on `app.state.platform`
([`boltrig/kernel/platform_routes/_shared.py:47`](../../../boltrig/kernel/platform_routes/_shared.py)
`"return getattr(request.app.state, \"platform\", {}) or {}"`).

**Import inversion that does exist.** The identity layer imports the kernel app,
not the other way round ([`boltrig/identity/sessions.py:26`](../../../boltrig/identity/sessions.py)
`"from boltrig.kernel.app import Principal, PrincipalResolver"`). This forces two
lazy imports inside `web_security.py` to avoid a cycle
([`boltrig/kernel/web_security.py:66`](../../../boltrig/kernel/web_security.py)
`"boltrig.config pulls in identity, which imports kernel.app"`).

**Forbidden by doctrine, and violated in places.** `AGENTS.md` states one
chokepoint and forbids side doors ([`AGENTS.md:21`](../../../AGENTS.md)
`"ONE chokepoint. Every external action goes through the kernel dispatcher"`, and
`"Do not add side doors."`).
Section 11 records where the surface writes to the DB and to an external gateway
without a verb.

## 4. Objects and contracts

### 4.1 `Principal`

The authenticated caller, built ONLY by a resolver, never from a request body.

| field | type | default | source |
| --- | --- | --- | --- |
| `tenant_id` | `str` | required | resolver (the ACTIVE org for a session) |
| `subject` | `str` | required | resolver |
| `grants` | `GrantSet` | empty | resolver, already narrowed |
| `role` | `str` | `"agent"` | resolver |
| `actor_tier` | `str` | `"ephemeral"` | resolver |
| `on_behalf_of` | `str \| None` | `None` | resolver |
| `scope` | `dict` | `{}` | resolver, visibility scope (US-IAM-02) |
| `active_workspace_id` | `str \| None` | `None` | resolver, re-authorized every request |
| `ip_address` | `str \| None` | `None` | stamped at the door from the request |
| `user_agent` | `str \| None` | `None` | stamped at the door from the request |
| `credential_kind` | `str` | `"machine"` | resolver; HOW they authenticated |

Cited: [`boltrig/kernel/app.py:40`](../../../boltrig/kernel/app.py) `"class Principal:"` through
[`:66`](../../../boltrig/kernel/app.py) `"credential_kind: str = \"machine\""`. The default
of `credential_kind` is deliberately the least-privileged value: `"Defaults to \"machine\" so an unlabelled resolver is refused, never admitted."`
The distinction between `actor_tier` (authority) and `credential_kind` (how you got
in) is load-bearing: [`boltrig/kernel/app.py:62`](../../../boltrig/kernel/app.py)
`"The two are not the same question and conflating"`.

`Principal.context(...)` is the ONLY constructor of an `InvocationContext` from the
HTTP surface ([`boltrig/kernel/app.py:68`](../../../boltrig/kernel/app.py) `"def context("`).
It carries a three-layer merge with a fixed precedence: caller `extra` (filtered),
then `trusted_extra` (server-side derivers), then the resolver-owned role and scope
last ([`boltrig/kernel/app.py:82`](../../../boltrig/kernel/app.py) `"stamped_extra = {"`).

### 4.2 `RESERVED_CONTEXT_KEYS`

A frozenset of eight keys silently dropped from any caller-supplied context:
`principal_role`, `principal_scope`, `approved_by`, `approval_request_id`,
`approval_request_fingerprint`, `approval_resource_context`, `knowledge_scopes`,
`memory_scopes` ([`boltrig/kernel/app.py:113`](../../../boltrig/kernel/app.py)
`"RESERVED_CONTEXT_KEYS = frozenset("`). The comment states the reason:
`"a request body can never seed kernel-trusted authority"`.

### 4.3 The canonical error envelope

One shape for every kernel error on every transport:
`{"status": "denied"|"error", "reason": <str>}`, where 403 alone maps to `denied`
([`boltrig/kernel/app.py:138`](../../../boltrig/kernel/app.py)
`"body = {\"status\": \"denied\" if e.status_code == 403 else \"error\", \"reason\": e.reason}"`).
A `SchemaValidationError` may widen the OUTWARD body with `caller_detail()` while
its audit detail stays value-free ([`boltrig/kernel/app.py:142`](../../../boltrig/kernel/app.py)
`"caller = getattr(e, \"caller_detail\", None)"`). It is installed as a single
FastAPI exception handler ([`boltrig/kernel/app.py:303`](../../../boltrig/kernel/app.py)
`"@app.exception_handler(BoltrigError)"`), which is why most routes have no try/except.

Three status codes escape the envelope by design and are returned by routes directly:
`202 {"status":"pending_human","hitl_request_id":...}`, `503 {"status":"degraded","output":...}`
([`boltrig/kernel/app.py:366`](../../../boltrig/kernel/app.py) `"except PendingHuman as e:"`),
and the MCP 202-with-empty-body for a JSON-RPC notification
([`boltrig/kernel/app.py:158`](../../../boltrig/kernel/app.py) `"if isinstance(body, dict) and body.get(\"id\") is None:"`).

### 4.4 Request bodies (`app_bodies.py`), the public contract

- `InvokeBody`: `noun`, `verb`, `params`, `context`, `idempotency_key`, `origin`,
  `approval_id` ([`boltrig/kernel/app_bodies.py:18`](../../../boltrig/kernel/app_bodies.py) `"class InvokeBody(BaseModel):"`).
- `SpawnBody`: `task`, `skills`, `prefer`, `context` ([`:35`](../../../boltrig/kernel/app_bodies.py) `"class SpawnBody(BaseModel):"`).
- `RespondBody`: `decision`, `notes` ([`:42`](../../../boltrig/kernel/app_bodies.py) `"class RespondBody(BaseModel):"`).
- `ChatBody`: 12 fields including a regex-pinned `agent_address`
  (`^[a-z0-9][a-z0-9_-]{0,62}$`, [`:58`](../../../boltrig/kernel/app_bodies.py)), an
  `on_behalf_bearer` passthrough explicitly documented as NOT an identity override
  ([`:69`](../../../boltrig/kernel/app_bodies.py) `"This is a CALLER-supplied downstream credential, NOT an identity override"`),
  and an opaque `model_choice_id` validated through `opaque_model_choice_id`
  ([`:122`](../../../boltrig/kernel/app_bodies.py) `"def _valid_model_choice_id"`).

Every other route on the surface takes an untyped `body: dict`. Bounded count:
of the 161 non-GET routes, only 4 (`/v1/invoke`, `/v1/spawn`, `/v1/chat`,
`/v1/hitl/{request_id}/respond`) bind a Pydantic model; the rest validate by hand
inside the handler.

### 4.5 Depth from spawn bodies

`_depth_from` clamps a caller-supplied depth to a non-negative int and never raises
([`boltrig/kernel/app.py:208`](../../../boltrig/kernel/app.py)
`"Caller-supplied spawn depth, clamped: garbage is 0"`), so a body cannot
reset the runaway-tree budget checked as `depth + 1 > max_depth`.

### 4.6 ROUTE INVENTORY

294 routes. Columns: HTTP method; path; the line of the registration in the module
named by the sub-heading; the authentication mechanism; whether the handler reaches
the dispatcher (`dispatch` = the handler or a same-module helper it calls reaches
`kernel.invoke(...)` or `dispatch_control_route(...)`; `store/service` = a
state-changing route that does NOT; `read` = a GET); and any RBAC guard the handler
itself performs.

Authentication values:

- `principal` (267 routes): the `principal` dependency defined at
  [`boltrig/kernel/app.py:315`](../../../boltrig/kernel/app.py) `"async def principal(request: Request)"`,
  which delegates to `resolve_principal` (a PAT bearer, else the configured resolver).
- `run-token` (9): a channel-gateway MCP run token in `x-boltrig-mcp-token`
  ([`boltrig/kernel/channel_gateway_auth.py:11`](../../../boltrig/kernel/channel_gateway_auth.py) `"def gateway_run_token"`).
- `device-session` (11): a scoped device session bearer
  ([`boltrig/kernel/device_route_support.py`](../../../boltrig/kernel/device_route_support.py) `"async def authenticate_device"`).
- `enrollment-code` (1): a one-shot scoped enrollment token in the body.
- `hmac-sig` (1): a per-channel HMAC over the raw wire bytes.
- `trigger-secret` (1): a constant-time digest compare against a stored trigger secret.
- `none` (3): unauthenticated.
- `run-token OR principal` (1): `/v1/mcp` branches on a header.


#### `boltrig/kernel/access_routes.py` (18)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/hitl/{question_id}/answer` | 211 | principal | store/service | - |
| POST | `/v1/runs/{run_id}/cancel` | 252 | principal | store/service | visible_work_item_by_run |
| GET | `/v1/me/tokens` | 281 | principal | read | - |
| POST | `/v1/me/tokens` | 286 | principal | store/service | - |
| DELETE | `/v1/me/tokens/{token_id}` | 311 | principal | store/service | - |
| GET | `/v1/me/connections` | 326 | principal | read | - |
| GET | `/v1/me/sessions` | 356 | principal | read | - |
| DELETE | `/v1/me/sessions/{session_id}` | 379 | principal | store/service | - |
| POST | `/v1/me/active-context` | 402 | principal | store/service | - |
| POST | `/v1/me/active-org` | 450 | principal | store/service | - |
| GET | `/v1/admin/users` | 507 | principal | read | _require_admin |
| PATCH | `/v1/admin/users/{user_id}` | 513 | principal | dispatch | _require_admin |
| GET | `/v1/admin/invitations` | 538 | principal | read | _require_admin |
| POST | `/v1/admin/invitations` | 562 | principal | dispatch | _authz_manage_workspace,_require_admin |
| DELETE | `/v1/admin/invitations/{invite_id}` | 609 | principal | dispatch | _require_admin |
| GET | `/v1/orgs/current` | 629 | principal | read | - |
| PATCH | `/v1/orgs/current` | 642 | principal | dispatch | _require_admin |
| GET | `/v1/orgs/current/members` | 665 | principal | read | - |

#### `boltrig/kernel/account_profile_routes.py` (6)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| PATCH | `/v1/me/profile` | 33 | principal | store/service | - |
| GET | `/v1/me/settings` | 51 | principal | read | - |
| PUT | `/v1/me/settings` | 78 | principal | store/service | - |
| GET | `/v1/me/activity` | 122 | principal | read | - |
| GET | `/v1/me/export` | 152 | principal | read | - |
| POST | `/v1/me/conversations/{conversation_id}/messages/{message_id}/regenerate` | 178 | principal | store/service | - |

#### `boltrig/kernel/ai_key_proposal_routes.py` (5)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/ai-keys/proposals` | 218 | principal | read | - |
| GET | `/v1/ai-keys/proposals/{proposal_id}` | 230 | principal | read | - |
| POST | `/v1/ai-keys/proposals/{proposal_id}/finalize` | 301 | principal | dispatch | - |
| POST | `/v1/ai-keys/proposals/{proposal_id}/approve` | 317 | principal | dispatch | - |
| DELETE | `/v1/ai-keys/proposals/{proposal_id}` | 343 | principal | store/service | - |

#### `boltrig/kernel/ai_key_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/ai-keys` | 243 | principal | read | - |
| PUT | `/v1/ai-keys` | 280 | principal | dispatch | - |
| POST | `/v1/ai-keys/activate` | 320 | principal | store/service | - |
| DELETE | `/v1/ai-keys/{level}/{scope_id}` | 349 | principal | dispatch | - |

#### `boltrig/kernel/app.py` (14)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/invoke` | 339 | principal | dispatch | foreign_run_asserted |
| GET | `/v1/invoke/approvals/{request_id}` | 375 | principal | read | - |
| POST | `/v1/mcp` | 385 | run-token OR principal | store/service | - |
| POST | `/v1/chat` | 409 | principal | store/service | - |
| GET | `/v1/conversations` | 463 | principal | read | - |
| GET | `/v1/conversations/search` | 490 | principal | read | - |
| GET | `/v1/capabilities` | 520 | principal | read | - |
| POST | `/v1/spawn` | 528 | principal | store/service | - |
| GET | `/v1/hitl` | 539 | principal | read | - |
| POST | `/v1/hitl/{request_id}/respond` | 545 | principal | store/service | - |
| GET | `/v1/work` | 554 | principal | read | departments_for |
| GET | `/v1/work/{item_id}` | 593 | principal | read | departments_for |
| GET | `/v1/audit/tree/{run_id}` | 635 | principal | read | - |
| GET | `/v1/runs/{run_id}/events` | 648 | principal | read | - |

#### `boltrig/kernel/approval_posture_routes.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/me/approval-posture` | 18 | principal | read | - |
| PUT | `/v1/me/approval-posture` | 23 | principal | store/service | is_interactive_credential |

#### `boltrig/kernel/call_gateway_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/calls/gateway/claim` | 265 | run-token | store/service | - |
| POST | `/v1/calls/gateway/{call_id}/events` | 269 | run-token | store/service | - |
| POST | `/v1/calls/gateway/{call_id}/state` | 274 | run-token | store/service | - |
| GET | `/v1/calls/gateway/{call_id}/hitl/{request_id}` | 279 | run-token | read | - |

#### `boltrig/kernel/call_routes.py` (9)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/calls` | 301 | principal | store/service | - |
| GET | `/v1/calls` | 305 | principal | read | - |
| GET | `/v1/calls/current` | 309 | principal | read | - |
| GET | `/v1/calls/{call_id}` | 313 | principal | read | - |
| GET | `/v1/calls/{call_id}/events` | 317 | principal | read | - |
| GET | `/v1/calls/{call_id}/usage` | 321 | principal | read | - |
| POST | `/v1/calls/{call_id}/media-token` | 326 | principal | store/service | - |
| POST | `/v1/calls/{call_id}/reopen` | 331 | principal | store/service | - |
| POST | `/v1/calls/{call_id}/end` | 336 | principal | store/service | - |

#### `boltrig/kernel/camera_agent_routes.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/device-agent/{device_id}/camera-bindings` | 367 | device-session | store/service | - |
| GET | `/v1/device-agent/{device_id}/camera-bindings` | 371 | device-session | read | - |
| GET | `/v1/device-agent/{device_id}/camera-leases` | 375 | device-session | read | - |
| GET | `/v1/device-agent/{device_id}/sensing-config` | 379 | device-session | read | - |
| POST | `/v1/device-agent/{device_id}/sensing-enrollment` | 384 | device-session | store/service | - |
| POST | `/v1/device-agent/{device_id}/camera-leases/{lease_id}/claim` | 390 | device-session | store/service | - |
| POST | `/v1/device-agent/{device_id}/camera-leases/{lease_id}/receipt` | 390 | device-session | store/service | - |

#### `boltrig/kernel/channel_gateway_outbox_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/channels/gateway/outbox/claim` | 131 | run-token | store/service | - |
| POST | `/v1/channels/gateway/outbox/{message_id}/ack` | 137 | run-token | store/service | - |
| POST | `/v1/channels/gateway/outbox/{message_id}/fail` | 143 | run-token | store/service | - |

#### `boltrig/kernel/channel_gateway_reconcile_routes.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/channels/gateway/reconcile` | 165 | run-token | read | - |
| POST | `/v1/channels/gateway/heartbeat` | 171 | run-token | store/service | - |

#### `boltrig/kernel/channel_gateway_session_routes.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/channels/gateway/session` | 129 | principal | store/service | - |

#### `boltrig/kernel/channel_inbound_routes.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/channels/{channel_id}/inbound` | 223 | hmac-sig | store/service | - |

#### `boltrig/kernel/channel_inventory_routes.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/channels` | 190 | principal | read | - |
| GET | `/v1/channels/{channel_id}/deliveries` | 196 | principal | read | - |

#### `boltrig/kernel/channel_routes.py` (9)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/channels` | 397 | principal | dispatch | - |
| PATCH | `/v1/channels/{channel_id}` | 425 | principal | dispatch | - |
| DELETE | `/v1/channels/{channel_id}` | 442 | principal | dispatch | - |
| POST | `/v1/channels/{channel_id}/deliveries/{message_id}/retry` | 458 | principal | dispatch | - |
| POST | `/v1/channels/{channel_id}/pair` | 493 | principal | dispatch | - |
| GET | `/v1/channels/{channel_id}/pair-finalizations` | 534 | principal | read | - |
| POST | `/v1/channels/{channel_id}/bindings` | 558 | principal | dispatch | - |
| GET | `/v1/channels/{channel_id}/bindings` | 591 | principal | read | - |
| DELETE | `/v1/channels/{channel_id}/bindings/{binding_id}` | 603 | principal | dispatch | - |

#### `boltrig/kernel/conversation_account_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| DELETE | `/v1/me/conversations/{conversation_id}` | 181 | principal | store/service | - |
| POST | `/v1/me/conversations/{conversation_id}/restore` | 185 | principal | store/service | - |
| PATCH | `/v1/me/conversations/{conversation_id}` | 189 | principal | store/service | - |
| PATCH | `/v1/me/conversations/{conversation_id}/project` | 193 | principal | store/service | - |

#### `boltrig/kernel/conversation_live_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| PUT | `/v1/conversations/{conversation_id}/queue` | 52 | principal | store/service | - |
| GET | `/v1/chat/config` | 159 | principal | read | - |
| GET | `/v1/conversations/{conversation_id}` | 167 | principal | read | - |
| GET | `/v1/conversations/{conversation_id}/events` | 174 | principal | read | - |

#### `boltrig/kernel/desktop_routes.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/hands/commands` | 52 | principal | read | - |
| POST | `/v1/hands/commands/{cmd_id}/receipt` | 66 | principal | store/service | - |

#### `boltrig/kernel/device_agent_routes.py` (5)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/device-agent/enrollment/complete` | 206 | enrollment-code | store/service | - |
| GET | `/v1/device-agent/{device_id}/leases` | 210 | device-session | read | - |
| POST | `/v1/device-agent/{device_id}/leases/{lease_id}/claim` | 219 | device-session | store/service | - |
| POST | `/v1/device-agent/{device_id}/leases/{lease_id}/receipt` | 219 | device-session | store/service | - |
| POST | `/v1/device-agent/{device_id}/session/rotate` | 223 | device-session | store/service | - |

#### `boltrig/kernel/device_routes.py` (8)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/devices/enrollment/start` | 234 | principal | store/service | - |
| GET | `/v1/devices` | 239 | principal | read | - |
| GET | `/v1/devices/{device_id}/leases` | 243 | principal | read | - |
| GET | `/v1/devices/{device_id}/camera-bindings` | 248 | principal | read | - |
| GET | `/v1/devices/{device_id}/camera-leases` | 253 | principal | read | - |
| POST | `/v1/devices/{device_id}/roots` | 258 | principal | store/service | - |
| DELETE | `/v1/devices/{device_id}/roots/{root_id}` | 262 | principal | store/service | - |
| DELETE | `/v1/devices/{device_id}` | 267 | principal | store/service | - |

#### `boltrig/kernel/familiar_phenotype_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/familiar/phenotype` | 81 | principal | read | - |
| POST | `/v1/familiar/emotion/reset` | 99 | principal | store/service | - |
| POST | `/v1/familiar/emotion/adopted` | 104 | principal | store/service | - |

#### `boltrig/kernel/federated_search_routes.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/search` | 279 | principal | store/service | - |

#### `boltrig/kernel/health_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/branding` | 23 | none | read | - |
| GET | `/healthz` | 31 | none | read | - |
| GET | `/readyz` | 41 | none | read | - |

#### `boltrig/kernel/memory_mutation_routes.py` (8)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/memory/recall` | 38 | principal | dispatch | - |
| POST | `/v1/memory/propose` | 49 | principal | dispatch | - |
| POST | `/v1/memory/bundle` | 62 | principal | dispatch | - |
| POST | `/v1/memory/candidates/{candidate_id}/review` | 78 | principal | dispatch | - |
| POST | `/v1/memory/remember` | 103 | principal | dispatch | - |
| POST | `/v1/memory/improve` | 110 | principal | dispatch | - |
| POST | `/v1/memory/forget` | 131 | principal | dispatch | - |
| POST | `/v1/memory/ingest` | 146 | principal | dispatch | - |

#### `boltrig/kernel/memory_read_routes.py` (6)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/memory/facts` | 28 | principal | read | - |
| GET | `/v1/memory/facts/{fact_id}` | 41 | principal | read | - |
| GET | `/v1/memory/ingestions` | 49 | principal | read | - |
| GET | `/v1/memory/candidates` | 74 | principal | read | - |
| GET | `/v1/memory/resolve` | 92 | principal | dispatch | - |
| GET | `/v1/memory/timeline` | 109 | principal | read | - |

#### `boltrig/kernel/notification_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/me/notifications` | 74 | principal | read | - |
| PUT | `/v1/me/notifications` | 83 | principal | dispatch | - |
| POST | `/v1/me/notifications/{preference_id}/test` | 94 | principal | dispatch | - |

#### `boltrig/kernel/org_discovery_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/me` | 29 | principal | read | - |
| POST | `/v1/me/permits` | 68 | principal | store/service | permits |
| GET | `/v1/me/orgs` | 73 | principal | read | - |

#### `boltrig/kernel/platform_routes/adapters.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/adapters/generate` | 12 | principal | dispatch | require_author |
| GET | `/v1/adapters/{adapter_id}/source` | 22 | principal | read | require_author |
| POST | `/v1/adapters/{adapter_id}/activate` | 42 | principal | dispatch | require_author |
| POST | `/v1/mcp/servers` | 58 | principal | dispatch | require_author |
| GET | `/v1/adapters` | 70 | principal | read | - |
| POST | `/v1/adapters/{adapter_id}/deactivate` | 80 | principal | dispatch | require_author |
| DELETE | `/v1/adapters/{adapter_id}` | 96 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/addons.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/addons` | 13 | principal | read | - |

#### `boltrig/kernel/platform_routes/admin.py` (6)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/admin/config/{section}` | 12 | principal | read | can_author_route |
| PUT | `/v1/admin/config/{section}` | 31 | principal | dispatch | require_author |
| GET | `/v1/admin/config/{section}/history` | 55 | principal | read | can_author_route |
| POST | `/v1/admin/config/{section}/rollback` | 79 | principal | dispatch | require_author |
| POST | `/v1/admin/config/export` | 101 | principal | store/service | can_author_route |
| GET | `/v1/admin/credentials` | 111 | principal | read | can_author_route |

#### `boltrig/kernel/platform_routes/agent_capabilities.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/agent-capabilities` | 40 | principal | read | require_author |
| POST | `/v1/agent-capabilities/{name}/retire` | 92 | principal | dispatch | require_author |
| POST | `/v1/agent-capabilities/{name}/restore` | 98 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/artifacts.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/artifacts` | 72 | principal | read | - |
| GET | `/v1/artifacts/{artifact_id}` | 95 | principal | read | - |
| GET | `/v1/artifacts/{artifact_id}/download` | 101 | principal | read | - |

#### `boltrig/kernel/platform_routes/audit_search.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/audit/search` | 95 | principal | read | can_author_route,scope_depts |

#### `boltrig/kernel/platform_routes/authored_registry_read_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/nouns` | 12 | principal | read | require_author |
| GET | `/v1/verbs` | 21 | principal | read | require_author |
| GET | `/v1/nouns/{noun_id}` | 35 | principal | read | require_author |
| GET | `/v1/verbs/{verb_id}` | 46 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/authored_registry_write_routes.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/nouns` | 26 | principal | dispatch | require_author |
| POST | `/v1/nouns/{noun_id}/archive` | 36 | principal | dispatch | require_author |
| POST | `/v1/nouns/{noun_id}/restore` | 42 | principal | dispatch | require_author |
| POST | `/v1/verbs` | 50 | principal | dispatch | require_author |
| POST | `/v1/verbs/{verb_id}/archive` | 60 | principal | dispatch | require_author |
| POST | `/v1/verbs/{verb_id}/restore` | 66 | principal | dispatch | require_author |
| POST | `/v1/verbs/{verb_id}/binding` | 72 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/backup_status.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/backup/status` | 19 | principal | read | - |

#### `boltrig/kernel/platform_routes/bifrost_models.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/bifrost/models` | 85 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/birth_profile.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/birth-profile` | 11 | principal | read | - |

#### `boltrig/kernel/platform_routes/budgets.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/budgets` | 39 | principal | read | scope_depts |
| PUT | `/v1/budgets/{scope_type}/{scope_id}` | 53 | principal | dispatch | require_author |
| POST | `/v1/budgets/{scope_type}/{scope_id}/reset` | 65 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/capability_review.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/capability-bindings` | 153 | principal | read | require_author |
| GET | `/v1/capability-catalogue` | 165 | principal | read | require_author |
| GET | `/v1/routing-policies` | 203 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/chat_model_choices.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/chat/model-choices` | 239 | principal | read | - |

#### `boltrig/kernel/platform_routes/console.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/console/overview` | 188 | principal | read | hitl_request_visible,scope_depts |

#### `boltrig/kernel/platform_routes/device_inventory.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/admin/devices` | 72 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/eval_case_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/eval/cases` | 43 | principal | read | require_author |
| POST | `/v1/eval/cases` | 63 | principal | dispatch | require_author |
| POST | `/v1/eval/cases/{case_id}/archive` | 80 | principal | dispatch | require_author |
| POST | `/v1/eval/cases/{case_id}/restore` | 84 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/eval_routes.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/eval/run` | 31 | principal | store/service | require_author |
| GET | `/v1/eval/runs` | 80 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/hitl_policy.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/hitl/policy` | 15 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/integration_setup.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/integrations/{integration_id}/oauth/start` | 148 | principal | store/service | require_author |
| POST | `/v1/integrations/{integration_id}/secrets` | 166 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/integrations.py` (6)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/integrations/catalogue` | 203 | principal | read | permits |
| GET | `/v1/integrations/connections` | 217 | principal | read | permits |
| GET | `/v1/integrations/member-connections` | 265 | principal | read | require_author |
| DELETE | `/v1/integrations/member-connections/{connection_id}` | 285 | principal | dispatch | require_author |
| GET | `/v1/integrations/connections/{connection_id}/health` | 305 | principal | read | - |
| DELETE | `/v1/integrations/connections/{connection_id}` | 343 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/knowledge.py` (11)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/knowledge/uploads` | 95 | principal | dispatch | - |
| PUT | `/v1/knowledge/uploads/{upload_id}` | 99 | principal | dispatch | - |
| POST | `/v1/knowledge/uploads/{upload_id}/commit` | 115 | principal | dispatch | - |
| GET | `/v1/knowledge/assets` | 119 | principal | dispatch | - |
| GET | `/v1/knowledge/assets/{asset_id}` | 125 | principal | dispatch | - |
| GET | `/v1/knowledge/assets/{asset_id}/original` | 129 | principal | dispatch | - |
| POST | `/v1/knowledge/search` | 140 | principal | dispatch | - |
| POST | `/v1/knowledge/context` | 144 | principal | dispatch | - |
| DELETE | `/v1/knowledge/assets/{asset_id}` | 148 | principal | dispatch | - |
| GET | `/v1/knowledge/providers` | 158 | principal | dispatch | - |
| POST | `/v1/knowledge/providers/{provider_id}` | 162 | principal | dispatch | - |

#### `boltrig/kernel/platform_routes/mcp_servers.py` (9)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/mcp/servers` | 223 | principal | read | require_author |
| GET | `/v1/mcp/servers/{server_id}` | 247 | principal | read | require_author |
| POST | `/v1/mcp/servers/{server_id}/probe` | 302 | principal | dispatch | require_author |
| POST | `/v1/mcp/servers/{server_id}/activate` | 308 | principal | dispatch | require_author |
| POST | `/v1/mcp/servers/{server_id}/deactivate` | 314 | principal | dispatch | require_author |
| POST | `/v1/mcp/servers/{server_id}/retire` | 320 | principal | dispatch | require_author |
| POST | `/v1/mcp/servers/{server_id}/restore` | 326 | principal | dispatch | require_author |
| PUT | `/v1/mcp/servers/{server_id}` | 332 | principal | dispatch | require_author |
| DELETE | `/v1/mcp/servers/{server_id}` | 354 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/memory.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/memory/query` | 6 | principal | store/service | - |

#### `boltrig/kernel/platform_routes/model_endpoints.py` (5)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/model-endpoints` | 130 | principal | read | - |
| GET | `/v1/model-endpoints/{endpoint_id}` | 149 | principal | read | require_author |
| GET | `/v1/model-policy` | 181 | principal | read | require_author |
| POST | `/v1/model-endpoints/{endpoint_id}/retire` | 225 | principal | dispatch | require_author |
| POST | `/v1/model-endpoints/{endpoint_id}/restore` | 235 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/model_profiles.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/model-profiles` | 12 | principal | read | - |

#### `boltrig/kernel/platform_routes/named_agents.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/named-agents` | 56 | principal | read | require_author,scope_depts |
| GET | `/v1/named-agents/{address}/inbox` | 65 | principal | read | require_author,scope_depts |

#### `boltrig/kernel/platform_routes/observability.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/cost` | 29 | principal | read | scope_depts |
| GET | `/v1/capabilities/changelog` | 51 | principal | read | can_author_route |
| GET | `/v1/model/telemetry` | 86 | principal | read | scope_depts |
| GET | `/v1/audit/verify` | 106 | principal | read | can_author_route |
| POST | `/v1/audit/export` | 146 | principal | store/service | can_author_route |
| GET | `/v1/runs` | 193 | principal | read | scope_depts |
| GET | `/v1/runs/{run_id}/topology` | 248 | principal | read | - |

#### `boltrig/kernel/platform_routes/permanent_fleet.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/permanent-fleet` | 17 | principal | read | require_author |
| PUT | `/v1/permanent-fleet` | 22 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/personal.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/me/agent` | 19 | principal | store/service | - |
| GET | `/v1/me/agent` | 30 | principal | read | - |
| DELETE | `/v1/me/agent` | 46 | principal | store/service | - |
| POST | `/v1/me/agent/invoke` | 54 | principal | store/service | - |

#### `boltrig/kernel/platform_routes/platform_status.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/platform/status` | 105 | principal | read | can_author_route |

#### `boltrig/kernel/platform_routes/privacy_policy.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/privacy/policy` | 15 | principal | read | - |

#### `boltrig/kernel/platform_routes/run_effects.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/runs/{run_id}/effects` | 149 | principal | read | visible_work_item_by_run |
| POST | `/v1/runs/{run_id}/revert` | 154 | principal | dispatch | visible_work_item_by_run |

#### `boltrig/kernel/platform_routes/skill_read_routes.py` (3)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/skills` | 14 | principal | read | - |
| GET | `/v1/skills/{skill_id}` | 33 | principal | read | require_author |
| GET | `/v1/skills/{skill_id:path}` | 38 | principal | read | require_author |

#### `boltrig/kernel/platform_routes/skill_write_routes.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/skills` | 49 | principal | dispatch | require_author |
| POST | `/v1/skills/{skill_id}/archive` | 61 | principal | dispatch | require_author |
| POST | `/v1/skills/{skill_id}/restore` | 67 | principal | dispatch | require_author |
| POST | `/v1/skills/{skill_id:path}/archive` | 73 | principal | dispatch | require_author |
| POST | `/v1/skills/{skill_id:path}/restore` | 79 | principal | dispatch | require_author |
| POST | `/v1/skills/{skill_id}/test-spawn` | 87 | principal | store/service | require_author |
| POST | `/v1/skills/{skill_id:path}/test-spawn` | 93 | principal | store/service | require_author |

#### `boltrig/kernel/platform_routes/spawn_rules.py` (2)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/spawn-rules` | 60 | principal | read | require_author |
| POST | `/v1/spawn-rules/simulate` | 92 | principal | store/service | require_author |

#### `boltrig/kernel/platform_routes/work.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/work` | 32 | principal | dispatch | require_author |
| PATCH | `/v1/work/{item_id}/assignment` | 38 | principal | dispatch | require_author |
| PATCH | `/v1/work/{item_id}/status` | 46 | principal | dispatch | require_author |
| PATCH | `/v1/work/{item_id}/parent` | 54 | principal | dispatch | require_author |

#### `boltrig/kernel/platform_routes/workflows.py` (13)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/workflows` | 124 | principal | read | - |
| GET | `/v1/workflows/{wf_id}` | 149 | principal | read | - |
| GET | `/v1/workflow-stats` | 167 | principal | read | - |
| GET | `/v1/workflows/{wf_id}/runs` | 171 | principal | read | - |
| GET | `/v1/workflows/{wf_id}/schedule/occurrences` | 195 | principal | read | require_author |
| POST | `/v1/workflows/{wf_id}/schedule/occurrences/{scheduled_for}/retry` | 226 | principal | dispatch | require_author |
| POST | `/v1/workflows` | 252 | principal | dispatch | require_author |
| POST | `/v1/workflows/{wf_id}/schedule` | 262 | principal | dispatch | require_author |
| POST | `/v1/workflows/{wf_id}/archive` | 294 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/restore` | 294 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/unschedule` | 294 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/trigger` | 303 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/execute` | 317 | principal | dispatch | - |

#### `boltrig/kernel/sensing_routes.py` (5)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| PUT | `/v1/me/sensing/camera` | 119 | principal | store/service | is_interactive_credential |
| PUT | `/v1/me/sensing/presence` | 147 | principal | store/service | is_interactive_credential |
| DELETE | `/v1/me/sensing/enrollment` | 171 | principal | store/service | is_interactive_credential |
| GET | `/v1/me/sensing` | 185 | principal | read | - |
| GET | `/v1/sensing/capability` | 189 | principal | read | - |

#### `boltrig/kernel/trajectory_routes.py` (4)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/trajectory` | 43 | principal | read | - |
| GET | `/v1/trajectory/{run_id}` | 53 | principal | read | visible_work_item_by_run |
| GET | `/v1/trajectory/{run_id}/export` | 72 | principal | read | visible_work_item_by_run |
| DELETE | `/v1/trajectory/{run_id}` | 100 | principal | store/service | visible_work_item_by_run |

#### `boltrig/kernel/workflow_trigger_author_routes.py` (7)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/workflows/{wf_id}/triggers` | 32 | principal | read | require_author |
| GET | `/v1/workflows/{wf_id}/trigger-finalizations` | 45 | principal | read | require_author |
| POST | `/v1/workflows/{wf_id}/triggers` | 60 | principal | dispatch | require_author |
| POST | `/v1/workflows/{wf_id}/triggers/{trigger_id}/disable` | 104 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/triggers/{trigger_id}/enable` | 104 | principal | dispatch | - |
| POST | `/v1/workflows/{wf_id}/triggers/{trigger_id}/rotate` | 104 | principal | dispatch | - |
| GET | `/v1/workflows/{wf_id}/triggers/{trigger_id}/deliveries` | 113 | principal | read | require_author |

#### `boltrig/kernel/workflow_trigger_public_routes.py` (1)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| POST | `/v1/automation-hooks/{tenant_id}/{trigger_id}` | 55 | trigger-secret | dispatch (cross-module) | _authenticated |

#### `boltrig/kernel/workspace_management_routes.py` (6)

| method | path | line | auth | dispatch | in-route guard |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/workspaces` | 15 | principal | read | - |
| POST | `/v1/workspaces` | 24 | principal | dispatch | require_admin |
| PATCH | `/v1/workspaces/{workspace_id}` | 54 | principal | dispatch | - |
| GET | `/v1/workspaces/{workspace_id}/members` | 83 | principal | read | - |
| POST | `/v1/workspaces/{workspace_id}/members` | 110 | principal | dispatch | - |
| DELETE | `/v1/workspaces/{workspace_id}/members/{user_id}` | 154 | principal | dispatch | - |
### 4.7 Inventory totals and the notable exceptions

| dimension | count |
| --- | --- |
| routes on the kernel app | 294 |
| GET / POST / DELETE / PUT / PATCH | 133 / 120 / 19 / 12 / 10 |
| carry the `principal` dependency | 267 |
| non-`principal` authentication | 24 (11 device-session, 9 run-token, 1 HMAC, 1 trigger-secret, 1 enrollment-code, 1 `/v1/mcp` dual) |
| unauthenticated | 3 |
| state-changing (non-GET) | 161 |
| state-changing AND reaching the dispatcher | 93 |
| state-changing and NOT reaching the dispatcher | **68** |
| routes performing an in-route RBAC check | 119, of which 81 call `require_author(p)` |

**Exception 1: the three unauthenticated routes.** `GET /v1/branding`,
`GET /healthz`, `GET /readyz`, all in one file on purpose
([`boltrig/kernel/health_routes.py:1`](../../../boltrig/kernel/health_routes.py)
`"The unauthenticated routes, all of them, in one file."`). The file states its own
reason: `"what can be reached without a session is a question somebody has to be able to answer by reading one file"`.
`/healthz` returns a per-tenant, per-adapter posture map keyed `f"{tenant}/{adapter}"`
([`:36`](../../../boltrig/kernel/health_routes.py) `"f\"{tenant}/{adapter}\": value for (tenant, adapter), value in health.items()"`).
`/readyz` returns 200 or 503 from a `ReadinessService` built lazily under an
`asyncio.Lock` ([`:50`](../../../boltrig/kernel/health_routes.py) `"async with readiness_service_lock:"`).

**Exception 2: `POST /v1/mcp` is the only route whose auth branches on a header.**
If `x-boltrig-mcp-token` is present the value is treated as a run token; otherwise
an `Authorization: Bearer` value is tested with `k.mcp.is_run_token` and adopted as
a run token if it matches; only then does the route resolve a `Principal`
([`boltrig/kernel/app.py:390`](../../../boltrig/kernel/app.py) `"run_token = request.headers.get(\"x-boltrig-mcp-token\")"`
through [`:405`](../../../boltrig/kernel/app.py) `"p = await principal(request)"`).
An invalid run token does NOT fall through to the principal path: it returns a
JSON-RPC error frame at HTTP 200 and records an `MCP_AUTH_FAILURE` security event
([`boltrig/kernel/mcp.py:163`](../../../boltrig/kernel/mcp.py) `"rt = self._lookup(token)"`,
[`:177`](../../../boltrig/kernel/mcp.py) `"return _err(request.get(\"id\"), -32001, \"invalid or expired run token\")"`).

**Exception 3: `POST /v1/channels/{channel_id}/inbound` is signature-authenticated.**
The only route that verifies an HMAC over the RAW wire bytes rather than a bearer
([`boltrig/kernel/channel_inbound_routes.py:89`](../../../boltrig/kernel/channel_inbound_routes.py)
`"raw_body = await request.body()"`, `"verify_and_normalise(body, dict(request.headers), secret, raw_body=raw_body)"`).
It resolves a channel `Principal` from the paired sender, applies a thread grant
ceiling by intersection ([`:161`](../../../boltrig/kernel/channel_inbound_routes.py)
`"principal = replace(principal, grants=principal.grants.intersect(ceiling))"`),
and then writes a work item DIRECTLY: `"await kernel.store.create_work_item(item)"`
([`:191`](../../../boltrig/kernel/channel_inbound_routes.py)). It is registered with
`add_api_route`, not a decorator ([`:223`](../../../boltrig/kernel/channel_inbound_routes.py)
`"app.add_api_route("`).

**Exception 4: `POST /v1/automation-hooks/{tenant_id}/{trigger_id}` is the only
public route that reaches the dispatcher.** Auth is a constant-time digest compare
([`boltrig/kernel/workflow_trigger_public_routes.py:30`](../../../boltrig/kernel/workflow_trigger_public_routes.py)
`"secrets.compare_digest("`), the caller identity is SYNTHESISED from the trigger's
owner and ceilinged by the trigger's stored grant ceiling
([`boltrig/kernel/workflow_trigger_delivery.py:81`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`"bounded = current.intersect(trigger.grant_ceiling)"`), and the call lands on
`dispatch_control_route(kernel, principal, "control.workflow.trigger", ...)`
([`:237`](../../../boltrig/kernel/workflow_trigger_delivery.py)). Its ordering is
deliberate and documented: dedup before throttle, throttle before the trigger lookup,
because the lookup is an unauthenticated indexed DB read
([`boltrig/kernel/workflow_trigger_public_routes.py:79`](../../../boltrig/kernel/workflow_trigger_public_routes.py)
`"Dedup BEFORE the throttle"`).

**Exception 5: the device and gateway families never touch the dispatcher.**
`call_routes.py`, `call_gateway_routes.py`, `camera_agent_routes.py`,
`device_agent_routes.py`, `device_routes.py`, `channel_inventory_routes.py`,
`channel_gateway_outbox_routes.py`, `channel_gateway_reconcile_routes.py`,
`channel_gateway_session_routes.py` and `channel_inbound_routes.py` contain ZERO
occurrences of `kernel.invoke(`, `k.invoke(` or `dispatch_control_route(` (bounded:
`rg -c 'kernel\.invoke\(|k\.invoke\(|dispatch_control_route\(' <each file>`, 2026-08-24,
pinned tree, 0 in every one). They write directly through named store methods:
`create_realtime_call`, `update_realtime_call`, `append_realtime_call_event`,
`claim_realtime_call_media`, `create_device_enrollment`, `complete_device_enrollment`,
`create_device_root`, `revoke_device`, `revoke_device_root`, `rotate_device_session`,
`claim_device_lease`, `settle_device_lease`, `upsert_camera_binding`,
`claim_camera_lease`, `settle_camera_lease`, `claim_channel_outbox`,
`ack_channel_outbox`, `fail_channel_outbox`, `claim_channel_gateway_lease`,
`upsert_channel_gateway_status`, `create_work_item`.

**Exception 6: `POST /v1/ai-keys/activate` provisions an EXTERNAL system off-dispatch.**
The handler calls `activate_ai_key_config`, which loads key MATERIAL from the store
and calls `BifrostUserGateway().ensure(...)`
([`boltrig/kernel/ai_key_proposal_routes.py:172`](../../../boltrig/kernel/ai_key_proposal_routes.py)
`"material = await load_ai_key_material(kernel.store, principal.tenant_id, resolution)"`,
[`:184`](../../../boltrig/kernel/ai_key_proposal_routes.py) `"await BifrostUserGateway().ensure("`).
Neither the route nor the helper writes an audit row.

**Exception 7: `POST /v1/integrations/{integration_id}/oauth/start` is SCAFFOLDED.**
It authorises, looks the catalogue item up, and then always returns HTTP 409 with
`"status": "unsupported"` ([`boltrig/kernel/platform_routes/integration_setup.py:159`](../../../boltrig/kernel/platform_routes/integration_setup.py)
`"\"status\": \"unsupported\","`). No OAuth flow exists behind it.

**Exception 8: `POST /v1/me/agent` writes with neither an RBAC guard nor an audit row.**
Its sibling `DELETE /v1/me/agent` is audited
([`boltrig/kernel/platform_routes/personal.py:51`](../../../boltrig/kernel/platform_routes/personal.py)
`"await audit_authoring(k, p, \"personal_agent.delete\", {})"`) while the create/update
at [`:27`](../../../boltrig/kernel/platform_routes/personal.py) (`"await k.store.upsert_personal_agent(agent)"`)
is not.

**Exception 9: three routes demand an interactive HUMAN, not just a principal.**
`PUT /v1/me/approval-posture` ([`boltrig/kernel/approval_posture_routes.py:25`](../../../boltrig/kernel/approval_posture_routes.py)
`"if p.actor_tier != \"human\" or not is_interactive_credential(p.credential_kind):"`)
and the two sensing writes plus the enrollment delete in
[`boltrig/kernel/sensing_routes.py`](../../../boltrig/kernel/sensing_routes.py) use the
same predicate. This is the only place on the surface where `credential_kind` gates a route.

**Exception 10: routes that delegate to the fleet.** `/v1/chat`, `/v1/spawn`,
`/v1/eval/run`, `/v1/me/agent/invoke` and the two `/v1/skills/{skill_id}/test-spawn`
forms do not dispatch themselves; they hand a context to an injected spawner or chat
service, whose steps then dispatch per verb. `/v1/skills/{skill_id}/test-spawn` is
registered twice, once with a plain segment and once with `{skill_id:path}`
([`boltrig/kernel/platform_routes/skill_write_routes.py:88`](../../../boltrig/kernel/platform_routes/skill_write_routes.py) `"async def test_spawn("`
and [`:93`](../../../boltrig/kernel/platform_routes/skill_write_routes.py)).

**Exception 11: route-order sensitivity.** `GET /v1/conversations/search` is
registered BEFORE `GET /v1/conversations/{conversation_id}` on purpose
([`boltrig/kernel/app.py:500`](../../../boltrig/kernel/app.py)
`"Registered BEFORE the /{conversation_id}"`).
`/v1/conversations/{conversation_id}` itself lives in a different module registered
later ([`boltrig/kernel/conversation_live_routes.py:168`](../../../boltrig/kernel/conversation_live_routes.py) `"async def conversation(conversation_id: str, request: Request,"`),
so the ordering depends on `register_worker_query_routes` being called at
[`boltrig/kernel/app.py:518`](../../../boltrig/kernel/app.py) `"register_worker_query_routes(app, principal_dep=principal"`, after both
`/v1/conversations` handlers.

## 5. Control flow

### 5.1 Application construction (`create_app`)

1. **Resolver selection.** If no `principal_resolver` was passed, ask
   `production_signal()`; if it is not None, raise `RuntimeError` and refuse to boot
   ([`boltrig/kernel/app.py:254`](../../../boltrig/kernel/app.py)
   `"sig = production_signal()"`, [`:256`](../../../boltrig/kernel/app.py)
   `"FATAL: create_app() received no principal_resolver with a production"`). Otherwise fall back
   to `_dev_principal`. **Failure branch:** in production the process does not start.
2. **Lifespan.** If `app.state.kernel` is unset, build it from `kernel_factory` ON
   THE SERVING LOOP so loop-bound resources attach correctly, then attach spawner,
   chat and platform ([`boltrig/kernel/app.py:276`](../../../boltrig/kernel/app.py)
   `"if not hasattr(app.state, \"kernel\"):"`). **Failure branch:** no kernel and no
   factory raises `RuntimeError("create_app needs a kernel or a kernel_factory")`.
   On shutdown `await active_kernel.aclose()` runs in a `finally`.
3. **Middleware.** `install_security(app)` at
   [`boltrig/kernel/app.py:297`](../../../boltrig/kernel/app.py) `"install_security(app)"`. **Failure branch:**
   a wildcard host allowlist under a production signal raises before any request.
4. **Error handler.** One `@app.exception_handler(BoltrigError)`.
5. **Prebuilt kernel path.** A kernel passed directly is attached synchronously so
   `TestClient` works without the lifespan ([`:309`](../../../boltrig/kernel/app.py)
   `"Prebuilt kernel is set synchronously so it works even without lifespan"`).
6. **Route registration, in this order:** health, the eleven `app.py`-local routes,
   `register_worker_query_routes`, `register_platform_routes`, `register_access_routes`,
   `register_auth_routes` (from `boltrig/api`), `register_memory_routes`,
   `register_channel_routes`, `register_channel_gateway_routes`, `register_desktop_routes`
   ([`boltrig/kernel/app.py:335`](../../../boltrig/kernel/app.py) `"from .health_routes import register_health_routes"` to [`:740`](../../../boltrig/kernel/app.py)).
   Each of those fans out further: `register_platform_routes` loops 32 modules then
   calls `register_call_routes` and `register_device_routes`
   ([`boltrig/kernel/platform_routes/__init__.py:59`](../../../boltrig/kernel/platform_routes/__init__.py)
   `"for module in ("`), `register_device_routes` calls `register_device_agent_routes`
   which calls `register_camera_agent_routes`, and so on to a depth of four.

### 5.2 Per-request principal resolution

1. `resolve_principal(request, resolver, _get_kernel)` runs
   ([`boltrig/kernel/app.py:321`](../../../boltrig/kernel/app.py) `"p = await resolve_principal(request, resolver, _get_kernel)"`).
2. Extract `Authorization: Bearer` ([`boltrig/kernel/bearer_principal.py:33`](../../../boltrig/kernel/bearer_principal.py)
   `"def bearer_token"`). If it is absent or does not satisfy `looks_like_pat`, delegate
   to the configured resolver and stop.
3. Otherwise resolve the PAT, passing `requested_workspace_id` from the
   `x-boltrig-workspace` header ([`:60`](../../../boltrig/kernel/bearer_principal.py)
   `"requested_workspace_id=request.headers.get(WORKSPACE_HEADER)"`).
   **Failure branch A:** `WorkspaceNotPermitted` becomes **403**, not 404, and the
   file states why: `"answering 404 instead would disclose which workspace ids exist"`
   ([`:67`](../../../boltrig/kernel/bearer_principal.py)). **Failure branch B:** a
   `None` principal becomes **401** `"invalid or expired access token"`.
   The refusal is deliberate rather than a fallback, because with no active workspace
   `effective_grants_for_request` returns the owner's org grants UN-NARROWED
   ([`:15`](../../../boltrig/kernel/bearer_principal.py) `"WHY A BAD WORKSPACE REFUSES RATHER THAN FALLS BACK"`).
4. Back in `app.py`: stamp `ip_address` from `client_ip(request)` and `user_agent`
   from the header, then `set_current_tenant(p.tenant_id)` to bind RLS for the request
   ([`boltrig/kernel/app.py:328`](../../../boltrig/kernel/app.py) `"p.ip_address = _client_ip(request)"` to [`:332`](../../../boltrig/kernel/app.py)).

### 5.3 The session resolver path (production single-tenant console)

`build_session_resolver` is what bootstrap selects when session auth is configured
([`boltrig/api/auth_selection.py:104`](../../../boltrig/api/auth_selection.py)
`"if settings.session_auth_configured:"`). Ordered steps, each with its failure branch,
from [`boltrig/identity/sessions.py:268`](../../../boltrig/identity/sessions.py) `"async def resolver(request: Request) -> Principal:"`:

1. Read the `boltrig_session` cookie. Missing: **401 "no session"**.
2. `resolve_session` against the store. Unknown or expired: **401**.
3. `resolve_active_org` re-authorises the session's active org against CURRENT
   membership. None: **401**.
4. `set_current_tenant(active_org_id)` then read the per-org user row. Missing or
   not `active`: **401**.
5. **CSRF**: on POST/PUT/PATCH/DELETE compare `x-boltrig-csrf` to the session token
   with `hmac.compare_digest`. Mismatch: **403 "csrf token missing or invalid"**
   ([`:312`](../../../boltrig/identity/sessions.py)). Bearer and PAT callers never
   reach this code, so they are never CSRF-gated.
6. **Forced password rotation clamp**: `must_change_password` restricts the caller
   to `{/v1/auth/csrf, /v1/auth/change-password, /v1/auth/logout}`, else **403
   "password_change_required"**.
7. **2FA enrollment clamp**: if the org requires 2FA and no factor is enrolled, the
   caller is restricted to `{/v1/auth/csrf, /v1/auth/2fa/enroll, /v1/auth/2fa/verify-enroll, /v1/auth/logout}`,
   else **403 "two_factor_enrollment_required"**.
8. `resolve_active_workspace` re-authorises membership; a revoked membership drops
   to `None` fail-closed.
9. `effective_grants_for_request` narrows org grants by the workspace role ceiling,
   intersecting only downward.
10. Rebind RLS to the active org, stash the session on `request.state.boltrig_session`,
    and return a `Principal` with `credential_kind="session"`.

Both clamps are ALLOWLISTS of literal paths, so a new auth-adjacent route is
clamped out by default.

### 5.4 `POST /v1/invoke`, the primary write door

1. `foreign_run_asserted(k.store, p, body.context)`; a run named in the body that
   belongs to another subject is **403 "not your run"** BEFORE any dispatch
   ([`boltrig/kernel/app.py:348`](../../../boltrig/kernel/app.py) `"if await foreign_run_asserted(k.store, p, body.context):"`). Both `run_id` and
   `parent_run_id` are fenced ([`boltrig/kernel/run_access.py:130`](../../../boltrig/kernel/run_access.py)
   `"for key in (\"run_id\", \"parent_run_id\"):"`).
2. Build the context from the body's `run_id`, `parent_run_id`, clamped `depth` and
   `skills_loaded`.
3. `k.invoke(noun, verb, params, ctx, idempotency_key=..., approval_id=...)`.
4. **Failure branches:** `PendingHuman` becomes 202 with `hitl_request_id`;
   `DegradedMode` becomes 503 with a partial `output`; any other `BoltrigError`
   reaches the central handler and the canonical envelope.

### 5.5 `dispatch_control_route`, the compatibility write path

Used by 93 mutating routes. Ordered steps from
[`boltrig/kernel/control_routes.py:54`](../../../boltrig/kernel/control_routes.py) `"async def dispatch_control_route("`:

1. `_ensure_control_plane`: if the tenant has no `control` adapter, build one from
   `app.state.platform` and register it; otherwise re-point its registry, admin,
   workflows and model catalogue, and re-register its verbs when
   `control.workflow.upsert` is missing ([`:28`](../../../boltrig/kernel/control_routes.py)
   `"adapter = kernel.loader.peek(tenant, \"control\")"`). This is a late-wire for
   in-process construction: `"Production bootstrap registers it eagerly."`
2. Strip `approval_id` and `idempotency_key` out of `params`, then let the
   `x-boltrig-approval-id` and `idempotency-key` HEADERS override the body values
   ([`:74`](../../../boltrig/kernel/control_routes.py)).
3. `kernel.invoke("control", verb, clean, principal.context(run_id=run_id), ...)`.
4. If an `approval_id` was supplied and the HITL row is now `CONSUMED` for the same
   verb with a run id, retire the matching held checkpoint through `settle_held_call`
   inside a bare `except Exception: pass`, because `"The governed write already committed. Cleanup is fail-safe"`
   ([`:106`](../../../boltrig/kernel/control_routes.py)).
5. **Failure branches:** `PendingHuman` returns `(None, 202 response)`;
   `DegradedMode` returns `(None, 503 response)`; every other error propagates.

### 5.6 SSE streams

Two families. `/v1/chat` pulls the FIRST event from the async generator before the
response begins, so an RBAC error surfaces as a normal envelope rather than inside
a half-open stream ([`boltrig/kernel/app.py:434`](../../../boltrig/kernel/app.py)
`"RBAC / access errors happen before the first event"`). A first event of type
`queued` short-circuits to 202 instead of SSE ([`:442`](../../../boltrig/kernel/app.py)).
`/v1/runs/{run_id}/events` authorises with `visible_run_events` (404 on unknown or
out-of-scope), then either snapshots or subscribes with `replay=True`, honouring a
`?since=<seq>` cursor that can only NARROW the replay
([`boltrig/kernel/app.py:676`](../../../boltrig/kernel/app.py)
`"cursor = since if (since is not None and since >= 0) else None"`).

## 6. Data

The HTTP surface owns no tables and no migrations. It reads and writes the store
through named methods only. The columns it is coupled to, by observation of the
handler code:

- **Pagination contract for `/v1/work`**: `clamp_work_page(limit)` bounds the page,
  keyset paging is by item id, and `next_cursor` is the last item's id only when the
  page came back full ([`boltrig/kernel/app.py:586`](../../../boltrig/kernel/app.py)
  `"next_cursor = items[-1].id if len(items) == page else None"`). Defaults come from
  `boltrig.store.base` as `DEFAULT_WORK_PAGE` and `MAX_WORK_PAGE`.
- **Department isolation**: `departments_for(p.role, p.scope)` returns `None` for an
  org-admin (unrestricted) or a list; `/v1/work/{item_id}` mirrors the store predicate
  in-process and 404s an out-of-scope item so its existence never leaks
  ([`boltrig/kernel/app.py:616`](../../../boltrig/kernel/app.py)
  `"out-of-scope reads 404 (not 403) so the item's existence never leaks"`).
- **Session rows** are written by three routes only: `DELETE /v1/me/sessions/{id}`,
  `POST /v1/me/active-context` (sets `active_workspace_id`), `POST /v1/me/active-org`
  (sets `active_org_id`). Each binds `set_current_tenant(session.tenant_id)` for the
  write and restores the caller's active tenant in a `finally`
  ([`boltrig/kernel/access_routes.py:440`](../../../boltrig/kernel/access_routes.py) `"session.active_workspace_id = workspace_id"`).
- **Cookies** are the only client-side state: `boltrig_session` (httpOnly) and
  `boltrig_csrf` (readable by JS), both `SameSite=Strict` except from an
  explicitly CORS-allowlisted Tauri origin, where they become `SameSite=None`
  ([`boltrig/api/desktop_session_auth.py:42`](../../../boltrig/api/desktop_session_auth.py)
  `"same_site = \"none\" if secure and _desktop_session_request(request) else \"strict\""`).
- **Retention and encryption** are not decided here. The one place the surface
  touches sealed material is `answer_hitl_question` for a SECURE question, which
  seals the value inside the kernel and records only the reference
  ([`boltrig/kernel/hitl_http.py:271`](../../../boltrig/kernel/hitl_http.py)
  `"reference = await kernel.credentials.seal_run_scoped_value("`), withholding even
  the LENGTH: `"answer_len is None here: even the LENGTH of a secure value is a leak."`

## 7. Configuration surface

| variable | read at | default | effect if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_ALLOWED_HOSTS` | [`boltrig/kernel/web_security.py:296`](../../../boltrig/kernel/web_security.py) `"hosts = _csv(e.get(\"BOLTRIG_ALLOWED_HOSTS\")) or [\"*\"]"` | `["*"]` | `["*"]` plus a production signal is a FATAL boot error. Otherwise Host validation is off and DNS-rebinding / Host-header attacks are unfiltered. |
| `BOLTRIG_CORS_ORIGINS` | [`boltrig/kernel/web_security.py:302`](../../../boltrig/kernel/web_security.py) `"origins = _csv(e.get(\"BOLTRIG_CORS_ORIGINS\"))"` | empty | Empty means CORSMiddleware is NOT INSTALLED AT ALL, so browsers see no ACAO and cross-origin reads fail closed. A listed origin also switches the desktop cookie to `SameSite=None` for that origin. |
| `BOLTRIG_MAX_BODY_BYTES` | [`boltrig/kernel/web_security.py:304`](../../../boltrig/kernel/web_security.py) `"max_body = int(e.get(\"BOLTRIG_MAX_BODY_BYTES\") or"` | 1 MiB (`_DEFAULT_MAX_BODY`) | A non-integer value falls back to 1 MiB silently. Too low breaks uploads; too high re-opens body-flood DoS. |
| `BOLTRIG_PRODUCTION`, `ENV`, `BOLTRIG_ENV`, `APP_ENV` | [`boltrig/kernel/web_security.py:185`](../../../boltrig/kernel/web_security.py) `"if is_truthy(env.get(\"BOLTRIG_PRODUCTION\")):"` | unset | Any of the three name vars equal to `prod`/`production`/`staging` counts as production and arms both fatal guards. |
| `BOLTRIG_TRUST_CF_CONNECTING_IP` | [`boltrig/kernel/web_security.py:70`](../../../boltrig/kernel/web_security.py) `"if is_truthy(os.environ.get(\"BOLTRIG_TRUST_CF_CONNECTING_IP\")):"` | unset | Off: `CF-Connecting-IP` is ignored and the TCP peer is used, which behind a tunnel collapses every per-IP rate-limit bucket into ONE. The file says so: [`:58`](../../../boltrig/kernel/web_security.py) `"31 sprayed logins for distinct emails then 429 every legitimate user"`. On without a tunnel: the header becomes client-spoofable. |
| `BOLTRIG_TRUST_FORWARDED_PREFIX` | [`boltrig/kernel/web_security.py:116`](../../../boltrig/kernel/web_security.py) `"if not is_truthy(e.get(\"BOLTRIG_TRUST_FORWARDED_PREFIX\")):"` | unset | Off: session cookies keep `Path=/` and are attached to every request on that host, including an unrelated app sharing the origin. On: the edge's `X-Forwarded-Prefix` (up to four segments matching `_PREFIX_RE`) narrows both cookies. |
| `BOLTRIG_DEV_AUTH` | [`boltrig/api/auth_selection.py:111`](../../../boltrig/api/auth_selection.py) `"if settings.dev_auth:"` | unset | Returns `None` so `create_app` installs `_dev_principal`, which trusts `x-boltrig-role`, `x-boltrig-tenant`, `x-boltrig-subject`, `x-boltrig-grants`, `x-boltrig-verbs`, `x-boltrig-departments`, `x-boltrig-tier`, `x-boltrig-obo`, `x-boltrig-workspace` and defaults `role` to `org-admin` with `GrantSet.of(["*"])`. Refused under a production signal by `refuse_dev_auth_in_prod`. |
| `REDIS_URL` | wired at the composition root, described at [`boltrig/kernel/ratelimit.py:4`](../../../boltrig/kernel/ratelimit.py) `"end is Redis (wired from "` | unset | Unset falls back to `InMemoryCounter`, making every bound per-process and per-boot. The file records that this was silently true for a long time: `"RedisCounter existed but was constructed nowhere"`. |

`_PATH_BODY_CAPS` is a hard-coded tuple, not an env var: any path starting
`/v1/knowledge/uploads/` gets 25 MiB instead of the global cap
([`boltrig/kernel/web_security.py:172`](../../../boltrig/kernel/web_security.py)
`"_PATH_BODY_CAPS = ((\"/v1/knowledge/uploads/\", 25 * 1024 * 1024),)"`).

## 8. PROCESS

**Bring-up.** The surface is never constructed by hand in production.
`compose_api_app` assembles the factories and calls `create_app` once
([`boltrig/api/app_composition.py:115`](../../../boltrig/api/app_composition.py)
`"return create_app("`), passing `principal_resolver=select_principal_resolver(manifest)`.
`select_principal_resolver` first runs `refuse_default_audit_key_in_prod()` (K-19)
and then delegates to `select_auth_resolver`, which picks exactly one posture in a
fixed order: session, then Cloudflare Access, then generic OIDC (manifest trio or
process trio, refusing a PARTIAL trio and refusing a MISMATCH between the two), then
dev auth, then a deny-all resolver
([`boltrig/api/auth_selection.py:94`](../../../boltrig/api/auth_selection.py)
`"def select_auth_resolver"`, and [`boltrig/api/bootstrap.py:491`](../../../boltrig/api/bootstrap.py)
`"def _deny_all_resolver():"` which raises 401 `"authentication is not configured"`).

**Adding a route.** The mechanical procedure implied by the code:

1. Pick or create a `*_routes.py` module with a `register_*(app, P, K)` or
   `register_*(app, *, principal_dep, get_kernel)` signature.
2. Bind `P = Depends(principal_dep)` and `K = Depends(get_kernel)` at the top of the
   register function; every module in the tree does exactly this (bounded:
   `rg -n 'Depends\(' boltrig/kernel/ | grep -v get_kernel`, 2026-08-24, 31 hits, all
   `Depends(principal_dep)` or `Depends(principal)`).
3. Wire the register call into the chain, which bottoms out at one of the ten calls
   in `create_app`.
4. If the route mutates, route it through `dispatch_control_route` with a `control.*`
   verb, per [`docs/requirements-control-plane.md:103`](../../../docs/requirements-control-plane.md)
   `"P2 (one dispatch chokepoint) is binding. A second ungoverned write path"`.
5. Add an invariant id to `tests/invariants.yaml` and a test marked
   `@pytest.mark.invariant("<ID>")`; `scripts/check_invariants.py` fails the build on
   an undeclared marker or an unbound invariant ([`AGENTS.md:53`](../../../AGENTS.md)
   `"Every security or correctness claim must be pinned to a test"`).

**Changing the edge.** `install_security` accepts an `env` dict override precisely so
it can be exercised without touching the process environment
([`boltrig/kernel/web_security.py:285`](../../../boltrig/kernel/web_security.py)
`"def install_security(app: FastAPI, *, env: dict | None = None)"`). Middleware order
is stated as an invariant of the function: `"Order: body cap first (cheap reject), then headers, then CORS, then Host. Starlette runs middleware in reverse add order, so add Host last to run first."`

**Diagnosis.** `/readyz` is the deployment probe and returns 503 with the report body
when not ready; `/healthz` is the liveness probe and never awaits adapter I/O, by
design ([`boltrig/adapters/loader.py:95`](../../../boltrig/adapters/loader.py)
`"reads this and must never await live adapter"`).
`GET /v1/me/connections` is the self-service surface that tells a caller how to attach
headlessly ([`boltrig/kernel/access_routes.py:328`](../../../boltrig/kernel/access_routes.py)
`"how to attach an external client headlessly (SET-41 / HEAD-03)"`).

**Recovery.** A gateway that loses its token has one documented path, stated in the
mint response itself: `"recovery": "replace_token_file_or_restart"`
([`boltrig/kernel/channel_gateway_session_routes.py:82`](../../../boltrig/kernel/channel_gateway_session_routes.py) `"replace_token_file_or_restart"`).
A device rotates through `POST /v1/device-agent/{device_id}/session/rotate`.

**Gates a change here must pass.** `make invariants`
([`Makefile:474`](../../../Makefile) `"invariants: ## The K-29/K-30 binding gate: every claimed invariant must have a test"`)
is the binding ratchet; `make unwired-claims`
([`Makefile:136`](../../../Makefile) `"unwired-claims: ## Fail when the record names a mechanism no production path constructs"`)
carries an explicit exclusion for this area's shape: a method overriding a framework
base is not reported, and the gate's own docstring names this module as the example
([`scripts/check_unwired_claims.py:53`](../../../scripts/check_unwired_claims.py)
`"boltrig/). Starlette calls SecurityHeadersMiddleware.dispatch; no boltrig"`). It also
excludes DECORATED functions, which is every one of the 246 decorator-registered route
handlers ([`scripts/check_unwired_claims.py:49`](../../../scripts/check_unwired_claims.py)
`"a DECORATED function. The decorator is the wiring: a route handler,"`); `make prose-references`
([`Makefile:142`](../../../Makefile) `"prose-references: ## Every path, test id, make target, env var and order citation in prose must resolve"`)
resolves every path and env var named in prose; `make reachability`
([`Makefile:139`](../../../Makefile) `"reachability: ## Reachability is TRANSITIVE: report every function unreachable from every root"`)
is what would notice a route handler that nothing registers. The whole set runs as
`make python-quality` ([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure vds-ledgers codex-protocol"`).
Stack bring-up for a manual probe is `make up` / `make down` / `make logs SERVICE=kernel`
([`Makefile:38`](../../../Makefile) `"up: ## Build + start the whole stack"`).

I did not run any test, make target, docker command or installer, per the contract.

## 9. Failure modes and fail-open/fail-closed posture

| guard | fails | proof |
| --- | --- | --- |
| Missing principal resolver under a production signal | CLOSED (process refuses to start) | [`boltrig/kernel/app.py:256`](../../../boltrig/kernel/app.py) `"raise RuntimeError("` |
| No auth configured at all | CLOSED (401 every request) | [`boltrig/api/bootstrap.py:496`](../../../boltrig/api/bootstrap.py) `"raise HTTPException(status_code=401, detail=\"authentication is not configured\")"` |
| PAT names a workspace the owner cannot reach | CLOSED (403, no fallback) | [`boltrig/kernel/bearer_principal.py:67`](../../../boltrig/kernel/bearer_principal.py) `"not a member of that workspace"` |
| Session cookie invalid / org membership revoked / user deactivated | CLOSED (401) | [`boltrig/identity/sessions.py:301`](../../../boltrig/identity/sessions.py) `"invalid or expired session"` |
| CSRF header missing on a mutating cookie request | CLOSED (403) | [`boltrig/identity/sessions.py:312`](../../../boltrig/identity/sessions.py) `"csrf token missing or invalid"` |
| Active workspace no longer a membership | CLOSED (drops to None, grants un-narrowed only at the org level) | [`boltrig/identity/sessions.py:351`](../../../boltrig/identity/sessions.py) `"resolve_active_workspace"` |
| `BOLTRIG_ALLOWED_HOSTS` exactly `*` in production | CLOSED (fatal) | [`boltrig/kernel/web_security.py:299`](../../../boltrig/kernel/web_security.py) `"FATAL: BOLTRIG_ALLOWED_HOSTS is '*' in production."` |
| `BOLTRIG_CORS_ORIGINS` unset | CLOSED (no CORS middleware, same-origin only) | [`boltrig/kernel/web_security.py:313`](../../../boltrig/kernel/web_security.py) `"if origins:"` |
| `BOLTRIG_MAX_BODY_BYTES` not an integer | OPEN-ish (silently reverts to the 1 MiB default) | [`boltrig/kernel/web_security.py:305`](../../../boltrig/kernel/web_security.py) `"except ValueError:"` |
| Unrecognised `X-Forwarded-Prefix` | OPEN by construction, and the file says so | [`boltrig/kernel/web_security.py:105`](../../../boltrig/kernel/web_security.py) `"The conservative choice failed OPEN, because the fallback for an"` |
| Content-Length header not an integer | CLOSED (400 `bad_content_length`) | [`boltrig/kernel/web_security.py:243`](../../../boltrig/kernel/web_security.py) `"await self._error(send, 400, \"bad_content_length\")"` |
| Body over cap, declared or streamed | CLOSED (413 `payload_too_large`) | [`boltrig/kernel/web_security.py:240`](../../../boltrig/kernel/web_security.py) `"await self._error(send, 413, \"payload_too_large\")"`, [`:265`](../../../boltrig/kernel/web_security.py) |
| Body on a method outside `{POST,PUT,PATCH}` with no Content-Length | OPEN (never counted) | [`boltrig/kernel/web_security.py:250`](../../../boltrig/kernel/web_security.py) `"if scope.get(\"method\") not in self._BODY_METHODS:"` |
| Security header already set by a route | OPEN (route wins) | [`boltrig/kernel/web_security.py:199`](../../../boltrig/kernel/web_security.py) `"response.headers.setdefault(k, v)"`. No kernel route sets one (bounded: `rg -n 'HTMLResponse\|text/html\|Content-Security-Policy' boltrig/kernel/`, 1 hit, the constant itself). |
| Channel signature invalid | CLOSED (401 `signature`) | [`boltrig/kernel/channel_inbound_routes.py:92`](../../../boltrig/kernel/channel_inbound_routes.py) `"return JSONResponse({\"status\": \"denied\", \"reason\": \"signature\"},"` |
| Channel credential missing | CLOSED (503 `channel_misconfigured`) | [`boltrig/kernel/channel_inbound_routes.py:82`](../../../boltrig/kernel/channel_inbound_routes.py) `"return JSONResponse({\"error\": \"channel_misconfigured\"},"` |
| Trigger secret mismatch or unknown trigger | CLOSED (401, indistinguishable) | [`boltrig/kernel/workflow_trigger_public_routes.py:101`](../../../boltrig/kernel/workflow_trigger_public_routes.py) `"if trigger is None or not valid:"` |
| Trigger owner deactivated or lost workspace membership | CLOSED (`webhook_principal` returns None) | [`boltrig/kernel/workflow_trigger_delivery.py:72`](../../../boltrig/kernel/workflow_trigger_delivery.py) `"if user is None or user.status != \"active\":"` |
| Gateway run token missing `extra.channel_gateway` | CLOSED (401 `unauthorized`) | [`boltrig/kernel/channel_gateway_auth.py:16`](../../../boltrig/kernel/channel_gateway_auth.py) `"if token is None or not (token.extra or"` |
| Device session token names a different device | CLOSED (None, then the handler errors) | [`boltrig/kernel/device_route_support.py`](../../../boltrig/kernel/device_route_support.py) `"if token_device_id != device_id:"` |
| Injected service absent (`chat`, `spawner`, `hands`, `eval`) | CLOSED-ish (503 with a typed reason, never a 500) | [`boltrig/kernel/app.py:413`](../../../boltrig/kernel/app.py) `"chat_unavailable"`, [`:534`](../../../boltrig/kernel/app.py) `"spawner_unavailable"`, [`boltrig/kernel/desktop_routes.py:56`](../../../boltrig/kernel/desktop_routes.py) `"hands_unavailable"` |
| Held-call cleanup after an approved control write | OPEN by design, swallowed | [`boltrig/kernel/control_routes.py:106`](../../../boltrig/kernel/control_routes.py) `"except Exception:"` with `"must never turn success into a client-visible failure"` |
| Unknown work status query param | CLOSED (400, never a 500) | [`boltrig/kernel/app.py:567`](../../../boltrig/kernel/app.py) `"except ValueError:"` |
| Out-of-scope work item or run | CLOSED, and indistinguishable from absent (404) | [`boltrig/kernel/app.py:617`](../../../boltrig/kernel/app.py) `"return JSONResponse({\"error\": \"not_found\"}, status_code=404)"`, [`:645`](../../../boltrig/kernel/app.py) |
| Desktop receipt for an unknown or expired command | CLOSED (404) and NOT audited, so a no-op is never recorded as execution | [`boltrig/kernel/desktop_routes.py:82`](../../../boltrig/kernel/desktop_routes.py) `"do not audit a no-op as execution"` |

**Claim-on-read.** `GET /v1/hands/commands` marks each returned command claimed with
no `await` between the read and the mark, so a second poll cannot double-execute
([`boltrig/kernel/desktop_routes.py:59`](../../../boltrig/kernel/desktop_routes.py)
`"so the read+mark is atomic on the kernel loop."`).

## 10. What is proven

| invariant | binds | declared tests |
| --- | --- | --- |
| `SEC-58` | Security headers, Host validation, body cap. CORS is TESTED here but NOT named in the description. | `tests/security/test_round_sixteen.py::test_security_headers_host_and_body_cap` (declared); `::test_wildcard_hosts_refused_in_production` and `::test_desktop_cors_preflight_allows_only_the_required_session_headers` carry the marker but are not listed under the id ([`tests/invariants.yaml:1239`](../../../tests/invariants.yaml) `"description: 'Edge/web hardening - the kernel app stamps"`) |
| `SEC-01` | Missing/invalid bearer is 401; a valid token is scoped | `tests/security/test_auth.py::test_missing_bearer_rejected` and 5 more |
| `SEC-60` | Dev auth refuses a production signal | `tests/security/test_round_sixteen.py::test_dev_auth_refuses_production_signal` |
| `SEC-37` | Headless REST/MCP runs the same chokepoint scoped to the user, no weak path | `tests/security/test_round_four.py::test_headless_parity_no_weak_path` |
| `SEC-38` | No unauthenticated access to tokens or connection details | `tests/security/test_round_four.py::test_no_unauthenticated_access_to_tokens` |
| `SEC-56` | Run event streams are tenant and scope scoped end to end; out-of-scope is 404 | `tests/security/test_round_eleven.py::test_run_events_are_tenant_scoped` and 4 more |
| `SEC-69` | `/v1/work` is keyset-paginated with a server-clamped page | `tests/security/test_dos_bounding.py::test_list_work_is_paginated_and_clamped` and 5 more |
| `SEC-186` | Run identity is not caller-assertable at `/v1/invoke` and `/v1/spawn` | `tests/security/test_asserted_run_ownership.py::test_invoke_refuses_a_run_id_belonging_to_another_user` and 5 more |
| `FR-KER-05` | Per-verb rate limits on a SHARED counter, Redis in production | `tests/kernel/test_ratelimit_degraded.py::test_rate_limit_enforced` and 4 more |
| `SEC-16` | Every action, allowed or denied, is audited, hash-chained, append-only | declared at [`tests/invariants.yaml:931`](../../../tests/invariants.yaml) `"description: 'Every action (allowed or denied) is audited,"` |
| `SEC-32` | Authoring and admin is RBAC-gated and audited with the actor | declared at [`tests/invariants.yaml`](../../../tests/invariants.yaml) |
| `SEC-33` | Cost/audit/runs insight is scope-filtered; unknown and out-of-scope run ids are indistinguishable 404s | declared |
| `SEC-34` | A PAT never escalates and dies with its user | declared |
| `SEC-14` | High-consequence verbs pause for human approval, single-use, bound to the exact call | declared |

**Not proven.** `WEB-02`, `WEB-03`, `WEB-05`, `WEB-06`, `RES-01`, `US-HEAD-02`,
`SEC-02`, `K-3` and `IAM-09` are cited in the code of this area but are NOT declared
ids in `tests/invariants.yaml` (bounded: `grep -n '^  <ID>:$' tests/invariants.yaml`
for each, 2026-08-24, pinned tree, zero hits each). Their content is partly covered
under other ids (`SEC-58`, `SEC-60`), which is why the ratchet does not notice.

`tests/security/test_mount_path_cookie_scope.py` contains 11 tests and ZERO
`@pytest.mark.invariant` markers (bounded: `rg -c 'pytest.mark.invariant'` on that
file, 0). The mount-path cookie scoping is therefore tested but UNBOUND: nothing in
the invariant ratchet fails if it is removed.

## 11. RISKS

RISK: 68 of the 161 state-changing routes never reach the dispatcher, against a
doctrine that names one chokepoint and forbids side doors
([`AGENTS.md:25`](../../../AGENTS.md) `"Do not add side doors."`).

RISK: `POST /v1/ai-keys/activate` provisions a caller's key into the external Bifrost
gateway with no dispatch, no HITL gate, no rate limit and no audit row
([`boltrig/kernel/ai_key_proposal_routes.py:184`](../../../boltrig/kernel/ai_key_proposal_routes.py)
`"await BifrostUserGateway().ensure("`).

RISK: `activate_ai_key_config` reads raw key MATERIAL out of the store on an HTTP
route rather than inside the kernel's credential resolution
([`boltrig/kernel/ai_key_proposal_routes.py:172`](../../../boltrig/kernel/ai_key_proposal_routes.py)
`"material = await load_ai_key_material(kernel.store, principal.tenant_id, resolution)"`),
against `"Credentials are resolved inside the kernel"` ([`AGENTS.md:35`](../../../AGENTS.md) `"- Credentials are resolved inside the kernel and NEVER handed"`).

RISK: the entire call, device, camera and channel-gateway family writes to the DB with
no verb, no grant check at the chokepoint and no per-verb rate limit (bounded:
`rg -c 'kernel\.invoke\(|k\.invoke\(|dispatch_control_route\('` returns 0 for all ten
modules named in Exception 5).

RISK: `POST /v1/me/agent` creates or replaces a personal agent with no RBAC guard and
no audit row, while its sibling DELETE is audited
([`boltrig/kernel/platform_routes/personal.py:27`](../../../boltrig/kernel/platform_routes/personal.py)
`"await k.store.upsert_personal_agent(agent)"`).

RISK: the production Host-validation guard compares the whole list to `["*"]`
([`boltrig/kernel/web_security.py:297`](../../../boltrig/kernel/web_security.py)
`"if hosts == [\"*\"] and _production_signal(e):"`), so `BOLTRIG_ALLOWED_HOSTS="*,app.example.com"`
passes the fatal check while still handing a wildcard entry to `TrustedHostMiddleware`.

RISK: the request-body cap is only applied to POST, PUT and PATCH when no
Content-Length is present ([`boltrig/kernel/web_security.py:221`](../../../boltrig/kernel/web_security.py)
`"_BODY_METHODS = frozenset({\"POST\", \"PUT\", \"PATCH\"})"`), so a chunked DELETE body
is never counted; the app has 19 DELETE routes.

RISK: the per-path 25 MiB cap is a prefix match on `scope["path"]`
([`boltrig/kernel/web_security.py:225`](../../../boltrig/kernel/web_security.py)
`"if path.startswith(prefix):"`), so any URL beginning `/v1/knowledge/uploads/`,
including one that resolves to a 404, buffers up to 25 MiB in memory before the router
sees it.

RISK: the CORS `allow_headers` allowlist omits two headers the kernel actually reads,
`idempotency-key` ([`boltrig/kernel/control_routes.py:75`](../../../boltrig/kernel/control_routes.py)
`"request.headers.get(\"idempotency-key\")"`) and `x-boltrig-workspace`
([`boltrig/kernel/bearer_principal.py:60`](../../../boltrig/kernel/bearer_principal.py) `"requested_workspace_id=request.headers.get(WORKSPACE_HEADER)"`),
so a cross-origin browser client cannot send an idempotency key or select a workspace,
which is exactly the embedded-console case `bearer_principal.py` was written for
([`:11`](../../../boltrig/kernel/bearer_principal.py) `"An embedded console needs to say which workspace it is showing"`).

RISK: `/healthz` is unauthenticated and discloses tenant ids and adapter names in its
response body ([`boltrig/kernel/health_routes.py:37`](../../../boltrig/kernel/health_routes.py)
`"f\"{tenant}/{adapter}\": value"`).

RISK: cookie deletion at logout is written with `path="/"`
([`boltrig/api/auth_routes.py:544`](../../../boltrig/api/auth_routes.py)
`"resp.delete_cookie(SESSION_COOKIE, path=\"/\")"`) and then rewritten by
`MountPathCookieMiddleware` using the CURRENT request's forwarded prefix
([`boltrig/kernel/web_security.py:159`](../../../boltrig/kernel/web_security.py)
`"scoped = [scope_set_cookie(c, prefix) for c in cookies]"`); if the prefix or its
trust flag changes between login and logout, the delete targets a different Path and
the live session cookie survives in the browser.

RISK: `MountPathCookieMiddleware` and `SecurityHeadersMiddleware` are
`BaseHTTPMiddleware` subclasses wrapping SSE routes; the ASGI-level body cap was
explicitly rewritten to avoid blocking SSE GETs
([`boltrig/kernel/web_security.py:248`](../../../boltrig/kernel/web_security.py)
`"Methods that do not carry a body can skip the buffering path."`), but no equivalent note or
test exists for the two `BaseHTTPMiddleware` layers that stream every event through a
queue.

RISK: 81 routes enforce authorship in the transport with `require_author(p)`, which
contradicts this area's own stated design that no policy lives here
([`boltrig/kernel/app.py:4`](../../../boltrig/kernel/app.py) `"no policy lives in this module"`,
against [`boltrig/kernel/platform_routes/_shared.py:17`](../../../boltrig/kernel/platform_routes/_shared.py)
`"def require_author(p) -> None:"`). For the six routes that both call it and never
dispatch, it is the ONLY authorisation.

RISK: 17 state-changing routes neither dispatch nor write an audit row, including
`DELETE /v1/trajectory/{run_id}` (a verbatim record purge, deliberately available to
any reader per [`boltrig/kernel/trajectory_routes.py:104`](../../../boltrig/kernel/trajectory_routes.py)
`"Deliberately available to whoever can read it"`) and `PUT /v1/conversations/{conversation_id}/queue`.

RISK: `WEB-02/03/05/06`, `RES-01`, `US-HEAD-02`, `SEC-02`, `K-3` and `IAM-09` are cited
in this area's source as if they were invariants but are not declared in
`tests/invariants.yaml`, so the ratchet cannot notice their removal.

RISK: the mount-path cookie scoping, a security control with its own 11-test file, is
bound to no invariant id (`rg -c 'pytest.mark.invariant' tests/security/test_mount_path_cookie_scope.py`
returns 0).

RISK: an invalid MCP run token yields HTTP 200 with a JSON-RPC error rather than 401
([`boltrig/kernel/app.py:401`](../../../boltrig/kernel/app.py) `"result = await k.mcp.handle(run_token, body"`,
[`boltrig/kernel/mcp.py:177`](../../../boltrig/kernel/mcp.py) `"return _err(request.get(\"id\"), -32001, \"invalid or expired run"`), so an HTTP-level
monitor or WAF sees authentication failures as successes.

RISK: `POST /v1/skills/{skill_id}/test-spawn` is registered twice, once plain and once
with `{skill_id:path}` ([`boltrig/kernel/platform_routes/skill_write_routes.py:88`](../../../boltrig/kernel/platform_routes/skill_write_routes.py) `"async def test_spawn("`
and [`:93`](../../../boltrig/kernel/platform_routes/skill_write_routes.py)); the
`:path` converter matches slashes, so the two overlap and only the first-registered
wins for a single-segment id.

RISK: `_ensure_control_plane` will BUILD and register a control-plane adapter at
request time if none exists ([`boltrig/kernel/control_routes.py:30`](../../../boltrig/kernel/control_routes.py)
`"from boltrig.config.control_plane import build_control_plane_adapter"`), so a
misconfigured production composition silently self-heals into a working write path
instead of failing loudly.

RISK: `SameSite` drops to `None` for any origin that is BOTH in
`DESKTOP_WEBVIEW_ORIGINS` and in `BOLTRIG_CORS_ORIGINS`
([`boltrig/api/desktop_session_auth.py:30`](../../../boltrig/api/desktop_session_auth.py)
`"return origin in DESKTOP_WEBVIEW_ORIGINS and origin in configured"`), and that env
var is read directly from `os.environ` inside the predicate rather than from the
config layer, so it can drift from what `install_security` was given.

## 12. OPEN QUESTIONS

1. Does `TrustedHostMiddleware` treat a list CONTAINING `"*"` as allow-any? The guard
   in this tree only rejects the exact list `["*"]`. Starlette 1.6.0 is pinned
   ([`requirements-lock.txt:3283`](../../../requirements-lock.txt) `"starlette==1.6.0"`)
   but is not vendored, so its behaviour cannot be read from the pinned tree. Settled
   by reading `starlette/middleware/trustedhost.py` at 1.6.0.
2. Is the off-dispatch device/call/gateway family a deliberate carve-out or drift? No
   decision record naming it was found (bounded: `rg -n 'add_api_route|off-dispatch|side door' docs/`
   was not run to exhaustion). Settled by locating decision 0016 (desktop hands) and
   decision 0003 (channels) and reading whether they authorise direct store writes.
3. Does any deployed reverse proxy actually set `X-Forwarded-Prefix`, and is
   `BOLTRIG_TRUST_FORWARDED_PREFIX` set anywhere? Not answerable from the pinned tree;
   settled by reading the live Caddy/compose config for a tenant box.
4. Are the SSE routes measured under `BaseHTTPMiddleware`? No test in `tests/` names
   both an SSE route and `install_security` (bounded:
   `rg -ln 'web_security|install_security' tests/` returned 5 files, none of which is
   an SSE test). Settled by an integration test that streams `/v1/runs/{id}/events`
   through the full middleware stack.
5. What is the actual `_dev_principal` blast radius in the beelink and canary stacks?
   The resolver defaults `role` to `org-admin` and `grants` to `["*"]`
   ([`boltrig/kernel/app.py:169`](../../../boltrig/kernel/app.py) `"role = h.get(\"x-boltrig-role\", \"org-admin\")"`); whether any live
   stack has `BOLTRIG_DEV_AUTH=1` without a production signal is a deployment fact,
   not a tree fact.
6. Does `k.mcp.handle_user` apply the same rate limits as the run-token path? The
   dispatch body of `MCPServer._dispatch` was not read in prose here; both paths call
   it with a `RunToken`, but whether the synthesised `lease_id="user-request"` token
   is bucketed separately is unverified. Settled by reading
   [`boltrig/kernel/mcp.py`](../../../boltrig/kernel/mcp.py) `_dispatch` in full.
7. For the 133 GET routes, most of which read the store directly, is department and workspace
   scoping pushed INTO the store query in every case, or does any handler load then
   filter? `SEC-69` proves it for the observability and work reads; the remainder were
   checked only at the AST level.

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0200 | The kernel exposes exactly one FastAPI application, built by `create_app`, carrying 294 routes registered from `boltrig/kernel/`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:291` `"app = FastAPI(title=\"Boltrig Kernel\""`; AST census of 246 decorator plus 48 expanded `add_api_route` registrations. No test asserts the route count (bounded: `rg -n 'app.routes' tests/`). | - |
| BT-REQ-0201 | `create_app` refuses to construct with no `principal_resolver` when a production signal is present. | IMPLEMENTED | `boltrig/kernel/app.py:257` `"FATAL: create_app() received no principal_resolver"` | SEC-60 |
| BT-REQ-0202 | With no auth configured and no dev-auth flag, the selected resolver refuses every request with 401. | IMPLEMENTED | `boltrig/api/bootstrap.py:496` `"authentication is not configured"` | SEC-01 |
| BT-REQ-0203 | Identity is taken only from a verified credential; a request body can never set tenant, subject, role, scope or grants. | IMPLEMENTED | `boltrig/kernel/app.py:6` `"handlers never read tenant/identity from"`; `boltrig/identity/sessions.py:13` `"verified session, never from the request body (SEC-02)."` | SEC-01 |
| BT-REQ-0204 | Eight reserved context keys supplied by a caller are dropped before the context is built. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:113` `"RESERVED_CONTEXT_KEYS = frozenset("` ; no test found naming the constant (bounded: `rg -n 'RESERVED_CONTEXT_KEYS' tests/`, 0 hits) | - |
| BT-REQ-0205 | A PAT bearer resolves before the configured resolver and yields the owner's effective grants. | IMPLEMENTED | `boltrig/kernel/bearer_principal.py:54` `"if not (token and looks_like_pat(token)):"` | SEC-37 |
| BT-REQ-0206 | A PAT naming a workspace its owner does not belong to is refused 403, never silently unscoped. | IMPLEMENTED-UNTESTED | `boltrig/kernel/bearer_principal.py:67` `"not a member of that workspace"` | - |
| BT-REQ-0207 | An invalid or expired PAT is refused 401. | IMPLEMENTED | `boltrig/kernel/bearer_principal.py:69` `"invalid or expired access token"` | SEC-01 |
| BT-REQ-0208 | Every mutating cookie-authenticated request must echo the session-bound CSRF token in `x-boltrig-csrf`, compared in constant time. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:309` `"hmac.compare_digest("` ; tests exist in `tests/security/test_first_party_login.py` but were not opened | - |
| BT-REQ-0209 | Bearer and PAT callers are never CSRF-gated, because the PAT branch returns before the session resolver runs. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:306` `"Bearer/PAT auth never reaches here, so it is not CSRF-gated."` | - |
| BT-REQ-0210 | A session whose user must change password is clamped to a three-path allowlist. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:319` `"if user.must_change_password"` | - |
| BT-REQ-0211 | A session in an org that requires 2FA, with no enrolled factor, is clamped to a four-path allowlist and refused 403 elsewhere. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:343` `"two_factor_enrollment_required"` | - |
| BT-REQ-0212 | The active workspace is re-authorised against current membership on every request and drops to None fail-closed. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:351` `"resolve_active_workspace("` | - |
| BT-REQ-0213 | Request provenance (`ip_address`, `user_agent`) is stamped at the door from the request, never from a body field. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:328` `"p.ip_address = _client_ip(request)"` | - |
| BT-REQ-0214 | `CF-Connecting-IP` is honoured only under `BOLTRIG_TRUST_CF_CONNECTING_IP`; `X-Forwarded-For` is never trusted. | IMPLEMENTED-UNTESTED | `boltrig/kernel/web_security.py:70` `"if is_truthy(os.environ.get(\"BOLTRIG_TRUST_CF_CONNECTING_IP\")):"` | - |
| BT-REQ-0215 | The RLS tenant is bound to the resolved principal's tenant before any handler runs. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:332` `"set_current_tenant(p.tenant_id)"` | - |
| BT-REQ-0216 | Every `BoltrigError` reaching the transport renders one envelope: `{"status","reason"}`, with 403 alone mapped to `denied`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:303` `"@app.exception_handler(BoltrigError)"` | - |
| BT-REQ-0217 | `POST /v1/invoke` refuses a body-asserted run id owned by another subject with 403 before dispatch. | IMPLEMENTED | `boltrig/kernel/app.py:348` `"if await foreign_run_asserted(k.store, p, body.context):"` | SEC-186 |
| BT-REQ-0218 | Both `run_id` and `parent_run_id` are fenced by the same predicate. | IMPLEMENTED | `boltrig/kernel/run_access.py:130` `"for key in (\"run_id\", \"parent_run_id\"):"` | SEC-186 |
| BT-REQ-0219 | A caller-supplied spawn depth is clamped to a non-negative integer and never raises. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:207` `"def _depth_from(raw: Any) -> int:"` | - |
| BT-REQ-0220 | `PendingHuman` renders 202 with the HITL request id, and `DegradedMode` renders 503 with a partial output, on both `/v1/invoke` and every `dispatch_control_route` caller. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:366` `"except PendingHuman as e:"`, `boltrig/kernel/control_routes.py:111` `"except PendingHuman as exc:"` | SEC-14 |
| BT-REQ-0221 | A JSON-RPC notification at `POST /v1/mcp` is answered 202 with an empty body, never a response frame. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:158` `"if isinstance(body, dict) and body.get(\"id\") is None:"` | - |
| BT-REQ-0222 | `POST /v1/mcp` accepts a run token from `x-boltrig-mcp-token` or from a bearer that `is_run_token` recognises, else it resolves a full principal. | IMPLEMENTED | `boltrig/kernel/app.py:390` `"run_token = request.headers.get(\"x-boltrig-mcp-token\")"` | SEC-37 |
| BT-REQ-0223 | A user-authenticated MCP call is scoped to the caller's effective grants through the same chokepoint as the site. | IMPLEMENTED | `boltrig/kernel/mcp.py:184` `"a transient connection"` | SEC-37 |
| BT-REQ-0224 | An invalid MCP run token records an `MCP_AUTH_FAILURE` security event under a reserved tenant marker. | IMPLEMENTED-UNTESTED | `boltrig/kernel/mcp.py:172` `"\"_unauthenticated\", SecurityEventType.MCP_AUTH_FAILURE"` | - |
| BT-REQ-0225 | `/v1/chat` pulls the first stream event before responding so an authorisation error renders as an envelope, not inside a half-open SSE stream. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:437` `"first = await gen.__anext__()"` | - |
| BT-REQ-0226 | A mid-run chat steer is acknowledged 202 `queued`, not as SSE. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:442` `"if first is not None and first.get(\"type\") == \"queued\":"` | - |
| BT-REQ-0227 | `/v1/work` clamps the page size at the store and returns a keyset `next_cursor` only when the page came back full. | IMPLEMENTED | `boltrig/kernel/app.py:586` `"next_cursor = items[-1].id if len(items) == page else None"` | SEC-69 |
| BT-REQ-0228 | A work item outside the caller's departments is answered 404, not 403. | IMPLEMENTED | `boltrig/kernel/app.py:617` `"return JSONResponse({\"error\": \"not_found\"}, status_code=404)"` | SEC-33 |
| BT-REQ-0229 | `/v1/runs/{run_id}/events` authorises with `visible_run_events` and 404s an unknown or out-of-scope run before streaming. | IMPLEMENTED | `boltrig/kernel/app.py:663` `"rows = await visible_run_events(k.store, p, run_id)"` | SEC-56 |
| BT-REQ-0230 | The `?since` cursor on the run stream can only narrow the replay, never widen what a run exposes. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:676` `"cursor = since if (since is not None and since >= 0) else None"` | SEC-56 |
| BT-REQ-0231 | `GET /v1/conversations/search` is registered before `GET /v1/conversations/{conversation_id}` so `search` is never captured as an id. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:500` `"Registered BEFORE the /{conversation_id}"` | - |
| BT-REQ-0232 | Exactly three routes are reachable without authentication: `/v1/branding`, `/healthz`, `/readyz`, and they live in one file. | IMPLEMENTED-UNTESTED | `boltrig/kernel/health_routes.py:1` `"The unauthenticated routes, all of them, in one file."` | SEC-38 |
| BT-REQ-0233 | `/healthz` never awaits live adapter I/O, reading a cached snapshot instead. | IMPLEMENTED-UNTESTED | `boltrig/adapters/loader.py:95` `"reads this and must never await live adapter"` | - |
| BT-REQ-0234 | `install_security` installs, in reverse-add order, TrustedHost, then CORS when configured, then security headers, then the cookie rewriter, then the body cap. | IMPLEMENTED | `boltrig/kernel/web_security.py:309` `"Starlette runs middleware in reverse add order"` | SEC-58 |
| BT-REQ-0235 | Seven security headers are stamped on every response with `setdefault`. | IMPLEMENTED | `boltrig/kernel/web_security.py:198` `"for k, v in _SECURITY_HEADERS.items():"` | SEC-58 |
| BT-REQ-0236 | The API CSP is `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`. | IMPLEMENTED | `boltrig/kernel/web_security.py:31` `"_CSP = ("` | SEC-58 |
| BT-REQ-0237 | CORS is installed only when `BOLTRIG_CORS_ORIGINS` is non-empty, never reflects Origin, and never pairs `*` with credentials. | IMPLEMENTED | `boltrig/kernel/web_security.py:314` `"Explicit allowlist only - never '*' with credentials, never reflect."` | SEC-58 |
| BT-REQ-0238 | The CORS `allow_headers` allowlist contains five entries and omits `idempotency-key` and `x-boltrig-workspace`, which kernel handlers read. | IMPLEMENTED-UNTESTED | `boltrig/kernel/web_security.py:320` `"allow_headers=["` against `boltrig/kernel/control_routes.py:75` `"idempotency-key"` | - |
| BT-REQ-0239 | A wildcard host allowlist under a production signal is a fatal boot error. | IMPLEMENTED | `boltrig/kernel/web_security.py:299` `"FATAL: BOLTRIG_ALLOWED_HOSTS is '*' in production."` | SEC-58 |
| BT-REQ-0240 | A declared or streamed body over the cap is rejected 413; a non-integer Content-Length is rejected 400. | IMPLEMENTED | `boltrig/kernel/web_security.py:240` `"payload_too_large"`, `:243` `"bad_content_length"` | SEC-58 |
| BT-REQ-0241 | The streaming body cap is applied only to POST, PUT and PATCH, so a chunked body on any other method is uncounted. | IMPLEMENTED-UNTESTED | `boltrig/kernel/web_security.py:221` `"_BODY_METHODS = frozenset({\"POST\", \"PUT\", \"PATCH\"})"` | - |
| BT-REQ-0242 | Paths under `/v1/knowledge/uploads/` get a 25 MiB cap by prefix match instead of the global cap. | IMPLEMENTED-UNTESTED | `boltrig/kernel/web_security.py:172` `"_PATH_BODY_CAPS = ((\"/v1/knowledge/uploads/\""` | - |
| BT-REQ-0243 | Only the two session cookies are re-scoped by the mount-path middleware, and only under `BOLTRIG_TRUST_FORWARDED_PREFIX`. | IMPLEMENTED | `boltrig/kernel/web_security.py:96` `"_SCOPED_COOKIES = frozenset({\"boltrig_session\", \"boltrig_csrf\"})"`; `tests/security/test_mount_path_cookie_scope.py::test_the_header_is_ignored_without_the_deployment_opt_in` | - |
| BT-REQ-0244 | An unrecognised forwarded prefix is ignored, which returns the cookie to `Path=/`, a widening the code names as failing open. | IMPLEMENTED | `boltrig/kernel/web_security.py:105` `"The conservative choice failed OPEN"`; `tests/security/test_mount_path_cookie_scope.py::test_a_prefix_we_do_not_recognise_is_not_honoured` | - |
| BT-REQ-0245 | The mount-path cookie control is bound to no invariant id. | IMPLEMENTED-UNTESTED | `rg -c 'pytest.mark.invariant' tests/security/test_mount_path_cookie_scope.py` returns 0, 2026-08-24, pinned tree | - |
| BT-REQ-0246 | HTTP-layer rate limiting exists on exactly three ingress paths: channel inbound (per channel and per sender), channel self-onboarding, and the public workflow webhook. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_routes.py:60` `"INBOUND_RL_PER_CHANNEL = RateLimit(per=\"minute\", max=120"`, `boltrig/kernel/workflow_trigger_public_routes.py:21` `"WEBHOOK_TRIGGER_RL = RateLimit(per=\"minute\", max=30"` | FR-KER-05 |
| BT-REQ-0247 | No middleware applies a global per-IP or per-principal request rate limit. | IMPLEMENTED-UNTESTED | bounded: `rg -n 'rate_limiter\|RateLimit(' boltrig/kernel/web_security.py boltrig/kernel/app.py`, 2026-08-24, zero hits | - |
| BT-REQ-0248 | Rate-limit windows are FIXED calendar windows, so a bound admits up to twice `max` across a boundary. | IMPLEMENTED | `boltrig/kernel/ratelimit.py:17` `"WINDOW SEMANTICS, stated here because callers configure against it"`; `tests/security/test_two_factor.py::test_the_window_is_fixed_not_sliding` | FR-KER-05 |
| BT-REQ-0249 | The public workflow webhook deduplicates before throttling and throttles before the trigger lookup. | IMPLEMENTED-UNTESTED | `boltrig/kernel/workflow_trigger_public_routes.py:79` `"Dedup BEFORE the throttle"` | - |
| BT-REQ-0250 | The public workflow webhook synthesises its principal from the trigger owner and intersects with the trigger's stored grant ceiling. | IMPLEMENTED-UNTESTED | `boltrig/kernel/workflow_trigger_delivery.py:81` `"bounded = current.intersect(trigger.grant_ceiling)"` | - |
| BT-REQ-0251 | The public workflow webhook reaches the dispatcher through `control.workflow.trigger`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/workflow_trigger_delivery.py:237` `"output, pending = await dispatch_control_route("` | - |
| BT-REQ-0252 | Channel inbound authenticates by HMAC over the RAW wire bytes, not the parsed body. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_inbound_routes.py:89` `"raw_body = await request.body()"` | - |
| BT-REQ-0253 | A channel thread ceiling can only narrow the resolved principal's grants. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_inbound_routes.py:161` `"grants=principal.grants.intersect(ceiling)"` | - |
| BT-REQ-0254 | Channel inbound creates a work item by direct store write, with no dispatcher call. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_inbound_routes.py:191` `"await kernel.store.create_work_item(item)"` | - |
| BT-REQ-0255 | The nine channel and call gateway routes authenticate with a run token that must carry `extra.channel_gateway`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_gateway_auth.py:16` `"if token is None or not (token.extra or {}).get(\"channel_gateway\"):"` | - |
| BT-REQ-0256 | A minted gateway session carries an EMPTY `GrantSet`, so presenting it at `/v1/mcp` grants nothing. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_gateway_session_routes.py:51` `"GrantSet(),"` | - |
| BT-REQ-0257 | Minting a gateway session requires an authoring role and is audited. | IMPLEMENTED-UNTESTED | `boltrig/kernel/channel_gateway_session_routes.py:15` `"if not can_author(principal.role):"`, `:100` `"await kernel.audit.write("` | SEC-32 |
| BT-REQ-0258 | The eleven device-agent and camera-agent routes authenticate with a scoped device session bearer whose device id must match the path. | IMPLEMENTED-UNTESTED | `boltrig/kernel/device_route_support.py` `"if token_device_id != device_id:"` | - |
| BT-REQ-0259 | Device enrollment completion authenticates with a one-shot scoped enrollment code carried in the body. | IMPLEMENTED-UNTESTED | `boltrig/kernel/device_agent_routes.py:45` `"parse_scoped_token(code, \"device_enrollment\")"` | - |
| BT-REQ-0260 | `GET /v1/hands/commands` claims each command on return so a second poll cannot double-execute it. | IMPLEMENTED-UNTESTED | `boltrig/kernel/desktop_routes.py:59` `"so the read+mark is atomic on the kernel loop."` | - |
| BT-REQ-0261 | A desktop receipt for an unknown or expired command is refused 404 and is not audited. | IMPLEMENTED-UNTESTED | `boltrig/kernel/desktop_routes.py:82` `"do not audit a no-op as execution"` | SEC-16 |
| BT-REQ-0262 | Every desktop receipt that lands is audited with a truncated error string. | IMPLEMENTED-UNTESTED | `boltrig/kernel/desktop_routes.py:86` `"detail[\"error\"] = receipt[\"error\"][:_MAX_ERROR_LEN]"` | SEC-16 |
| BT-REQ-0263 | `dispatch_control_route` lets the `x-boltrig-approval-id` and `idempotency-key` headers override the same body fields. | IMPLEMENTED-UNTESTED | `boltrig/kernel/control_routes.py:74` `"request.headers.get(\"x-boltrig-approval-id\") or approval_id"` | - |
| BT-REQ-0264 | `dispatch_control_route` builds and registers a control-plane adapter at request time when the tenant has none. | IMPLEMENTED-UNTESTED | `boltrig/kernel/control_routes.py:32` `"adapter = build_control_plane_adapter("` | - |
| BT-REQ-0265 | Held-call settlement after an approved control write is swallowed so cleanup cannot turn a committed write into a client error. | IMPLEMENTED-UNTESTED | `boltrig/kernel/control_routes.py:106` `"except Exception:"` | - |
| BT-REQ-0266 | A HITL approval response goes through `kernel.hitl.answer`, never the dispatcher, and a non-approval decision is wrapped as untrusted text first. | IMPLEMENTED-UNTESTED | `boltrig/kernel/hitl_http.py:185` `"decision = wrap_untrusted(\"hitl_response\", principal.subject, decision)"` | SEC-14 |
| BT-REQ-0267 | `POST /v1/hitl/{question_id}/answer` answers only a QUESTION, never an approval, and refuses a non-owner 403 with no write. | IMPLEMENTED-UNTESTED | `boltrig/kernel/hitl_http.py:251` `"if req.type != HITLType.QUESTION:"`, `:255` `"item.on_behalf_of != principal.subject"` | SEC-14 |
| BT-REQ-0268 | A SECURE question's answer is sealed inside the kernel and only its reference is recorded; even its length is withheld. | IMPLEMENTED-UNTESTED | `boltrig/kernel/hitl_http.py:271` `"reference = await kernel.credentials.seal_run_scoped_value("` | K-20 |
| BT-REQ-0269 | A sole-author or development-posture approval always leaves a distinguishing audit row. | IMPLEMENTED-UNTESTED | `boltrig/kernel/hitl_http.py:203` `"await kernel.audit.write("` | SEC-16 |
| BT-REQ-0270 | `POST /v1/runs/{run_id}/cancel` is owner-only, writes a cooperative cancel signal, audits it, and never interrupts an in-flight step. | IMPLEMENTED-UNTESTED | `boltrig/kernel/access_routes.py:267` `"await k.store.request_run_cancel("` | - |
| BT-REQ-0271 | `POST /v1/me/active-context` and `/v1/me/active-org` require a first-party session, re-authorise membership, and refuse with no write and no audit when it fails. | IMPLEMENTED-UNTESTED | `boltrig/kernel/access_routes.py:430` `"if not any(w.id == workspace_id for w in memberships):"`, `:483` `"member = await k.store.get_org_member("` | - |
| BT-REQ-0272 | Session writes bind the identity realm for the write and restore the caller's active tenant in a `finally`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/access_routes.py:441` `"set_current_tenant(session.tenant_id)"` | - |
| BT-REQ-0273 | A minted PAT's secret is returned exactly once in the mint response and never stored in the clear. | IMPLEMENTED | `boltrig/kernel/access_routes.py:308` `"view[\"secret\"] = secret  # shown ONCE"` | SEC-34 |
| BT-REQ-0274 | PAT and session revocation routes refuse another user's row with 404, not 403. | IMPLEMENTED-UNTESTED | `boltrig/kernel/access_routes.py:314` `"if pat is None or pat.user_id != p.subject:"` | SEC-34 |
| BT-REQ-0275 | Memory MUTATION routes run the chokepoint with server-derived scopes in `trusted_extra`. | IMPLEMENTED | `boltrig/kernel/memory_mutation_routes.py:18` `"return p.context(trusted_extra={\"memory_scopes\": memory_scopes(p)})"` | SEC-40 |
| BT-REQ-0276 | Memory READ routes query the store directly under `memory_owner_scopes`, without the chokepoint. | IMPLEMENTED-UNTESTED | `boltrig/kernel/memory_read_routes.py:33` `"facts = await k.store.list_memory_facts("` | SEC-69 |
| BT-REQ-0277 | `POST /v1/memory/query` reads the store directly with no dispatch and no audit row. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/memory.py:11` `"items = await k.store.query_memory("` | - |
| BT-REQ-0278 | 81 routes enforce authorship in the transport by calling `require_author(p)`, which raises `GrantMissing`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/_shared.py:21` `"raise GrantMissing(\"authoring/admin not permitted for this role\")"`; AST count over all route handlers | SEC-32 |
| BT-REQ-0279 | 68 of 161 state-changing routes never reach `kernel.invoke` or `dispatch_control_route`. | IMPLEMENTED-UNTESTED | AST reachability over `boltrig/kernel/`, 2026-08-24, pinned tree; ten named modules return 0 for `rg -c 'kernel\.invoke\(\|k\.invoke\(\|dispatch_control_route\('` | - |
| BT-REQ-0280 | `POST /v1/ai-keys/activate` provisions an external gateway binding with no dispatch and no audit row. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ai_key_proposal_routes.py:184` `"await BifrostUserGateway().ensure("` | - |
| BT-REQ-0281 | `POST /v1/me/agent` writes a personal agent with no RBAC guard and no audit row. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/personal.py:27` `"await k.store.upsert_personal_agent(agent)"` | SEC-30 |
| BT-REQ-0282 | `POST /v1/me/agent/invoke` spawns only on behalf of the owner and is capped by the owner's grants. | IMPLEMENTED | `boltrig/kernel/platform_routes/personal.py:74` `"grant_ceiling=p.grants,"` | SEC-30 |
| BT-REQ-0283 | Test-spawn and eval routes require an authoring role and run under the initiator's grants. | IMPLEMENTED | `boltrig/kernel/platform_routes/eval_routes.py:35` `"require_author(p)"`, `:51` `"grants=p.grants,"` | SEC-29 |
| BT-REQ-0284 | `POST /v1/integrations/{integration_id}/oauth/start` always answers 409 `unsupported`; no OAuth flow exists. | SCAFFOLDED | `boltrig/kernel/platform_routes/integration_setup.py:159` `"\"status\": \"unsupported\","` | - |
| BT-REQ-0285 | `GET /v1/admin/credentials` returns credential references only, never values. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/admin.py:116` `"# refs only, never values"` | - |
| BT-REQ-0286 | `PUT /v1/me/approval-posture` and the three sensing writes require `actor_tier == "human"` and an interactive credential kind. | IMPLEMENTED-UNTESTED | `boltrig/kernel/approval_posture_routes.py:25` `"if p.actor_tier != \"human\" or not is_interactive_credential(p.credential_kind):"` | - |
| BT-REQ-0287 | Selecting FULL_ACCESS approval posture additionally requires an explicit `confirm` value. | IMPLEMENTED-UNTESTED | `boltrig/kernel/approval_posture_routes.py:40` `"body.get(\"confirm\") != \"full_access\""` | - |
| BT-REQ-0288 | `DELETE /v1/trajectory/{run_id}` purges the verbatim record for anyone who can read it, leaves the audit row untouched, and writes no audit row of its own. | IMPLEMENTED-UNTESTED | `boltrig/kernel/trajectory_routes.py:104` `"Deliberately available to whoever can read it"` | - |
| BT-REQ-0289 | The two familiar emotion routes publish inert relay frames and import nothing from the emotion add-on. | IMPLEMENTED-UNTESTED | `boltrig/kernel/familiar_phenotype_routes.py:101` `"k.events.publish(p.tenant_id, \"emotion\""` | - |
| BT-REQ-0290 | An injected service that is absent yields a typed 503, never a 500. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:413` `"chat_unavailable"`, `:534` `"spawner_unavailable"`, `boltrig/kernel/desktop_routes.py:56` `"hands_unavailable"` | - |
| BT-REQ-0291 | Only four routes bind a Pydantic request model; every other state-changing route takes an untyped `body: dict` or no body at all and validates by hand. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app_bodies.py:1` `"The typed request bodies the kernel HTTP door accepts."`; AST census of handler annotations | - |
| BT-REQ-0292 | `WEB-02`, `WEB-03`, `WEB-05`, `WEB-06`, `RES-01`, `US-HEAD-02`, `SEC-02`, `K-3` and `IAM-09` are cited in this area's source but are not declared in `tests/invariants.yaml`. | IMPLEMENTED-UNTESTED | bounded: `grep -n '^  <ID>:$' tests/invariants.yaml` for each id, 2026-08-24, pinned tree, zero hits each | - |
| BT-REQ-0293 | `POST /v1/skills/{skill_id}/test-spawn` is registered twice, once plain and once with a `:path` converter that overlaps it. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/skill_write_routes.py:88` `"async def test_spawn("` and `:93` `"@app.post(\"/v1/skills/{skill_id:path}/test-spawn\")"` | - |
| BT-REQ-0294 | Session cookies drop to `SameSite=None` for an origin that is both a known desktop webview origin and present in `BOLTRIG_CORS_ORIGINS`. | IMPLEMENTED-UNTESTED | `boltrig/api/desktop_session_auth.py:42` `"same_site = \"none\" if secure and _desktop_session_request(request) else \"strict\""` | - |
| BT-REQ-0295 | `/healthz` discloses tenant ids and adapter names without authentication. | IMPLEMENTED-UNTESTED | `boltrig/kernel/health_routes.py:37` `"f\"{tenant}/{adapter}\": value"` | - |
