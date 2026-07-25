# Kernel-tools lane: namespace bridge landed, two downstream blockers remain

Date: 2026-07-24
Status: namespace translation SOLVED + landed (`0402911`); end-to-end tool
execution still blocked by two distinct, now-precisely-identified issues.

## What is now fixed (landed on main)

The three-session namespace-translation blocker is resolved and shipped
(`feat(proxy): bridge Codex's MCP tool namespace across the gateway`,
`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py` +
`codex_model_proxy_server.py`):

- Request: the per-cell proxy FLATTENS the `mcp__boltrig` namespace into
  top-level function tools so a namespace-blind gateway (Bifrost ->
  Anthropic-shaped z.ai) cannot collapse them.
- Response: `CodexResponseStreamProcessor` REATTACHES
  `namespace="mcp__boltrig"` onto each returned `function_call`, which is what
  Codex's strict `ToolName{name, namespace}` router match requires.

Proven live: the codex runtime log went from `unsupported call` to
`codex_core::tools::parallel: tool call completed ... execution_started=true`
for `opbox_matter_list`. Codex now resolves and DISPATCHES the tool call.

## Blocker A (newly revealed) - Codex sends an MCP-tool-call APPROVAL request

Immediately after dispatch, the codex App Server sends a server-INITIATED
request over stdio:

```
{"method":"item/tool/requestUserInput","id":0,"params":{
  "threadId":"...","turnId":"...","itemId":"call_...",
  "questions":[{"id":"mcp_tool_call_approval_call_...",
    "header":"Approve app tool call?",
    "question":"Allow the boltrig MCP server to run tool \"opbox.matter.list\"?",
    ...}]}}
```

Our App Server client (`codex_app_server.py::_reader_loop`) handles only
RESPONSES and NOTIFICATIONS; a server-initiated REQUEST hits
`wire.UnexpectedServerRequestError()`, which fails the notification pump and
degrades the turn. So even with `approval_policy="never"` (that governs
shell/exec), codex asks separately for approval of every MCP tool call and we
never answer it.

Decision needed (design fork - route to the VJS court, not decided here):
1. Auto-approve at the client - respond to `item/tool/requestUserInput` with an
   approval, since the kernel already governs the actual verb dispatch through
   its own HITL + ceiling. Simplest; the codex-side prompt is redundant with our
   real gate.
2. Route the approval to boltrig's existing HITL - answer the codex request from
   the kernel's HITL decision, so the two gates are one. Cleaner conceptually,
   more wiring (map codex `questions` <-> HITL asks).
3. Suppress the request at source if a codex config disables MCP-tool approval
   (needs confirmation that 0.144.3 exposes such a knob; `[tools]` did not).

Either 1 or 2 requires the App Server client to ANSWER a server-initiated
request - a protocol capability it does not have today. That is the next
concrete piece of work.

## Blocker B (pre-existing, session-1) - model-bearer attestation ambiguity

`model_proxy_peer_attestation.py` fails the SO_PEERCRED ancestry check with
`peer ancestry is ambiguous`, which yields empty model-bearer tokens and blocks
model auth on a fresh cell. It was worked around during this investigation with
a temporary `BOLTRIG_DEV_SKIP_PEER_ANCESTRY` bypass ONLY to isolate the
namespace fix; that bypass has been REVERTED (it is a security hole - it
confirms the single registration without proving ancestry). The real fix is to
make the ancestry walk deterministic for the codex cell's process tree, or to
re-attest by a non-ancestry signal. Separate subsystem from the tool lane.

## Blocker A - the answer schema is now KNOWN (recovered from the pinned binary)

The `requestUserInput` request/answer types are not in the pinned schema bundle
(experimental API), but the pinned binary emits its own types:

```
docker exec boltrig-fleet-worker-1 sh -c \
  'D=$(mktemp -d); /opt/boltrig/codex/codex app-server generate-ts --out "$D"; \
   cat "$D"/v2/ToolRequestUserInput*.ts'
```

Authoritative types (codex 0.144.3):
- Request `item/tool/requestUserInput` params: `{threadId, turnId, itemId,
  questions[], autoResolutionMs: number|null}`; each question `{id, header,
  question, isOther, isSecret, options: {label, description}[]|null}`.
- **Response result: `{answers: {[questionId]: {answers: string[]}}}`** — echo the
  chosen option `label`(s) per question id (match the approve option from
  `params.options`; do NOT hardcode "Accept"). Envelope `{"id":<int>,"result":{...}}`,
  `jsonrpc` OMITTED.
- `autoResolutionMs`: codex auto-resolves if the client does not answer in time, so
  a human HITL wait can exceed it — a real constraint on the design.

Implementation seam (agent Option 1): add `wire.encode_response` +
`BoundedWriter.send_response`, replace the `else: raise
UnexpectedServerRequestError` at `codex_app_server.py:343-344` with dispatch to an
injected `server_request_handler` (run as a task so the reader never blocks). The
one genuine design challenge: boltrig's existing HITL PAUSES+REQUEUES the run
(durable, cross-process), but this approval is MID-TURN while the App Server is
synchronously blocked in the fleet-worker and the answer arrives at the kernel API
process — so "route into HITL" needs a NEW synchronous waiter + a cross-process
answer signal (Redis pubsub keyed by run_id, or poll the HITL store). Bridge key:
codex `turnId` ↔ boltrig `run_id`.

## Blocker C (new) - a PAT carries no workspace, so headless chat can't reach codex

