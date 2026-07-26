# Boltrig SDK Contract, derived from Opbox's real surface needs

Status: specification (not code). Author target: the boltrig agent building the two SDKs now.
Goal: cover every boltrig primitive so any app frontend (Opbox first, others later) surfaces the
full capability set instead of bespoke-reading `/v1/*`, and so any app backend exposes its verbs to a
boltrig kernel with per-user execution parity out of the box.

Boltrig is the agent-of-record UNDER apps. Two SDKs sit either side of the kernel chokepoint:

- Kernel SDK (backend): `sdks/node/` = package `boltrig-app-sdk`. Already exists. How an app exposes
  its verbs to a boltrig kernel and how boltrig calls back to execute them. See
  `sdks/node/src/{server,register,head,http,index}.ts` and README.
- UI SDK (frontend): being built now. A client library exposing every boltrig primitive so a frontend
  renders runs/chats/HITL/cost/etc. The reference implementation already exists inside the boltrig
  console at `ui/src/api/` (`transport.ts`, `sse.ts`, `types.ts`, `domains/*.ts`, `api.ts`) plus the
  turn reducer `ui/src/panels/chatTurnNormalizer.ts` + `chatTurnTypes.ts`. The UI SDK is the
  extraction/generalization of that console client into a framework-agnostic package.

---

## 0. Critical framing: there are TWO kernels. Do not conflate them.

This is the single most load-bearing fact for the whole contract.

- BOLTRIG kernel: the AI agent runtime. `BOLTRIG_KERNEL_URL` (default `http://localhost:8000`). Speaks
  the `/v1/*` REST + SSE surface enumerated in section 1. This is what BOTH SDKs are about.
- OPBOX unitary-stack kernel: the Rust kernel (`KERNEL_URL`, default `http://kernel:8088`). Reached by
  opbox via `dispatch(verb, args, {bearer})` from `@/lib/kernel/client`. Opbox's Agent Centre,
  per-matter agents, workflows, and roster/HITL all currently go HERE via named verbs
  (`org.agent.list`, `agenttask.list`, `oversight.escalate`, ...), NOT boltrig primitives.

Consequence: today only opbox's conversational chat path and account provisioning touch boltrig `/v1/*`
(and behind an off-by-default build flag `NEXT_PUBLIC_USE_KERNEL_CHAT`). Most "agent ops" surfaces are
wired to the opbox Rust kernel. The UI SDK's job is to make the boltrig primitive set first-class in
app frontends so those surfaces CAN be re-expressed over boltrig (agent-of-record) without each app
re-deriving `/v1/*` by hand. Section 5 tracks the surfaces that are net-new-over-boltrig vs re-point.

Terminology note: the task calls the per-user downstream credential the "runBearer". In the code the
literal token `runBearer` does not exist. It is the `on_behalf_bearer` field on the `/v1/chat` body
(`boltrig/kernel/app.py:231`), sealed per-run as a run-scoped adapter bearer
(`boltrig/kernel/credentials.py:213 seal_run_scoped_adapter_bearer`), resolved at dispatch into the
adapter `credential` (`boltrig/kernel/dispatch.py:474 resolve_run_scoped_credential`), and presented on
the wire to the app's verb server as `x-boltrig-mcp-token: <bearer>` (and `Authorization: Bearer`)
by `boltrig/adapters/mcp_transport.py:126 _headers`. This doc uses "OBO bearer" for that value.

---

## 1. The full boltrig primitive surface (the UI SDK checklist)

Every `/v1/*` path is mounted with NO per-router prefix: the decorator path is the full path
(`boltrig/kernel/app.py:790-837` register the platform/access/auth/memory/channel/gateway/desktop
routers, each hard-coding its own `/v1/...`). Global auth: every handler with `p=Depends(principal)`
requires an authenticated caller; a `Bearer` that looks like a PAT resolves to `PAT scope ∩ owner
grants` (`app.py:359-387`), else the configured resolver (OIDC prod / header-trusting dev). `Principal`
carries `tenant_id, subject, grants, role, actor_tier, on_behalf_of, scope, active_workspace_id`.

Scoping vocabulary used in the Auth column below:
- tenant: universal tenant isolation (`p.tenant_id` + Postgres RLS).
- owner=user:email: owner-scoped to the caller (`on_behalf_of`/`user_id == subject`, memory
  `owner_scope = user:<email>`).
- dept: department isolation via `departments_for(role, scope)`.
- ws: workspace fence via `p.active_workspace_id`.
- author: `can_author(role)` (author/admin) gate.
- admin: `_ADMIN_ROLES = {org-admin, superadmin, admin}`.

### 1.1 Conversations and Turns (chat)

| Primitive | Endpoint(s) | Shape (key fields) | Auth/scoping |
|---|---|---|---|
| Chat turn (SSE) | `POST /v1/chat` (app.py:473) | body `{message, conversation_id?, attachments[]{name,media_type,data(b64)}, on_behalf_bearer?}`; response `text/event-stream` of ChatEvent (1.2), OR `202 {status:"queued",conversation_id,message_id,run_id}`, OR `503 {error:"chat_unavailable"}` | bearer; owner=user:email; spawn ceilinged by `p.grants` |
| List conversations | `GET /v1/conversations?limit&offset` (app.py:521) | `{conversations:[{id,title,status,updated_at}], next_offset?}` | bearer; owner |
| Search conversations | `GET /v1/conversations/search?q&limit&offset` (app.py:547) | `{results:[{id,title,status,updated_at,snippet}], next_offset}` (400 if no `q`) | bearer; owner |
| Conversation transcript | `GET /v1/conversations/{id}` (app.py:575) | `{messages:[{id,role,content,run_id,hitl_request_id,events[],attachments[],superseded_by,created_at}]}` (403 cross-owner) | bearer; owner+role |
| Delete conversation | `DELETE /v1/me/conversations/{id}` (access_routes.py:236) | `{status,id}` (404/403) | bearer; owner-only |
| Rename conversation | `PATCH /v1/me/conversations/{id}` (access_routes.py:251) | body `{title}` (1-120); `{status,id}` | bearer; owner-only |
| Regenerate turn | `POST /v1/me/conversations/{id}/messages/{mid}/regenerate` (access_routes.py:271) | `{status,conversation_id,message_id,superseded,run_id}` (409 not-eligible) | bearer; owner-only |

