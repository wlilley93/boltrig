# Nankle node system spec (Round Eight)

A clean surface over the registry, the workflow canvas, and chat - with internet
access as a governed verb, not an exception.

- **Status:** Draft, grounded against wlilley93/Nankle (main) as provided.
- **Scope:** three front-end surfaces over existing Nankle data (a registry/adapter
  tree editor, a multi-node-kind workflow canvas, a chat trigger surface), plus the
  one genuinely new backend capability: governed internet access.
- **Companion to:** the workflow editor / control plane specs + the addendum. This
  spec widens the workflow editor to three node kinds and resolves "uncaged".

## 1. Summary

Three surfaces, one discipline. A registry editor (nouns/verbs/bindings). A
workflow canvas with three node kinds (kernel-run, service, agent) plus trigger
nodes (chat/cron/webhook). A chat surface that is also a trigger. None introduce a
path around the single dispatch chokepoint - Section 4 demonstrates this.

## 2. Instruction to the implementing agent (separation of concerns)

- **Front-end:** render nodes/edges/forms/chat; hold local interaction state;
  serialise to/from the EXACT JSON the backend already expects; display what the
  backend returns faithfully; NEVER hold a client copy of authorization - the
  server's denial is authoritative (match `AdminPanel.tsx`).
- **Agent:** reasoning / the tool loop / the event stream belong to the runtime
  (Pi); the front end never simulates what an agent node will do; the runtime is
  unaware it is being visualised.
- **Kernel:** all authorization (grants, chokepoint, HITL, audit) stays in the
  kernel; the palette is populated from the kernel's scoped registry; the kernel
  never special-cases a call by which surface triggered it.

## 3. The three surfaces

- **3.1 Registry editor - a tree, not a DAG.** Nouns/verbs/bindings; a verb
  terminates in exactly one binding (adapter or agent), so it is hierarchical.
  Credentials never shown, only references.
- **3.2 The workflow canvas - three node kinds.** Kernel-run node (one fixed verb,
  may trigger a sub-workflow); service node (mechanically identical, grouped
  because its verb reaches a SaaS - NOT a separate code path); agent node (hands a
  sub-problem to Pi, which reasons among its granted verbs); trigger nodes
  (chat/cron/webhook entry points on the same canvas).
- **3.3 Chat - also a trigger.** A chat message starts a flow like a cron tick or
  webhook; the chat surface and the canvas are not unrelated.

## 4. Resolving "uncaged": internet access as a governed verb

"Uncaged" = an agent node with internet access, NOT one that bypasses the kernel.
Internet access becomes a new verb bound to a new adapter, governed by the same
chokepoint as everything else.

- **4.1 The primitive exists, partly.** `NetworkConfig` (air_gapped, https_proxy,
  ca_bundle, allowed_domains, blocked_domains) is modeled in the manifest; nothing
  read it. The work is wiring a new adapter to that policy model.
- **4.2 Start narrow.** Ship `web.fetch` (read-only GET) first; interactive
  browsing is a separate, later capability.
- **4.3 Higher consequence tier.** Fetched content is the one place untrusted,
  attacker-reachable text enters an agent's reasoning - a prompt-injection surface
  a Jira/MS-Graph adapter doesn't have. The existing per-verb HITL gate is real
  defense: even if injected content steers the agent toward a consequential next
  call, that next verb's own gate still fires.
- **4.4 SSRF.** Domain lists are necessary but not sufficient: reject private and
  link-local ranges and cloud metadata endpoints by default, independent of the
  domain list.

## 5. Tooling

- Registry editor + workflow canvas: **React Flow (@xyflow/react)** - MIT,
  React-native, purpose-built for node-flow editors; one graph dependency for both
  (tree layout vs canvas).
- Chat: the spec suggests **Vercel AI Elements** (shadcn/ui + AI SDK), ruling out
  the deprecated `shadcn-chat`. Both React Flow and the AI SDK family are flagged
  as deliberate dependency decisions, not to be waved through.

## 6. What this does not change

Skills / Router authoring / Adapter Studio stay form-based; AdminPanel's
JSON-section editor (privacy, network, hitl, notifications, personal_agents,
evaluation) is untouched.

## 7. Open items

- Whether anything enforces `NetworkConfig` (it did not; the web-fetch adapter is
  new enforcement work, not just wiring).
- Composable sub-workflow nodes introduce workflows-triggering-workflows; whether
  to reuse the agent `max_depth` limit against unbounded recursion is undesigned.
- Whether live execution state renders on the canvas, the log only, or both.
- Whether `api.upsertWorkflow`/`triggerWorkflow` route through a kernel verb or
  write the store directly (the control-plane governance answer).

## Build note (Round Eight disposition)

- **Backend (S4) is the substantive new capability and is built:**
  `nankle/adapters/builtin/web_fetch.py` - read-only `web.fetch`, high-consequence,
  SSRF-guarded, `NetworkConfig`-enforced, governed by the chokepoint (SEC-52/53).
  This closes the spec's central "uncaged" question and open item 7.1.
- **Dependency decision (recorded, disposed by principle):** adopt **React Flow**
  for the graph-shaped surfaces (the spec's pick; demonstrated-need:
  [[speclaw3-split-test]]); **reject Vercel AI Elements + the AI SDK** for chat -
  the existing `ChatPanel` + SSE already renders the pi_sidecar event shape, so a
  second chat stack is a fragmentation cost for marginal benefit
  ([[consolidation-over-fragmentation]]). Chat-as-trigger reuses the existing
  surface + the existing trigger/normalise path.
- **The control-plane governance answer (open item 7.4)** is already settled by
  Round Seven: control-plane writes can route through the `control.*` governed
  verbs; the web-fetch verb's own registration is governed the same way.
- The sub-workflow recursion limit (7.2) and live-canvas execution state (7.3)
  remain open follow-ons.
