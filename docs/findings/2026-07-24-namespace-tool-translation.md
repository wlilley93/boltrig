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

## Governance note

This is the per-cell model-proxy - our translation layer, the VJS-CC-VJS 4
chokepoint. Reshaping the tool REPRESENTATION (namespace <-> flat) does not
change WHICH verbs are allowed (the ceiling set is identical, built-ins still
stripped, response still guarded), so it is engineering within the established
boundary, not a new security fork. Keep the ceiling tests green and add flatten
+ round-trip coverage when the return-path form is nailed.