Note: `messages[].events[]` re-hydrate the exact same turn cards on re-open (persisted ChatEvent
stream). The persisted `ChatMessage` shape mirrors 1.2 (`ui/src/api/types.ts:259-269`).

### 1.2 The SSE frame model (the streaming contract, the heart of the UI SDK)

ONE `ChatEvent` union is emitted by BOTH `POST /v1/chat` and `GET /v1/runs/{id}/events` and reduced by
ONE reducer (`ui/src/panels/chatTurnNormalizer.ts:normalizeEvents`). Reference union at
`ui/src/api/types.ts:434-447`. Frames are `data:`-delimited JSON, blank-line framed, terminal on
`message_end`/`cancelled`; `heartbeat` and `[DONE]` are dropped, never dispatched
(`ui/src/api/sse.ts:177-201`). Idle guard `STREAM_IDLE_MS=120_000`.

| `type` | Fields (types.ts) | Meaning |
|---|---|---|
| `message_start` | `run_id, conversation_id` (307) | turn/run opened; client captures `conversation_id`/`run_id` |
| `text_delta` | `delta` (312) | append to assistant text |
| `reasoning_delta` | `delta` (316) | append to reasoning ("Thinking") |
| `tool_call` | `run_id?, tool?`(chat)/`verb?`(relay)`, call_id?, args_summary?{keys[],count}, input?`(relay only)`, status?, consequence?` (330) | tool invoked; K-20: chat stream carries keys only, full `input` only on run relay |
| `tool_result` | `run_id?, call_id?, verb?, status, result_summary?{keys?,status?}, output?`(relay only) (352) | tool settled; paired to its `tool_call` by `call_id` (fallback verb) |
| `subagent` | `child_run_id, task, skills[]?, name?, role?, color?, step_count?` (381) | delegated child run started (see GAP: no completion frame) |
| `hitl` | `hitl_request_id, kind?, question?, options[]?, verb?, call_id?, requested_by?` (394) | human input needed; `kind` in `approval|clarification|escalation|question` |
| `question` | `run_id?, question_id, prompt, choices[]?` (374) | agent clarifying question (answer path) |
| `workflow_step` | `step_id, action, status(running|ok|failed|skipped|paused|error)` (417) | one workflow node settle |
| `workflow_run` | `run_id, workflow_id, status(completed|failed|paused)` (427) | run-level settle marker |
| `heartbeat` | `run_id?` (366) | keep-alive, dropped |
| `message_end` | `run_id` (404) | terminal (no token usage, see GAP) |
| `cancelled` | `run_id` (410) | terminal from cancel |

Normalized turn (`chatTurnTypes.ts:73-86`): `{runId?, conversationId?, text, reasoning, tools[],
subagents[], hitls[], questions[], steps[], timeline[], ended, cancelled}`. `timeline[]` preserves
arrival order as a discriminated union (`tool|subagent|hitl|question|steps`). The UI SDK MUST ship this
reducer plus the per-entry card contracts (ToolEntry, SubagentEntry, HitlEntry, QuestionEntry,
StepEntry) so every consuming frontend folds the stream identically. The reference Python head client
`sdks/node/src/head.ts` (`SseParser`, `streamTurn`, `renderEvent`, `respondHitl`, `answerQuestion`) is
the seed of the chat/HITL portion.

### 1.3 Runs, run-events, steps, audit tree

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| List runs | `GET /v1/runs?limit&cursor` (observability.py:343) | `{runs:[{run_id,work_item,intent,status,owner}], limit, next_cursor}` | bearer; dept+ws (keyset page) |
| Run event stream (SSE) | `GET /v1/runs/{id}/events?follow=0|1` (app.py:757) | `text/event-stream` of ChatEvent (1.2, FULL relay incl `input`/`output`); 404 unknown_run | bearer; `visible_run_events` dept+ws+work-item (run_access.py:62) |
| Cancel run | `POST /v1/runs/{id}/cancel` (access_routes.py:355) | `{status,run_id}` (404/403) | bearer; owner-only |
| Audit tree | `GET /v1/audit/tree/{run_id}` (app.py:744) | `AuditNode` recursive `{run_id,parent_run_id?,actor?,tier?,depth?,actions?,cost_micros?,total_cost_micros?,tokens?,statuses{},children[]}` (types.ts:181) | bearer; `visible_audit_tree_events` strict dept+ws (run_access.py:91) |
| Audit search | `GET /v1/audit/search?actor&verb&run&resource&status&since&until&security&event_type` (observability.py:204) | `{stream:"audit"|"security", results:[{seq,ts,actor,verb?,status?,run_id?,workspace_id?,ip_address?,user_agent?,resource?,resource_id?}], scope}` | bearer; audit=dept+ws; security arm requires author |
| Audit verify | `GET /v1/audit/verify?workspace` (observability.py:293) | `{chain_intact,chain_first_bad_seq,security_chain_intact,anchor_intact,anchor{...},intact}` | bearer; author |
| Audit export | `POST /v1/audit/export` (observability.py:327) | `{format,count,events[{seq,ts,actor,verb,status,run_id,on_behalf_of}]}` | bearer; author (self-audits) |
| My activity | `GET /v1/me/activity` (access_routes.py:204) | `{results:[{seq,ts,verb,status,run_id}]}` | bearer; owner |

### 1.4 Work-queue / Kanban (lifecycle)

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Work list | `GET /v1/work?status&limit&cursor` (app.py:639) | `{items:[WorkItem], limit, next_cursor}` | bearer; dept+ws |
| Work detail | `GET /v1/work/{id}` (app.py:691) | `{item:WorkItem, children[], audit:[{ts,actor,actor_tier,verb,noun,status,detail}]}` (404 out-of-scope) | bearer; dept+ws |

`WorkItem` (types.ts:83): `{id, intent, status, confidence?, convergent?, owner_member?, source?,
parent_id?, hatchet_run_id?, on_behalf_of?}`. Kanban lane values `WorkStatus` (types.ts:75):
`pending -> in_flight -> blocked -> awaiting_human -> done -> failed` (order at
`ui/src/panels/workBoard/model.ts:7`). Views: project (parent/child forest), linear, board.

### 1.5 Agent roster (CoS -> heads -> workers)

