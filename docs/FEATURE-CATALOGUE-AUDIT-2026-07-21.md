# Feature catalogue audit - 2026-07-21

Scope: all 30 buyer-facing claims in `site/src/data/features.ts`, checked against the current
kernel, fleet, console, deployment configuration, invariant catalogue, and automated tests.

## Result

The catalogue needed updating. The shipped paths remain covered and no new blocking regression
was found, but five claims crossed an implementation boundary. The catalogue and relevant console
copy now describe those boundaries explicitly:

1. A cron specification can be validated and persisted, but no internal cron runner starts it.
2. Budget hard stops are enforced by the fleet spawner for organisation and department scopes.
   Workflow scopes and window values are stored policy metadata, and counter reset is manual.
3. Memory always records a source kind, but a manual fact may omit its source reference.
4. `channel.send` delivers through a configured outbound URL. Socket delivery without that URL is
   still the documented sidecar queue seam.
5. HTTP/OpenAPI, SQL, MCP, Graph, Jira, CRM, browser, and channel integration paths exist, while
   the generic MQ, OCR, and file-share drivers remain seams and are no longer marketed as live.
6. The first-party Knowledge slice now supports canonical text, Markdown, and PDF originals,
   permission-first exact, lexical, and vector-overlap retrieval, stable revision/segment
   citations, and governed erasure.
   Other formats and external provider connections remain later work.

## Per-feature trace

`Verified` means the claim has a concrete implementation and automated coverage. `Bounded` means
the implementation is real after the wording is narrowed to its shipped boundary.

