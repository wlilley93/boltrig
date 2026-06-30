# Definition of Done - Round Eight (node system)

Spec: [`requirements-node-system.md`](./requirements-node-system.md). Two distinct
pieces: a genuinely new backend capability (internet access as a governed verb)
and front-end node surfaces (which carry a real dependency decision).

The spec's grounding was verified first. The headline backend finding held:
`NetworkConfig` (air_gapped / proxy / CA / allow / block) is modeled in the
manifest but was read and enforced by nothing - so the web-fetch adapter is new
enforcement work, not just wiring.

## What shipped

### S4 - Internet access as a governed verb (the substantive capability)

"Uncaged" means an agent may reach the internet, NOT bypass the kernel. So
internet access is a normal verb, governed by the same chokepoint as everything
else - no exception, no second path.

- `adapters/builtin/web_fetch.py` (new): `web.fetch`, a read-only HTTP GET
  (S4.2 - interactive browsing is a later, separate capability).
  - **High consequence (S4.3):** fetched content is the one place untrusted,
    attacker-reachable text enters an agent's reasoning, so the per-verb HITL gate
    holds it. Even if injected page content steers the agent toward a consequential
    next call, that next verb's OWN gate still fires. Content is returned as data,
    never authority.
  - **SSRF guard + NetworkConfig enforcement (S4.1/4.4, SEC-52):** the adapter now
    enforces air-gap + allow/block domains, and independently refuses any target
    resolving to a private / loopback / link-local / reserved / multicast address
    or the cloud metadata endpoint, regardless of the domain name. Redirects are
    not followed (no redirect into internal space). The policy/SSRF decision is a
    pure function (`check_network_policy`) refusing a blocked target BEFORE any
    network call - fully testable offline.
- `models/errors.py`: `NetworkPolicyViolation` (403).
- `api/bootstrap.py`: registers `web.fetch` (manifest path reads the typed
  `NetworkConfig`; dev-seed uses an empty policy where the SSRF guard still bites).
  Registering does NOT grant it - the tenant ceiling + caller grants still decide
  (SEC-53).

### S3/S5 - Front-end node surfaces

- **Dependency decision (recorded, disposed by principle, not routed to the user):**
  - **Adopt React Flow (`@xyflow/react`)** for the graph-shaped surfaces - the
    spec's explicit pick, MIT, React-native, purpose-built; the data is genuinely
    graph-shaped (the demonstrated-need test). It was already the foreshadowed
    first UI dependency beyond `react`.
  - **Reject Vercel AI Elements + the AI SDK** for chat: the existing `ChatPanel` +
    SSE already renders the pi_sidecar event shape, so a second chat framework is a
    fragmentation cost for marginal benefit (consolidation-over-fragmentation).
    Chat-as-trigger reuses the existing surface.
- **Workflow canvas (S3.2):** a React Flow canvas added as a view in the existing
  Workflow Studio. Nodes are steps; edges are parent links; node kind (kernel-run /
  service / agent) is derived from the chosen verb's binding; trigger nodes are
  visual entry markers excluded from the executable steps. It serialises to the
  EXACT `definition.steps` shape, so the Round Seven interpreter runs it; saves via
  `upsertWorkflow`, runs via `executeWorkflow`; authorization stays server-side
  (the AdminPanel pattern). Palette from the scoped `GET /v1/capabilities`.

## Invariants (binding-debt 0)

Two new, both bound (`tests/security/test_round_eight.py`): **SEC-52** (SSRF +
NetworkConfig enforcement), **SEC-53** (internet access is a governed, grant +
HITL-gated verb).

## Gate (green)

- `pytest`: **124 passed, 14 skipped** (+5 over Round Seven).
- `check_invariants.py`: **declared=74, bound_tests=98, binding_debt=0, PASS**.
- `ruff check boltrig scripts`: clean. UI `npm run build`: green (with React Flow).

## Honest seams / deferred (per the spec's own open items)

- **Interactive browsing** (navigate/click/sessions) is deliberately not built;
  only read-only `web.fetch` ships (S4.2).
- **Composable sub-workflow recursion** (open item 7.2): reusing the agent
  `max_depth` limit against unbounded workflow-triggering-workflow is undesigned.
- **Live canvas execution state** (7.3): which node is active/failed rendering on
  the canvas vs the log is unresolved; the Execute view shows per-step results.
- **Registry tree editor (S3.1)** is a lighter follow-on; `RouterPanel` already
  shows the scoped registry, and adapter/verb authoring exists in the studios.
- Migrating the legacy direct-write studio routes onto the `control.*` governed
  verbs (open item 7.4) remains the Round Seven follow-on.

This closes the node system spec's central question - internet access resolves as
a governed verb (SSRF-guarded, HITL-gated), not an exception - and adds the visual
canvas over the existing, already-governed workflow data.