There is NO single roster endpoint. The console composes it (`ui/src/panels/agentsSlide/useAgentsData.ts`):

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Hierarchy (CoS+heads) | `GET /v1/admin/config/hierarchy` (admin.py:12) | `{section,value:{tier1:chief, tier2[]:heads}}` | bearer; author |
| Worker pool | `GET /v1/admin/config/ephemeral_runtimes` | config value (worker capabilities) | bearer; author |
| Model endpoints | `GET /v1/model-endpoints` (access_routes.py:650) | `{endpoints:[{id,kind,model,data_class}]}` (never base_url) | bearer; tenant |
| Skills | `GET /v1/skills` (skills.py:12) | `{skills:[{id,version,extends,tool_grants,locale}]}` | bearer; tenant |
| Capabilities | `GET /v1/capabilities?noun` (app.py:603) | grant-filtered `{verbs:[VerbInfo], nouns?, workflows?, agent_capabilities?}` | bearer; grant-filtered |
| Budgets (per agent) | `GET /v1/budgets` (budgets.py:27) | see 1.7 | bearer; dept |
| Work (per agent) | `GET /v1/work` (1.4) | see 1.4 | bearer; dept+ws |

`AgentKind = chief|head|worker`. The console derives effective grants/verbs by joining matched skills'
`tool_grants` and verbs whose `binding.target_type=="agent" && target_ref==agent.name`
(`ui/src/panels/agents/model.ts:143`). The UI SDK should expose a `roster()` helper that performs this
join so apps do not re-derive it. GAP: boltrig exposes no run/roster LIST scoped to an owning object
(matter); the live subagent topology is only the unbounded `subagent` chat frame (section 5).

### 1.6 HITL approvals

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Pending HITL | `GET /v1/hitl` (app.py:622) | `{requests:[{id,type,urgency,question,context,options,work_item_id,status,run_id,verb,requested_by,requested_on_behalf_of,inputs,secure,secure_purpose}]}` (hitl_http.py:19) | bearer; per-request visibility (`hitl_request_visible`) |
| Respond (approval/escalation/clarification) | `POST /v1/hitl/{id}/respond` (app.py:628) | body `{decision, notes?}`; `{status:"answered",response_id,sole_author_exemption?}` | bearer; human tier + anti-self-approval (SEC-14) |
| Answer (question, owner-only) | `POST /v1/hitl/{id}/answer` (access_routes.py:322) | body `{answer}`; `{status:"ok",question_id,response_id,run_id}` (409 not-a-question, 403 not-your-run) | bearer; owner-only; secure answers sealed as run-scoped credential |

`HITLKind = approval|clarification|escalation|question` (types.ts:118). The kernel `/answer` 409s a
non-QUESTION, so the UI SDK MUST route `kind==="question"` to `/answer` and everything else to
`/respond` (opbox already learned this the hard way, `boltrig-frames.ts:126-155`). Same HITL card is
reused inline in chat, in the run drawer, and in the approvals panel.

### 1.7 Cost + budgets

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Cost rollup | `GET /v1/cost` (observability.py:123) | `{total_cost_micros, by_actor{}, scope}` | bearer; dept+ws |
| Budgets | `GET /v1/budgets` (budgets.py:27) | `{budgets:[{id,scope_type(tenant|department|workflow),window(run|daily|monthly),hard_stop,token_limit,spent_tokens,cost_limit_micros,spent_micros}], scope}` | bearer; dept |
| Upsert budget | `PUT /v1/budgets/{scope_type}/{scope_id}` (budgets.py:41) | governed `control.budget.upsert` (may 202 pending) | bearer; author |
| Reset budget | `POST /v1/budgets/{scope_type}/{scope_id}/reset` (budgets.py:53) | governed `control.budget.reset` | bearer; author |
| Model telemetry | `GET /v1/model/telemetry?limit` (observability.py:182) | `{models:[...], scope}` | bearer; dept+ws |
| Console overview | `GET /v1/console/overview?limit` (console.py:176) | one-shot `{platform{components,runtimes}, models[], cost{total,by_actor,by_status}, budgets[], recent_runs[], approvals[], counts{}}` | bearer; dept+ws |

### 1.8 Workflows + workflow runs (Hatchet flows)

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| List | `GET /v1/workflows` (workflows.py:19) | `{workflows:[{id,version,source,intent_tags[]}]}` | bearer; ws-visible |
| Detail | `GET /v1/workflows/{id}` (workflows.py:38) | `{id,version,source,definition,intent_tags[]}` (404) | bearer; ws |
| Run stats | `GET /v1/workflow-stats` (workflows.py:53) | `{stats:[{workflow_id,run_count,success_count,last_run_at}]}` | bearer; tenant |
| Workflow runs | `GET /v1/workflows/{id}/runs` (workflows.py:57) | `{workflow_id, runs:[run_id]}` (each filtered via `visible_run_events`) | bearer; ws |
| Upsert | `POST /v1/workflows` (workflows.py:81) | governed `control.workflow.upsert` | bearer; author |
| Schedule | `POST /v1/workflows/{id}/schedule` (workflows.py:91) | governed `control.workflow.schedule` | bearer; author |
| Trigger | `POST /v1/workflows/{id}/trigger` (workflows.py:112) | `control.workflow.trigger` (runs under caller grants, no author gate) | bearer |
| Execute | `POST /v1/workflows/{id}/execute` (workflows.py:126) | `control.workflow.execute` | bearer |

Live run canvas overlays `workflow_step`/`workflow_run` frames (1.2) from `GET
/v1/runs/{id}/events?follow=1` onto nodes by `id===step_id`; `WorkflowRunRecord`
`{run_id,workflow_id,version,status,steps[{id,action,status,output,reason}],inputs}` (types.ts:699).

### 1.9 Memory

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Query | `POST /v1/memory/query` (memory.py:6) | body `{kind?,limit}`; `{items:[{id,owner_scope,kind,content,source_ref}], scopes}` | bearer; owner-scopes |
| Recall | `POST /v1/memory/recall` (memory_routes.py:37) | body `{query,mode(graph_completion|similarity),limit}`; `{facts?,count?,status?}` | bearer; owner-scopes |
| Remember | `POST /v1/memory/remember` (memory_routes.py:45) | `{status,fact_ids?,owner_scope?}` | bearer; owner |
| Forget | `POST /v1/memory/forget` (memory_routes.py:50) | body `{target}|{source_ref}` (400 if neither) | bearer; owner |
| Ingest | `POST /v1/memory/ingest` (memory_routes.py:64) | body `{owner_scope?,items[],source_kind?,source_ref?}`; `{status,id,ingestion_status,facts_added,screened}` (403 scope, 413 too many) | bearer; owner-scope enforced |
| Facts | `GET /v1/memory/facts?kind&limit` (memory_routes.py:94) | `{facts:[{id,owner_scope,kind,content,data_class,provenance{source_kind,source_ref,created_at}}], scopes}` | bearer; scope-filtered |
| Ingestions | `GET /v1/memory/ingestions?limit` (memory_routes.py:107) | `{ingestions:[{id,source_kind,source_ref,owner_scope,status,facts_added,screened,created_at}]}` | bearer; admin=all else own |