| # | Catalogue feature | Result | Primary evidence |
|---|---|---|---|
| 1 | One place to delegate | Verified | `ui/src/panels/ChatPanel.tsx`, `ui/src/panels/KanbanPanel.tsx`, `tests/integration/test_delegation_pump.py` |
| 2 | Governed agent profiles | Verified | `boltrig/config/control_plane.py`, `ui/src/panels/agentsSlide/AgentCreateCard.tsx`, `ui/tests/__characterization__/panels/AgentStudio.test.tsx` |
| 3 | Governed workflows | Bounded | `boltrig/workflows/interpreter.py`, `tests/integration/test_workflow_trigger.py`, `ui/e2e/workflow-live.spec.ts` |
| 4 | Work board | Verified | `boltrig/fleet/pump.py`, `tests/security/test_work_detail.py`, `ui/tests/__characterization__/panels/WorkBoard.test.tsx` |
| 5 | Reusable skills | Verified | `boltrig/skills/shelf.py`, `tests/unit/test_skill_discovery.py`, `tests/integration/test_round_fifteen_bundle.py` |
| 6 | Scoped permissions | Verified | `boltrig/kernel/grants.py`, `tests/security/test_grant_enforcement.py`, `tests/security/test_workspace_grants.py` |
| 7 | Human approvals | Verified | `boltrig/kernel/approval_gate.py`, `tests/security/test_hitl_gate.py`, `tests/security/test_hitl_access.py` |
| 8 | Secrets stay server-side | Verified | `boltrig/kernel/credentials.py`, `tests/security/test_credential_isolation.py`, `tests/security/test_mcp_consumer_credential.py` |
| 9 | Scoped cost boundaries | Bounded | `boltrig/kernel/cost.py`, `boltrig/fleet/spawn.py`, `tests/security/test_budget_and_pii.py` |
| 10 | Sensitive routing | Verified | `boltrig/fleet/model_router.py`, `tests/security/test_sensitive_routing.py`, `tests/security/test_model_routing.py` |
| 11 | Live execution stream | Verified | `boltrig/kernel/events.py`, `tests/kernel/test_event_relay.py`, `tests/security/test_chat_streaming_richness.py` |
| 12 | Run inspector | Verified | `boltrig/observability/tree.py`, `ui/src/panels/RunView.tsx`, `ui/tests/__characterization__/panels/RunView.test.tsx` |
| 13 | Audit and scoped reporting | Verified | `boltrig/kernel/audit.py`, `tests/kernel/test_audit_chain.py`, `tests/security/test_audit_tree_scope.py` |
| 14 | Knowledge with citations | Bounded | `boltrig/knowledge/service.py`, `tests/knowledge/test_knowledge_service.py`, `ui/src/panels/KnowledgePanel.tsx` |
| 15 | Evaluation cases | Verified | `boltrig/fleet/eval.py`, `tests/security/test_eval_case_listing.py`, `ui/tests/__characterization__/panels/EvalPanel.test.tsx` |
| 16 | Console chat | Verified | `boltrig/fleet/chat.py`, `tests/integration/test_chat.py`, `ui/e2e/chat.spec.ts` |
| 17 | Headless engine | Verified | `boltrig/kernel/app.py`, `boltrig/kernel/mcp.py`, `tests/kernel/test_app.py` |
| 18 | MCP in and out | Verified | `boltrig/kernel/mcp.py`, `boltrig/adapters/mcp_consumer.py`, `tests/integration/test_mcp_consumer.py` |
| 19 | Signed channel intake | Verified | `boltrig/kernel/channel_routes.py`, `tests/security/test_channel_inbound.py`, `tests/security/test_channel_gateway_routes.py`, `tests/security/test_channel_gateway_roundtrip.py` |
| 20 | Governed outbound | Bounded | `boltrig/adapters/builtin/channel_send.py`, `tests/security/test_channel_send.py` |
| 21 | Deployment bundles | Verified | `boltrig/config/manifest.py`, `docs/extension-contract.md`, `tests/integration/test_round_fifteen_bundle.py` |
| 22 | Live authoring | Verified | `boltrig/config/control_plane.py`, `tests/security/test_control_plane_parity.py`, `ui/tests/__characterization__/panels/governedControlMutations.test.tsx` |
| 23 | External systems | Bounded | `boltrig/adapters/generator.py`, `boltrig/adapters/http_base.py`, `boltrig/adapters/mcp_consumer.py`, `tests/integration/test_generated_adapter.py` |
| 24 | Domain guardrails | Verified | `boltrig/workflows/control_flow.py`, `boltrig/kernel/dispatch.py`, `tests/integration/test_control_flow.py` |
| 25 | No core fork | Verified | `scripts/check_architecture.py`, `tests/security/test_severability.py`, `tests/unit/test_architecture_gate.py` |
| 26 | Self-hosted stack | Verified | `docker-compose.yml`, `tests/deploy/test_compose_hardening.py` |
| 27 | Organisation and workspace access | Verified | `boltrig/kernel/access_routes.py`, `tests/security/test_first_party_login.py`, `tests/security/test_tenancy_management.py` |
| 28 | Private credentials | Verified | `boltrig/kernel/credentials.py`, `tests/security/test_ai_keys.py`, `tests/security/test_credential_isolation.py` |
| 29 | Production deploys | Verified | `deploy/compose.release.yml`, `tests/deploy/test_release_images.py`, `tests/deploy/test_compose_hardening.py` |
| 30 | Tested guarantees | Verified | `tests/invariants.yaml`, `scripts/check_invariants.py`, `.github/workflows/ci.yml` |

## Follow-up implementation gaps

These are product gaps, not claims in the corrected catalogue:

- Add an actual scheduled-workflow runner before advertising unattended cron execution.
- Add durable window rollover and workflow-scope enforcement before presenting those budget fields
  as active hard-stop boundaries.
- Add a real socket delivery queue and consumer before claiming Slack or Discord delivery.
- Wire and harden the MQ, OCR, and file-share adapter seams before listing them as connectors.
- Add Office, image/OCR, audio/video, email, web-capture, and structured-data representations
  before broadening Knowledge beyond text, Markdown, and PDF.
- Bind credential-backed Supermemory and Mem0 Knowledge projection adapters before describing
  their provider-catalogue entries as active external connections.
