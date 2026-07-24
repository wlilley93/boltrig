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

## End-to-end status

`POST /v1/chat "use opbox.matter.list"` will still return `degraded` until A and
B are resolved: B blocks model auth on a cold cell, and A blocks the tool
execution once the model does emit the (now correctly-resolved) call. The
namespace translation - the part three sessions were stuck on - is no longer in
the path of failure.