Disabled sentinel: `{status:"error", reason:"binding_not_found"}` -> render "memory not enabled".

### 1.10 Knowledge

All via `k.invoke("knowledge", ...)` with server-derived scopes (knowledge.py:14); owner-scope enforced
inside the verb (SEC-40).

| Primitive | Endpoint(s) | Shape |
|---|---|---|
| Upload (3-step) | `POST /v1/knowledge/uploads` -> `PUT /v1/knowledge/uploads/{id}` (b64 bytes, 413 cap) -> `POST /v1/knowledge/uploads/{id}/commit` (knowledge.py:38-60) | `{asset_id,revision_id,status,segment_count,digest,projections[]}` |
| Assets | `GET /v1/knowledge/assets?limit` (knowledge.py:62); `GET /v1/knowledge/assets/{id}` | `KnowledgeAsset{id,title,filename,asset_type,workspace_id?,revision_id,source_kind,source_ref?,segment_count,created_at}` |
| Original bytes | `GET /v1/knowledge/assets/{id}/original` (knowledge.py:70) | blob (content-disposition) |
| Search | `POST /v1/knowledge/search` (knowledge.py:81) | `hits[{asset_id,revision_id,segment_id,title,filename,text,locator,score,citation}]` |
| Context build | `POST /v1/knowledge/context` (knowledge.py:85) | retrieval context |
| Erase | `DELETE /v1/knowledge/assets/{id}` (knowledge.py:89) | may return `hitl_request_id` |
| Providers | `GET /v1/knowledge/providers`; `POST /v1/knowledge/providers/{id}` (knowledge.py:93-97) | `{id,display_name,role,enabled,bundled,health,status,last_error?}` |

Auth: bearer; owner-scope inside verb.

### 1.11 Capabilities / Registry (noun / verb / binding)

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Capabilities | `GET /v1/capabilities?noun` (app.py:603) | `{verbs:[VerbInfo{id,noun,input_schema?,output_schema?,consequence?,binding?{target_type(adapter|agent),target_ref},health?}], nouns?, workflows?, agent_capabilities?}` | bearer; grant-filtered |
| Adapter health | `GET /healthz` (app.py:389) | `{status, adapters:Record<"<tenant>/<adapterId>", ok|degraded|down|unknown>}` | none |
| Capability changelog | `GET /v1/capabilities/changelog` (observability.py:145) | `{changes:[{ts,actor,action,ref,status}]}` | bearer; author |
| Upsert noun | `POST /v1/nouns` (router.py:12) | governed `control.noun.define` | bearer; author |
| Upsert verb | `POST /v1/verbs` (router.py:22) | governed `control.verb.define` | bearer; author |
| Set binding | `POST /v1/verbs/{id}/binding` (router.py:32) | governed `control.binding.set` (invariant: one binding per verb) | bearer; author |
| Skills upsert/test | `POST /v1/skills`, `POST /v1/skills/{id}/test-spawn` (skills.py:20-32) | governed / spawner result | bearer; author |

### 1.12 Adapters

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Inventory | `GET /v1/adapters` (adapters.py:58) | `{adapters:[{id,runtime,version,source,activated,health}]}` | bearer; tenant |
| Generate | `POST /v1/adapters/generate` (adapters.py:12) | governed `control.adapter.generate` | bearer; author |
| Source | `GET /v1/adapters/{id}/source` (adapters.py:22) | `{id,source}` (404) | bearer; author |
| Activate | `POST /v1/adapters/{id}/activate` (adapters.py:30) | governed `control.adapter.activate` (high-consequence, drives HITL) | bearer; author |
| Register MCP server | `POST /v1/mcp/servers` (adapters.py:46) | governed `control.mcp_server.register` (INERT until reviewed, SEC-22) | bearer; author |

This block is exactly what the Kernel SDK `register.ts` drives (`registerMcpServer`, `activateAdapter`,
`listAdapters`). The UI SDK should expose read-side (inventory/source/health) so an app can render its
own adapter/registration state.

### 1.13 Channels

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| List | `GET /v1/channels` (channel_routes.py:421) | `{channels:[{id,platform,name,transport,enabled,unpaired_behavior}]}` | bearer; author |
| Connect/configure/disconnect | `POST /v1/channels`; `PATCH/DELETE /v1/channels/{id}` (channel_routes.py:595-654) | governed `control.channel.*` | admin |
| Pair / bindings | `POST /v1/channels/{id}/pair`; `GET/POST /v1/channels/{id}/bindings`; `DELETE .../{binding_id}` (channel_routes.py:656-759) | pairing code (show-once) / `{bindings[]}` | admin + role-rank clamp |
| Inbound (webhook) | `POST /v1/channels/{id}/inbound` (channel_routes.py:439) | 202 `{status,work_item}` | NO principal; HMAC signature |
| Gateway session/outbox | `POST /v1/channels/gateway/session`; `POST /v1/channels/gateway/outbox/{claim,ack,fail}` (channel_gateway_routes.py) | run-scoped gateway token; claim/ack/fail | admin (session) / gateway token (outbox) |

### 1.14 Me / tokens / sessions / settings / connections / personal-agent

