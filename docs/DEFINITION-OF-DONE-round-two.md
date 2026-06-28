# Definition of Done - Round Two (conversational layer, Pi sidecar, MCP wire)

Status against the Round Two DoD (S10). Markers: **done** (implemented + bound to
a test), **seam** (code path real; a live external leg is needed to exercise it).

1. **Pi sidecar runs work** - **done (with seam).** A `pi` capability resolves to
   `PiRuntime` (FR-RUN-01) and runs through the sandboxed sidecar; with no sidecar
   and no keys it degrades and the offline suite is green (FR-RUN-05).
   `fleet/pi_runtime.py`, `services/pi_sidecar/`, `tests/security/test_pi_runtime.py`.
   Seam: a live model key + the running sidecar to exercise real reasoning.
2. **Least privilege proven** - **done.** A Pi/MCP run sees only its granted verbs
   over a run-scoped token; an out-of-scope verb is denied at the chokepoint
   (SEC-23, FR-MCP-02); the sidecar request carries no tool credentials (SEC-27,
   FR-RUN-02); the sandbox is declared no-native-tools, egress kernel+model only
   (SEC-24). `tests/security/test_mcp_face.py`, `test_pi_runtime.py`,
   `tests/integration/test_round_two_manifest.py`.
3. **Chokepoint parity proven** - **done.** A tool call through the MCP face runs
   the full dispatch order with audit + the HITL gate, identically to a direct
   invoke (SEC-26); a Pi run's tool call is denied out-of-scope (FR-RUN-03).
   `tests/security/test_mcp_face.py`, `test_pi_runtime.py`.
4. **Chat end-to-end** - **done.** A chat turn is routed through the fleet (a work
   item linked by run id), streams text/reasoning/tool/sub-agent/HITL events, and
   persists as a retrievable conversation (FR-CONV-04, US-CONV-02/03/05).
   `fleet/chat.py`, `tests/integration/test_chat.py`, the `ui/` Chat panel.
5. **Conversation RBAC** - **done.** One user cannot read or continue another's
   conversation within a tenant; the owner and scoped roles can (SEC-25,
   FR-CONV-06). `tests/security/test_conversations.py`.
6. **Severability extended** - **done.** The kernel and models import nothing from
   Pi or the sidecar (SEC-28); machine-enforced.
   `tests/security/test_severability.py::test_kernel_and_models_have_no_pi_or_sidecar_coupling`.
7. **Thinness preserved** - **done.** Pi, MCP, and chat added services, data, and
   thin layers; the dispatch sequence in `kernel/dispatch.py` is unchanged. The
   MCP face and the chat endpoint are translation over `invoke` and fleet routing.
8. **Governance green** - **done.** All new guarantees (FR-RUN-*, FR-MCP-*,
   FR-CONV-*, SEC-23..28) are bound with catalogue entries; `check_invariants.py`
   passes at binding-debt 0.

## Remaining seams (live external legs)
- A real Pi reasoning run needs a model key + the running sidecar (the loop +
  degrade path are implemented and offline-tested).
- The MCP consumer (`mcp` runtime, US-MCP-03) needs a reachable external MCP
  server to consume in production (proven in-process against Nankle's own face).
- Live Hatchet durable-event resume (carried from Round One) remains a hatchet
  engine detail; the durable-pause property is proven via Postgres.
