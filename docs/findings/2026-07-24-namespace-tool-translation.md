# Kernel-tools lane: the MCP-namespace tool translation problem

Date: 2026-07-24. Supersedes the earlier "GLM can't call the namespace" framing
in `HANDOVER-2026-07-24.md` finding 3 with a sharper mechanism and a partial fix.

## The problem, precisely

Codex 0.144.3 presents an MCP server to the model as ONE Responses-API entry:
`{"type":"namespace","name":"mcp__boltrig","tools":[ {type:function, name:opbox_matter_list, inputSchema, description}, ... ]}`
(confirmed live AND in the pinned schema `schemas/codex/0.144.3/...` -
`DynamicToolSpec` / `NamespaceDynamicToolSpec`). The 57 nested tools are the
org-admin effective grant set (control.* + desktop.* + opbox.8 + memory.4 +
chat_ask_user).

Bifrost's only provider is `zai` with `base_provider_type: anthropic` (z.ai's
Anthropic endpoint), while codex speaks the Responses API. So bifrost translates
Responses -> Anthropic Messages. **Anthropic has no "namespace" tool concept**,
so the translation collapses the whole `mcp__boltrig` namespace into a single
opaque tool named `mcp__boltrig`. The model then calls `mcp__boltrig` with
`arguments:"{}"` - it never sees the individual verbs. That call is outside the
ceiling (the guard allows the nested names, not the bare namespace), so the
response-stream guard truncates it -> `codex_empty_output`. This is
model-INDEPENDENT (reproduced identically; a glm-5.2 switch changed nothing).

## What was proven this session (partial fix, request side)

Flattening the namespace at the model-proxy chokepoint (`enforce_tool_ceiling`
in `model_proxy_tool_ceiling.py`) - spreading the ceiling-kept nested function
tools as individual top-level `type:function` tools before bifrost sees them -
**eliminates the collapse**: the model then issues a proper named tool call
(bifrost `status=success ctok=88`, NO more `codex_empty_output`, NO guard
truncation). The nested entries are already exact function-tool objects, so the
spread needs no per-tool reshaping. The ceiling is unchanged (same verb set);
only the wire shape the gateway sees changes, so this stays within VJS-CC-VJS 4.
Working WIP is saved as `docs/findings/2026-07-24-namespace-flatten-wip.patch`
(reverted from main - it does NOT complete the fix, see below, and must not ship
half-done on a security path).

## The remaining blocker (return path)