| Primitive | Endpoint(s) | Shape | Auth/scoping |
|---|---|---|---|
| Settings | `GET/PUT /v1/me/settings` (access_routes.py:179) | `{profile{id,email,display_name,role,scope,status,source,...}, settings{}}` | bearer; self |
| Export | `GET /v1/me/export` (access_routes.py:216) | `{user,conversations[],work_items[],settings{}}` | bearer; self |
| PATs | `GET /v1/me/tokens`; `POST /v1/me/tokens`; `DELETE /v1/me/tokens/{id}` (access_routes.py:385-420) | list `{tokens:[{id,name,scope,created_at,last_used_at,expires_at,revoked}]}`; mint `{...,secret}` (shown once, capped to caller grants SEC-34) | bearer; self |
| Sessions | `GET /v1/me/sessions`; `DELETE /v1/me/sessions/{id}` (access_routes.py:460-477) | `{sessions:[{id,client,revoked,created_at,last_seen_at}]}` | bearer; self (identity realm) |
| Connections | `GET /v1/me/connections` (access_routes.py:427) | `{rest_base,mcp_endpoint,auth,snippets{claude_code,curl},note}` | bearer |
| Active context/org | `POST /v1/me/active-context`; `POST /v1/me/active-org` (access_routes.py:500-546) | `{status,workspace_id|org_id}` | bearer + first-party session |
| Notifications | `GET/PUT /v1/me/notifications` (access_routes.py:752) | `{prefs:[{id,event_type,channel,target,enabled}]}` | bearer; self |
| Personal agent | `GET/POST/DELETE /v1/me/agent`; `POST /v1/me/agent/invoke` (personal.py) | `{id,runtime(codex|script),skills[]}`; invoke -> spawner result (delegated-only SEC-30) | bearer; self |

### 1.15 Org / Workspaces / Directory / AI keys (admin)

| Primitive | Endpoint(s) | Auth |
|---|---|---|
| Org | `GET/PATCH /v1/orgs/current`; `GET /v1/orgs/current/members` (access_routes.py:906) | read=member; write=admin |
| Workspaces | `GET/POST /v1/workspaces`; `PATCH /v1/workspaces/{id}`; `GET/POST/DELETE /v1/workspaces/{id}/members[/{uid}]` (access_routes.py:951) | own; create=org-admin; manage=owner/admin |
| Users directory | `GET /v1/admin/users`; `PATCH /v1/admin/users/{id}` (access_routes.py:788) | admin + no-escalation |
| Invitations | `GET/POST /v1/admin/invitations`; `DELETE /v1/admin/invitations/{id}` (access_routes.py:821) | admin |
| AI keys | `GET /v1/ai-keys`; `PUT /v1/ai-keys`; `DELETE /v1/ai-keys/{level}/{scope_id}` (access_routes.py:663) | org=org-admin; ws/user gated by `allow_own_ai_keys` (key never echoed, `has_key` only) |

### 1.16 Direct invoke / spawn / MCP door

| Primitive | Endpoint(s) | Shape | Auth |
|---|---|---|---|
| Invoke verb | `POST /v1/invoke` (app.py:418) | body `{noun,verb,params,context,idempotency_key?,approval_id?}`; `{status:"ok",output}` / 202 pending_human / 503 degraded / canonical error | bearer; runs under `p.context` |
| Spawn subagent | `POST /v1/spawn` (app.py:611) | body `{task,skills[],prefer{},context{}}`; spawner dict | bearer; grant ceiling |
| MCP door | `POST /v1/mcp` (app.py:449) | JSON-RPC; run-token via `x-boltrig-mcp-token` OR user PAT bearer | run-token or user PAT |

### 1.17 Config / Console / Platform status / Eval / Desktop / Auth

| Primitive | Endpoint(s) | Auth |
|---|---|---|
| Config | `GET/PUT /v1/admin/config/{section}`; `.../history`; `.../rollback`; `POST /v1/admin/config/export`; `GET /v1/admin/credentials` (admin.py) | author (refs only, never values) |
| Platform status | `GET /v1/platform/status` (observability.py:110) | bearer; secret-scrubbed |
| Eval | `GET/POST /v1/eval/cases`; `POST /v1/eval/run`; `GET /v1/eval/runs` (eval_routes.py) | author |
| Desktop (hands) | `GET /v1/hands/commands`; `POST /v1/hands/commands/{id}/receipt` (desktop_routes.py) | bearer; claim-on-read |
| Health/ready | `GET /healthz`, `GET /readyz` (app.py:389) | none |
| Auth / 2FA | `POST /v1/auth/{login,accept-invite,logout,refresh,2fa/*}` (boltrig/api/auth_routes.py) | public/session |

Cross-cutting the UI SDK MUST model:
- Canonical error envelope: uncaught `BoltrigError` -> `{status:"denied"|"error", reason}` with the
  error status (403=denied) (`app.py:121`). Governed `control.*` routes may 202 with
  `{status:"pending_human", hitl_request_id}` instead of the success body (`types.ts:154`) surfaced as a
  pending-human card. The UI SDK's write helpers MUST return `GovernedRouteResponse<T>` (success |
  pending_human).
- Empty results are scoping, not errors: render calm empty/denied states, do not throw.

---

## 2. Opbox surface -> boltrig primitive map (the "don't miss functionality" cross-check)

For each opbox surface: the boltrig primitive it must consume, what it consumes TODAY, and the gap.
Recall section 0: much of opbox's agent surface runs on the opbox Rust kernel today, not boltrig.