`resolve_pat_principal` (`boltrig/identity/tokens.py:116-123`) builds the Principal
with no `active_workspace_id`. `/v1/chat` passes `p.active_workspace_id`
(`kernel/app.py:485`) straight through, so a PAT-driven chat turn has NO workspace
scope and the read-only Codex phase degrades with `no_read_only_phase_scope`
(`kernel/app.py:178-181`) — a DIFFERENT degradation than A/B, which means a PAT
alone cannot exercise the tool lane end-to-end. The session/frontend path sets the
workspace from the session; PATs (the headless-client credential, and the
frontend-SDK's own client credential) cannot today. Fix options: derive the
workspace from the user's membership when unambiguous, store a workspace on the
PAT, or let the chat body/header carry an explicit workspace_id (the SDK will want
the last regardless). This blocks the `mint-token`-driven lane verification and is
squarely part of the frontend-SDK "headless client" story.

## Live test (2026-07-24, after C + namespace fix deployed)

A real PAT-driven turn (`mint-token` + C giving the workspace scope) now REACHES
the codex model call: it spawned an `ops/opbox` subagent and hit z.ai. Bifrost's
own log shows the `glm-4.6` `responses_stream` call ran ~5.2s then failed with
`status_code: 499, {"type":"request_cancelled","message":"client disconnected"}`,
and the turn returned `degraded (codex: codex_empty_output)`.

So the client (our per-cell proxy <- codex) tore the stream down mid-response. The
cause is one of: (a) `CodexResponseStreamProcessor` raising `ToolCeilingViolation`
and truncating (but NO truncation warning was logged, arguing against this), (b)
codex closing its connection to our proxy after receiving a tool call and then
hitting the approval/pump blocker (A), or (c) the attestation reject (B) tearing
the cell down. Bifrost does not log the offered tools array or the streamed
response body, and the codex cell's own cause is swallowed at the current log
level - the SAME wall the prior handover hit.

**Next diagnostic (prerequisite for A/B):** add PERMANENT, bounded cell-level
observability - capture the codex cell's stderr to a ring buffer surfaced at
WARNING when a cell degrades, and ensure the model-proxy truncation + attestation
warnings actually reach the fleet-worker log. Only then can the 499 be attributed
to A vs B vs a stream-processor defect, rather than re-guessed. This is a real gap
(flagged twice across handovers), so it should be built as shippable observability,
not throwaway debug.

## RESOLVED - the lane works end to end (2026-07-24)

After blocker A was implemented ([2026] VJS-COUNTY 12: answer codex's
item/tool/requestUserInput by admitting to the kernel gate; `e70ba6f`) and
deployed, a live PAT-driven turn drove a governed `opbox.matter.list` call all the
way through and returned the REAL data:

  "There are 3 matters in the Opbox workspace: 1. Acme Holdings - incorporation
   (MAT-1001) OPEN; 2. Beta Trust - annual filing (MAT-1002) ON_HOLD; 3. boltrig
   shadow proof (default-1003) OPEN"

NOT degraded. bifrost: glm-4.6 success. No pump crash, no attestation failure, no
teardown markers. The three real matter ids exist only behind the actual verb, so
this is definitive proof the tool executed through the governed dispatch chokepoint
(ceiling on the model-proxy + kernel.invoke grant-check + audit).

The full chain that had to line up: namespace flatten+reattach (codex resolves the
tool) -> blocker C PAT workspace scope (the turn reaches codex) -> blocker A
approval admit-to-kernel (codex's approval is answered, the tool executes, the
kernel governs). All landed and deployed.

### Re-verified on a clean rebuild (2026-07-25)

Re-ran `scripts/lane-smoke.sh` against a freshly built + recreated kernel and
fleet-worker (main at `40fc648`, so including the CRLF/marker hardening the
earlier verification ran without). Same real answer, not degraded, three
`glm-4.6` bifrost calls all `success`.

The DEFINITIVE evidence is the audit log, not the reply text (a plausible reply
could in principle be recalled from memory):

```
select ts, actor, verb, status from audit_log where ts > now() - interval '25 minutes';
2026-07-25 06:34:15+00 | worker-cheap | opbox.matter.list | ok
```

The governed verb was dispatched through the kernel chokepoint and audited. Note
that `POST /v1/mcp` does NOT appear in the kernel access log for a successful
turn - the door is not reached over the container's HTTP listener - so the audit
row, not the access log, is the check to run when confirming this lane.

Two carried-over open issues from `HANDOVER-2026-07-23.md` close on this run:
- **#2 (`BOLTRIG_CODEX_MCP_RUN_TOKEN` presence in the cell env unconfirmed)** -
  confirmed transitively and conclusively: the tool executed through the MCP
  door, which the cell cannot reach without the run token.
- **#3 (admission mismatch "observed MCP inventory does not match the admitted
  lane")** - it was to be re-opened only if it recurred with a live tool set. It
  did not recur on a live tool set. Closed.

### Blocker B (attestation) status: monitored, not a hard blocker

B did NOT fire on the successful runs (bifrost saw the model call succeed, which
requires a valid bearer, so attestation passed). It remains INTERMITTENT. The
diagnosability is now in place (named zero-match causes + the runtime terminal
cause is logged), so the next time B fires the exact cause (cgroup drift vs
reparent vs pid-ns) will be captured rather than swallowed. The actual fix is
deferred until that evidence lands, so a security check is not weakened on a guess.

## End-to-end status (historical, pre-fix)

`POST /v1/chat "use opbox.matter.list"` will still return `degraded` until A and
B are resolved: B blocks model auth on a cold cell, and A blocks the tool
execution once the model does emit the (now correctly-resolved) call. The
namespace translation - the part three sessions were stuck on - is no longer in
the path of failure.