After flattening, codex REJECTS the model's call with `unsupported call:
<name>` (codex's own error, not ours - grep-confirmed absent from our source;
NO `/v1/mcp` request reaches the kernel). Tried both:
- bare `opbox_matter_list` -> `unsupported call: opbox_matter_list`
- qualified `mcp__boltrig__opbox_matter_list` (the `__` separator the response
  guard's `_name_allowed` already strips) -> still `unsupported call`

So codex maps the model's call back to its MCP server by a name derived from
ITS OWN namespace declaration, and neither the bare nor the `mcp__boltrig__`
form matches. Codex controls BOTH ends (it declares the tools AND routes the
response call); we only rewrite the middle, so codex still expects the call in
whatever form it registered from the namespace it declared.

**Leading hypothesis (untested):** the `namespace` is called as a UNIT - the
model is meant to call `mcp__boltrig` (the namespace) with an ARGUMENT selecting
the nested verb, not call the nested verb by its own name. That reframes the
very first observation (GLM calling `mcp__boltrig` with `{}`) as
structurally-correct-but-argument-empty (bifrost's Anthropic translation likely
dropped the nested selection schema), NOT a pure collapse. If true, flattening
is the wrong axis; the fix is ensuring the model receives the schema that tells
it how to select a nested verb when calling `mcp__boltrig`.

## Next diagnostic (to crack the exact call form)

1. Capture the codex App Server's STDERR during a turn (it's read by
   `CodexStdioTransport` but not currently surfaced) - codex likely logs the
   tool registry / the exact expected call name alongside `unsupported call`.
2. OR find codex's model-facing serialization of a namespaced tool call in the
   pinned schema (`DynamicToolCall*` items) - determine whether a nested call is
   `{name: <bare>}`, `{name: mcp__boltrig, arguments:{tool:<bare>,...}}`, or a
   qualified name with a separator we haven't tried.
3. Once known, either (a) rename the flattened tools to that exact form on the
   request (no response rewrite needed), or (b) keep bare-flat on the request and
   rewrite the model's response tool-call name/shape back to codex's expected
   form on the response stream (`ToolCallStreamGuard` already parses call names,
   so the machinery is there).

## Session 2 addendum (2026-07-24 pm): codex-side facts, via its own stderr

Captured the codex app-server's stderr (the transport normally discards it;
temporarily teed it) with `RUST_LOG=codex_core::tools=trace,codex_core::mcp=trace`
injected via the cell env, flatten WIP applied. Decisive facts:

- **The MCP connection WORKS end to end.** codex logs
  `add_mcp_runtime_tools{direct_mcp_tool_count=57 deferred_mcp_tool_count=0}` -
  codex connected to `kernel:8000/v1/mcp`, ran tools/list, and registered ALL
  57 boltrig verbs in its tool router. So the run-token bearer reaches codex and
  authenticates (this RETIRES the lingering doubt about token delivery - it is
  fully working; the empty `/proc/environ` is codex capturing the token before
  its sandbox re-exec, exactly as hypothesised). The reason no `/v1/mcp` CALL
  (tools/call) shows during a turn is purely that the routing below fails before
  codex ever forwards one; tools/list at cell startup DID hit the door.
- **The failure is purely name routing**, from codex itself:
  `codex_core::tools::router: error=unsupported call: mcp__boltrig__opbox_matter_list`.
  Both the bare `opbox_matter_list` AND the `mcp__boltrig__<verb>` qualified form
  are "unsupported call". codex registered the tools from the kernel's tools/list,
  where the kernel advertises each by its RAW dotted `v.id` (`opbox.matter.list`,
  `boltrig/kernel/mcp.py:353`), which codex sanitises to `opbox_matter_list` for
  the model-facing nested name - yet codex's router won't accept that name once
  the tool is presented flat.
- **Charset wall:** Anthropic tool names must match `^[a-zA-Z0-9_-]{1,64}$`, so a
  `.` or `/` separator (the other two forms `_name_allowed` checks) cannot even
  survive to the model over the z.ai/Anthropic path. Only `__` is expressible,
  and codex rejects it. So "flatten + rename to codex's key" cannot be completed
  without knowing codex's exact router key, which is codex-internal (needs codex
  source or a captured WORKING namespaced call, which GLM can't produce because
  of the collapse - a chicken-and-egg).

## Two candidate fixes (neither a quick win; both scoped for a future session)

1. **Response-side reconstruction.** Keep request-side flattening (proven to make
   the model emit a real named call). On the RESPONSE stream, rewrite the model's
   flat function-call back into the namespaced form codex's router expects. Blocked
   on the same unknown: codex's exact expected namespaced-call shape. Cracking it
   needs codex source for `codex_core::tools::router` / `mcp_tool_exposure`, or a
   reference capture of a working codex+MCP call against a Responses-native model.

2. **Change bifrost's provider so there is NO namespace-collapsing translation.**
   The collapse exists ONLY because bifrost's `zai` provider is
   `base_provider_type: anthropic` (`https://api.z.ai/api/anthropic`) and Anthropic
   has no namespace concept. z.ai also exposes an OpenAI-compatible endpoint
   (`https://api.z.ai/api/paas/v4`). Re-point/duplicate the provider as an
   `openai`-type base and codex's namespace may pass through with a less-lossy (or
   no) translation, letting codex's OWN name mapping work end to end - no proxy
   rename at all. HIGHER BLAST: bifrost is the shared gateway for ALL model traffic
   on this box (read-only Codex lane AND the main org chat), so this must be a NEW
   provider/route tested in isolation first, not an in-place edit of the live one,
   and needs the z.ai key validated against the OpenAI endpoint. This is the more
   promising path if it holds, because it removes the root cause instead of
   working around it.

## Governance note

This is the per-cell model-proxy - our translation layer, the VJS-CC-VJS 4
chokepoint. Reshaping the tool REPRESENTATION (namespace <-> flat) does not
change WHICH verbs are allowed (the ceiling set is identical, built-ins still
stripped, response still guarded), so it is engineering within the established
boundary, not a new security fork. Keep the ceiling tests green and add flatten
+ round-trip coverage when the return-path form is nailed.