| Opbox surface | Files | Boltrig primitive(s) it must consume | Consumes today | Gap |
|---|---|---|---|---|
| AI sidebar | `src/components/shared/AIChat*.tsx`, `AIChatAgentTree.tsx`, `use-ai-chat.ts`, `use-ai-chat-sse.ts`, `src/lib/ai/boltrig-frames.ts`, `app/api/ai/kernel-chat/route.ts` | 1.1 chat turn + 1.2 SSE frames (text/reasoning/tool-call/tool-result/subagent/hitl/question/cost) + 1.6 HITL respond/answer + 1.7 cost | `POST /v1/chat` (body reduced to `{message,conversation_id?,on_behalf_bearer?}`, route.ts:151/160), `POST /v1/hitl/{id}/{respond,answer}` (approve/route.ts:163), `GET /v1/runs/{id}/events?follow=1` (approve/route.ts:207) | Bespoke: hand-rolled body translation, `on_behalf_bearer` seal, 202-queued passthrough, and a ~100-line `filterHitlContinuationStream` re-implementing run-relay resume + K-20 projection (`boltrig-chat.ts:102-200`). All prime UI SDK primitives: `chat.send`, `chat.respondHitl`, `run.followFrom(marker)`. Behind off-by-default `NEXT_PUBLIC_USE_KERNEL_CHAT` (`chat-endpoint.ts:23`). |
| Spotlight (Cmd+K) | `src/components/search/Spotlight*.tsx`, `use-spotlight-ai-actions.ts`, `ToolResultCards.tsx` | Same 1.1/1.2 chat + tool-result entity cards | Reuses `useAIChat` hook -> same `/api/ai/kernel-chat` path; no direct fetches | Inherits the sidebar's bespoke seam. Would consume `chat.*` + `capabilities()`/`runs()` once the UI SDK exists. |
| AI settings | `app/(app)/settings/ai/*` (OrgAiPanel, PersonalAiPanel, SetupTab, PricingPanel, AiConfigPanels, ...) | 1.7 budgets/cost, 1.15 AI keys, connection/model-gateway status, 1.14 PAT/provisioning status | Reads opbox-internal routes only (`/api/ai/platform-status`, `/api/organizations/{id}/ai-config`, `/api/settings/ai-usage` off `AiCostLedger`, Hermes `test-fire` hits `{base}/v1/models`+`/chat/completions`) | No boltrig endpoint read here at all, and NO boltrig-PAT/provisioning-status panel (nothing renders `User.boltrigProvisionedAt`). If per-user boltrig accounts become load-bearing, add a provisioning-status primitive + panel. Budgets/cost shown are opbox-local, not boltrig `/v1/budgets`+`/v1/cost`. |
| Agent centre | `app/(app)/automations/agents/page.tsx`; `src/components/agents/{AgentKanban,AgentBoard,AgentRoster,AgentApprovals}.tsx` | 1.4 work-queue + 1.5 roster + 1.6 HITL | ALL opbox Rust kernel: `GET /api/agents` (`org.agent.list`), `GET /api/agents/tasks` (`agenttask.list`), `POST /api/agents/govern` (`org.agent.disable`/`oversight.escalate`/`agenttask.reorder`/`cancel`), `GET /api/agents/activity` (`agent.activity.feed`) | Net-new-over-boltrig, not a re-point: the queue/roster/governance are opbox-kernel verbs. Mapping onto boltrig needs `/v1/work`(1.4) as the queue, `/v1/hitl/{id}/respond`(1.6) as governance, and a boltrig roster/subagent-topology primitive that does not exist yet (only the unbounded `subagent` frame). |
| Per-matter agents | `src/components/matters/MatterAgentsTab.tsx` (+ `MatterAgentTasksTab.tsx`) | 1.3 runs filtered by matter | `MatterAgentsTab` reads the frontend companion table directly (`prisma.agentTaskExt.findMany({sourceMatterId})`, `app/api/matters/[id]/agent-tasks/route.ts:24`); `MatterAgentTasksTab` reads `agenttask.list?matterId=` | Two divergent matter-scoped agent surfaces (one `AgentTaskExt`, one kernel verb): consolidation gap. Boltrig has NO run-list filtered by an owning object; `/v1/runs` is not owner/label filterable -> kernel gap to add matter/label scoping. |
| Workflows (Hatchet) | `src/components/workflows/WorkflowRunsView.tsx`; `app/(app)/automations/workflows/*` | 1.8 workflows + workflow runs + 1.2 `workflow_step`/`workflow_run` frames | All opbox-internal Prisma workflow engine (`/api/workflows`, `/api/workflows/{id}/runs`), no boltrig | Boltrig emits `workflow_*` frames but opbox ignores them ("no chat-UI semantics"); boltrig workflow runs are surfaced nowhere in opbox. Gap if boltrig-driven workflows should be visible: consume `/v1/workflows`+`/v1/workflows/{id}/runs`+the run relay. |

---

## 3. Kernel SDK: the per-user bearer API spec

### 3.1 The shipped behavior and why it blocks per-user parity

`sdks/node/src/server.ts` (the app's MCP verb server that boltrig calls back to) does two things that
must change for per-user execution:

1. It authenticates the presented bearer by constant-time comparing it to ONE static token read from
   `process.env[tokenEnv]` (default `BOLTRIG_MCP_TOKEN`), `server.ts:183-204`. Any bearer that is not
   exactly that static token returns `-32001 unauthorized`.
2. `VerbHandler = (params) => ...` (`server.ts:55-57`); the handler is invoked as
   `verb.handler(args)` (`server.ts:247`). The extracted `bearer` is used ONLY for the static compare
   and is then DISCARDED. The handler never sees it.

What boltrig actually presents per call: `x-boltrig-mcp-token: <bearer>` AND `Authorization: Bearer
<bearer>` for the SAME kernel-resolved token (`boltrig/adapters/mcp_transport.py:126`). The token is
resolved kernel-side per call from the credential seam (`boltrig/adapters/mcp_consumer.py:236-261`,
`bearer_token(credential)`), never held on the adapter. And under the OBO passthrough that value is NOT
the static registration token: it is the caller's clamped external bearer (the opbox-kernel session
bearer), sealed per-run (`credentials.py:213`) and resolved at dispatch as an OVERRIDE of the static
adapter credential (`dispatch.py:464-478`: `resolve_for_adapter` first, then
`resolve_run_scoped_credential` wins when a run-scoped bearer is sealed).

So two failures compound:
- Auth failure: when boltrig sends the OBO bearer, `server.ts` rejects it because it is not the static
  `BOLTRIG_MCP_TOKEN`. The OBO passthrough cannot even reach a Node SDK verb server today.
- Identity blindness: even if it authenticated, the handler cannot know WHICH user the call is
  on behalf of, so it cannot enforce that user's permissions in the app. The app would need bespoke,
  out-of-band work to recover identity.

The reference "done right" already exists in opbox's own Rust MCP door: `handle_request(state, bearer,
req)` resolves `RawRequest::new(Source::Mcp, bearer)` to an actor and binds a per-bearer tier ceiling
(`opbox-kernel/kernel/src/mcp/protocol.rs:127,187,225`; `mcp/mod.rs:105-109`). The Node SDK must catch
up to that: treat the presented bearer as the per-call identity token and resolve it.

### 3.2 The required SDK API change

Split the two concerns the single static token currently conflates: transport trust (is this really my
kernel calling?) and per-call identity (on whose behalf?). The kernel sends ONE bearer, so the primary
contract is: the presented bearer IS the identity token, and identity resolution IS the auth gate.

Add an identity-resolution hook and widen the handler signature:

```ts
// New: what the app knows about the caller after resolving the per-call bearer.
export interface VerbIdentity {
  subject: string;                 // e.g. the opbox user id / email
  tenantId?: string;
  grants?: string[];               // the caller's effective grants, for the app to enforce
  [k: string]: unknown;            // app-specific claims
}

// New: the second arg every handler now receives.
export interface VerbContext {
  bearer: string | null;           // the raw per-call bearer (x-boltrig-mcp-token / Authorization)
  identity: VerbIdentity | null;   // resolved identity, or null in static/service mode
  verb: string;                    // the dotted verb id being executed
  adapterId?: string;              // this app's adapter id, if known
}

export type VerbHandler = (
  params: Record<string, unknown>,
  ctx: VerbContext,                // <-- was absent; now always passed
) => unknown | Promise<unknown>;

export interface BoltrigMcpServerOptions {
  // ...existing name/version/verbs/host/port...

  // Mode A (default, back-compat): omit resolveIdentity. Keep the constant-time
  // compare against tokenEnv; identity = a fixed service principal. Preserves
  // today's dev/non-OBO tenants unchanged.
  tokenEnv?: string;

  // Mode B (per-user OBO): provide resolveIdentity. The SDK calls it with the
  // presented bearer; null => 401 (-32001). A non-null identity is passed to the
  // handler via ctx.identity so the handler enforces THAT user's permissions.
  // The app implements this by validating the bearer against its own auth
  // (for opbox: the opbox-kernel session bearer against its session store), i.e.
  // exactly what opbox-kernel/kernel/src/mcp/protocol.rs already does.
  resolveIdentity?: (bearer: string | null) => Promise<VerbIdentity | null>;

  // Optional defense-in-depth for Mode B: a SEPARATE shared secret proving the
  // caller is the boltrig kernel, carried in its own header, so identity and
  // transport-trust are not the same value. Defaults to network locality
  // (host 127.0.0.1, the existing default) when unset.
  transportSecretEnv?: string;
  transportSecretHeader?: string;  // default e.g. "x-boltrig-kernel-secret"
}
```

Behavioral contract:
- Mode A (no `resolveIdentity`): unchanged from today. `ctx.identity` is a fixed service principal;
  `ctx.bearer` is the static token. Existing apps and tests keep passing.
- Mode B (`resolveIdentity` provided): the SDK no longer static-compares the bearer. It calls
  `resolveIdentity(bearer)`; `null` -> `-32001 unauthorized` (mirrors `mcp.py:169`); non-null ->
  `handler(params, {bearer, identity, verb, adapterId})`. If `transportSecretEnv` is set, the SDK ALSO
  requires `transportSecretHeader` to match before resolving identity (fail-closed).
- The handler enforces per-user permission using `ctx.identity.grants` (or by re-dispatching into the
  app's own kernel WITH `ctx.bearer`, which is what opbox will do: forward the OBO bearer to the
  opbox Rust kernel so its own RLS/tier ceiling applies).
- Never log `ctx.bearer` or `resolveIdentity` inputs (the SDK already forbids logging the token).

This is the whole change future apps need for per-user execution: implement one `resolveIdentity` hook
(or forward `ctx.bearer` to their own kernel) instead of bespoke plumbing. The kernel side is already
built (`seal_run_scoped_adapter_bearer` + `resolve_run_scoped_credential` + the dual-header transport);
only the Node verb-server end is behind. `_OBO_ADAPTER_ID` (`boltrig/fleet/chat.py:73`, default
`"opbox"`, env `BOLTRIG_OBO_ADAPTER_ID`) names the adapter the OBO bearer is sealed for, so the SDK
should let an app declare its adapter id and, in Mode B, assume the presented bearer is the OBO bearer
sealed for that adapter for the life of the run.

### 3.3 Head/chat client note (already partly built)

`sdks/node/src/head.ts` already ports the chat SSE consumer + `respondHitl`/`answerQuestion`. It
authenticates with a PAT (`Authorization: Bearer`), which is the correct inbound model: the PAT's user
IS the chatter, and `on_behalf_bearer` is a SEPARATE optional downstream credential passed in the chat
body (not an identity override). Opbox confirms this split: per-user PAT resolution
(`src/lib/ai/boltrig-chat.ts:48 resolveBoltrigChatPat`, tier1 `User.boltrigPat`, tier2
`BOLTRIG_CHAT_PATS`) for identity, plus the clamped opbox-kernel bearer forwarded as
`on_behalf_bearer` (`app/api/ai/kernel-chat/route.ts:160`) for downstream execution. The head client
should gain an `onBehalfBearer` option on `streamTurn` so this is a first-class SDK parameter, not a
hand-added body field.

---

## 4. Shared source-of-truth notes (two frontends over the same data)

- Source of record: runs, chats, run events/audit, and the kernel cost/audit chain live in the BOLTRIG
  kernel. It is the SoR for the agent's work. Apps READ them back; they do not re-store them.
- The UI SDK is the shared read/stream client so TWO frontends render identical data: the boltrig
  console (`ui/`) and opbox (and future apps) must view the SAME runs/chats/HITL/cost via the SAME
  `ChatEvent` union (1.2), the SAME run relay (`GET /v1/runs/{id}/events`), and the SAME normalized turn
  reducer. The boltrig console's `ui/src/api/*` + `chatTurnNormalizer.ts` is the reference to extract, so
  the two frontends cannot drift.
- Opbox keeps THIN companions beside boltrig, not copies of the SoR:
  - `AgentTaskExt` (`prisma/schema.prisma:2904`, `agent_task_ext`): a frontend-owned EXTENSION of the
    kernel `agent_task` row (PK = kernel agent_task id, no FK, cross-store). Holds UI/orchestration state
    the kernel does not: `title/prompt/source*`, the frontend-derived fan-out state
    `waitingForChildren`/`declaredChildKeys` (the WAITING_CHILDREN status the kernel lacks), the cost tail
    `costUsd/durationMs/toolCallCount`, claim state `claimTokenHash`/`claimedAt`, the GDPR Art-22 gate
    `requiresHumanReview`. This is companion state, NOT the run of record.
  - `AiCostLedger` (`prisma/schema.prisma:6223`): opbox's billing SoR (per-call row with tokens,
    gross/net USD, discount, reseller price, key source, conversation FKs). Because boltrig `message_end`
    carries NO token usage, the boltrig chat path records a PRE-turn ESTIMATE
    (`src/lib/ai/kernel-chat-billing.ts:203 recordAiCost`, `estimateTokensFromChars`, `outputTokens:1000`
    fallback), gated pre-stream by `checkBudget`. This is a billing companion, reconcilable against the
    kernel's own cost once usage frames exist (see GAPS). Note a SEPARATE kernel-owned snake_case
    `ai_cost_ledger` (`schema.prisma:8898`) is the kernel's cost table; the two stores are distinct.
- Governance stays kernel-side: high-consequence writes route through `control.*` verbs and may return
  `{status:"pending_human", hitl_request_id}`; the UI SDK surfaces that, it does not locally approve.

---

## 5. GAPS (consolidated: what the SDK and/or kernel must add)

Kernel SDK (section 3):
1. G1. Per-user bearer never reaches the verb handler. Add `resolveIdentity` hook + widen
   `VerbHandler` to `(params, ctx)` with `ctx.{bearer,identity}`; stop static-comparing the OBO bearer.
   Without this, OBO passthrough cannot reach a Node SDK verb server and per-user permission parity is
   impossible without bespoke per-app work. (`sdks/node/src/server.ts:55,183,247`.)
2. G2. Head client should accept `onBehalfBearer` as a first-class `streamTurn` option (today apps
   hand-add the body field). (`sdks/node/src/head.ts:153`.)

SSE protocol gaps opbox already works around (kernel-side, surfaced through the UI SDK):
3. G3. No subagent-completion frame. `subagent` opens a child but nothing settles it, so opbox's
   delegation tree renders RUNNING forever (`boltrig-frames.ts:177-195`). Add a subagent-settle frame
   (e.g. `subagent_end {child_run_id,status}`).
4. G4. `message_end` carries no token usage/cost. Opbox falls back to pre-turn estimates for billing
   (`kernel-chat-billing.ts`). Emit usage on `message_end` (or a `cost`/`usage` frame) so
   `AiCostLedger` records actuals and reconciles with `/v1/cost`.
5. G5. No run-relay resume cursor. `GET /v1/runs/{id}/events?follow=1` replays the whole backlog with
   no "since" marker, forcing opbox's ~100-line `filterHitlContinuationStream` offset+K-20 re-projection
   (`boltrig-chat.ts:102-200`). Add a resume marker (`?since=<seq>`), and expose a UI SDK
   `run.followFrom(marker)` that hides backlog-drop + the K-20 projection.
6. G6. `workflow_step`/`workflow_run` frames are emitted but no app surface consumes them; boltrig
   workflow runs are surfaced nowhere in opbox. UI SDK should provide the workflow-run canvas contract
   (1.8) so boltrig-driven workflows are visible.

Primitive/kernel coverage gaps (the UI SDK cannot expose what does not exist):
7. G7. No boltrig run/roster LIST scoped to an owning object. Agent Centre queue/roster/HITL and
   per-matter agents run on the opbox Rust kernel today (section 2). To make boltrig the agent-of-record
   there, add: `/v1/runs` filterable by owner/label/matter, and a roster/subagent-topology read
   primitive (the live tree is only the unbounded `subagent` frame). Until then, mapping those surfaces
   onto boltrig is net-new surface, not a re-point.
8. G8. No boltrig-PAT / provisioning-status primitive surfaced. Nothing reads
   `User.boltrigProvisionedAt`; AI settings has no boltrig connection/provisioning panel. If per-user
   boltrig accounts are load-bearing, add a status primitive (provisioned?, PAT health) + panel.

Consolidation gaps in opbox (flag for the app team, not the SDK):
9. G9. Two divergent matter-scoped agent surfaces: `MatterAgentsTab` reads `AgentTaskExt` directly,
   `MatterAgentTasksTab` reads `agenttask.list`. Converge on one data source (ideally the boltrig `runs`
   primitive once G7 lands).
10. G10. Cost double-accounting: opbox bills off local `AiCostLedger` estimates while boltrig owns the
    real cost chain (`/v1/cost`, `/v1/console/overview`). Reconcile once G4 provides actual usage.

---

## Appendix: file map (evidence)

Kernel SDK: `sdks/node/src/server.ts` (verb server + static-token gap), `register.ts` (register/activate/
mint-PAT/respond-HITL), `head.ts` (chat SSE + HITL), `http.ts`, `index.ts`, `README.md`.

Kernel OBO wiring: `boltrig/kernel/app.py:231,473` (ChatBody.on_behalf_bearer, `/v1/chat`);
`boltrig/fleet/chat.py:69-73,718-721` (`_OBO_ADAPTER_ID`, seal at turn start);
`boltrig/kernel/credentials.py:213,244` (seal/resolve run-scoped adapter bearer);
`boltrig/kernel/dispatch.py:464-478` (static-vs-OBO precedence);
`boltrig/adapters/mcp_consumer.py:224-261`, `mcp_transport.py:126` (per-call bearer, dual headers);
`opbox-kernel/kernel/src/mcp/protocol.rs:127-225`, `mcp/mod.rs:105-109` (reference per-bearer resolve).

UI SDK reference: `ui/src/api/{transport,sse,api,types}.ts`, `ui/src/api/domains/*.ts`,
`ui/src/panels/chat/{chatTurnNormalizer.ts,chatTurnTypes.ts}` and the per-card renderers.

Kernel routes: `boltrig/kernel/app.py`, `access_routes.py`, `channel_routes.py`,
`channel_gateway_routes.py`, `memory_routes.py`, `work_http.py`, `hitl_http.py`, `run_access.py`, and
`boltrig/kernel/platform_routes/*` (adapters, admin, budgets, console, eval_routes, knowledge, memory,
observability, personal, router, skills, workflows).

Opbox surfaces: `src/components/shared/AIChat*.tsx`, `src/hooks/use-ai-chat*.ts`,
`src/lib/ai/{boltrig-chat,boltrig-provisioning,boltrig-frames,kernel-chat-billing}.ts`,
`app/api/ai/kernel-chat/{route.ts,approve/route.ts}`, `src/components/search/Spotlight*.tsx`,
`app/(app)/settings/ai/*`, `app/(app)/automations/agents/page.tsx`,
`src/components/agents/{AgentKanban,AgentBoard,AgentRoster,AgentApprovals}.tsx`,
`src/components/matters/{MatterAgentsTab,MatterAgentTasksTab}.tsx`,
`src/components/workflows/WorkflowRunsView.tsx`, `prisma/schema.prisma` (AgentTaskExt:2904,
AiCostLedger:6223, User.boltrigPat:79, kernel ai_cost_ledger:8898).
