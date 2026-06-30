# Binding invariants

A binding invariant is a guarantee Boltrig enforces that is pinned by at least
one test. The catalogue below is the human-readable view; the machine-checkable
map is `tests/invariants.yaml`, and the gate that keeps them honest is
`scripts/check_invariants.py` (run it with `make invariants`).

The gate (the K-29 / K-30 ratchet) fails the build if:

- any declared invariant has **zero** bound tests (an unbound claim), or
- any `@pytest.mark.invariant("X")` marker in `tests/` is **not** declared here
  (an undeclared invariant), or
- the catalogue claims a test node id that no marker actually backs (drift).

Binding debt may only ever decrease. Today: **94 declared, debt 0** (123 bound
test node ids), per `python scripts/check_invariants.py`. `tests/invariants.yaml`
is the authoritative, machine-checked list; the table below is the curated
human-readable view and highlights the core kernel set plus each round's new
guarantees (it does not restate every id - the yaml does).

The ids draw from three families: SRS principles (`P*`), the kernel doctrine
(`K-*`), and SRS security / functional requirements (`SEC-*`, `FR-*`).

**Canonical source of the `K-*` ids (per [2026] VJS-CC NANKLE-CONSOLIDATION 001,
directive D2):** every `K-*` id in this catalogue is the canonical invariant id
from the doctrine's Appendix A, in the `agent-kernel-doctrine` repository
(`volume-1-the-rust-kernel/appendices/appendix-A-invariant-catalog.md`). Boltrig
binds these ids to tests; it does not define or renumber them. The `P*`, `SEC*`
and `FR*` ids are Boltrig-local (drawn from the SRS) and never restate a `K-*`.

## Catalogue

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **P9** | Backend unavailability degrades gracefully, it never crashes the kernel. | `tests/kernel/test_ratelimit_degraded.py::test_degraded_mode_when_backend_down` |
| **K-2** | The tenant permission ceiling caps caller grants (intersection, not union). | `tests/security/test_grant_enforcement.py::test_tenant_ceiling_caps_caller_grants` |
| **K-5** | Deny dominates allow in a GrantSet (a deny beats a covering allow). | `tests/unit/test_grants_model.py::test_deny_dominates_allow` |
| **K-9** | Grant wildcards match on the noun namespace, never a bare prefix collision. | `tests/unit/test_grants_model.py::test_wildcard_does_not_match_prefix_collision` |
| **K-13** | Fail-closed: empty grants deny everything and an unknown verb has no binding. | `tests/kernel/test_dispatch.py::test_unknown_verb_fails_closed`, `tests/unit/test_grants_model.py::test_empty_grants_deny_everything` |
| **K-19** | The audit chain is tamper-evident: re-deriving it detects any reorder, drop, or edit. | `tests/kernel/test_audit_chain.py::test_chain_verifies_and_detects_tampering` |
| **K-20** | Bounded observability: the audit writer scrubs secrets / identity in `detail`. | `tests/security/test_credential_isolation.py::test_audit_scrubs_secret_in_detail` |
| **SEC-05** | Resolved credential material never enters the audit log. | `tests/security/test_credential_isolation.py::test_secret_material_never_enters_audit` |
| **SEC-07** | A verb is denied unless the caller holds the matching grant. | `tests/security/test_grant_enforcement.py::test_ungranted_verb_is_denied`, `tests/security/test_grant_enforcement.py::test_grant_for_other_verb_does_not_authorise` |
| **SEC-08** | Tenant isolation: no cross-tenant discovery or dispatch (fail-closed). | `tests/security/test_tenant_isolation.py::test_other_tenant_cannot_see_this_tenants_verbs`, `tests/security/test_tenant_isolation.py::test_other_tenant_dispatch_fails_closed` |
| **SEC-13** | PII is detected and redacted before it leaves the boundary. | `tests/security/test_budget_and_pii.py::test_pii_redaction` |
| **SEC-14** | High-consequence / blocking verbs pause for human approval and cannot be bypassed by an agent. | `tests/security/test_hitl_gate.py::test_blocking_verb_pauses_for_approval`, `tests/security/test_hitl_gate.py::test_resumes_after_approval` |
| **SEC-16** | Every action (allowed or denied) is audited, append-only, and hash-chained. | `tests/kernel/test_audit_chain.py::test_every_action_is_audited`, `tests/kernel/test_audit_chain.py::test_denied_actions_are_also_audited` |
| **SEC-21** | Verb params are schema-validated before any dispatch side effect. | `tests/kernel/test_dispatch.py::test_invalid_params_rejected_before_dispatch` |
| **FR-KER-05** | Per-verb / per-tenant rate limits are enforced at the kernel. | `tests/kernel/test_ratelimit_degraded.py::test_rate_limit_enforced` |
| **FR-COST-02** | A hard-stop budget halts before exceeding; a soft budget records overage only. | `tests/security/test_budget_and_pii.py::test_budget_hard_stop_halts_before_exceeding`, `tests/security/test_budget_and_pii.py::test_soft_budget_does_not_halt` |

### Round Three (authoring studios, admin, observability, eval, personal agents, memory)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-29** | Test-spawns / eval run under the initiator's grants - no escalation. | `tests/security/test_round_three.py::test_test_spawn_cannot_escalate` |
| **SEC-30** | A personal agent acts only with the owner's delegated authority (on-behalf-of, capped). | `tests/security/test_round_three.py::test_personal_agent_is_delegated_only` |
| **SEC-31** | Memory is scope-isolated - cross-user / cross-department reads are denied. | `tests/security/test_round_three.py::test_memory_scope_isolation` |
| **SEC-32** | Authoring / admin is RBAC-gated and audited with the actor. | `tests/security/test_round_three.py::test_authoring_requires_role_and_is_audited` |
| **SEC-33** | Cost / audit / runs insight is scope-filtered - a dept cannot read another's. | `tests/security/test_round_three.py::test_audit_and_runs_are_scope_filtered` |
| **FR-OBS-02** | The audit browser is scope-filtered (search / run links preserved). | `tests/security/test_round_three.py::test_audit_and_runs_are_scope_filtered` |
| **FR-EVAL-02** | An eval runs through the chokepoint under a defined scope, no escalation. | `tests/security/test_round_three.py::test_eval_runs_without_escalation` |
| **FR-ADM-02** | Admin config round-trips to a manifest and supports rollback (C1, NFR-REL-01). | `tests/integration/test_round_three_studios.py::test_admin_config_round_trips` |
| **FR-WFS-04** | A registered workflow becomes a live durable run with the durable executor. | `tests/integration/test_round_three_studios.py::test_workflow_live_durable_registration` |
| **FR-ADS-02** | Adapter Studio binds a generated adapter's verbs only after a named review (gate). | `tests/integration/test_round_three_studios.py::test_adapter_studio_review_gate` |

### Round Four (settings, account & access management)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-34** | A personal access token never escalates (scope ∩ current grants, re-checked) and a deactivated / de-provisioned user's tokens stop working. | `tests/security/test_round_four.py::test_pat_never_escalates_and_dies_with_user` |
| **SEC-35** | Invitations do not bypass the IdP - they pre-stage a role/scope, grant no access until SSO login, and are consumed once. | `tests/security/test_round_four.py::test_invitations_do_not_bypass_idp` |
| **SEC-36** | Settings writes enforce RBAC server-side and are audited with the actor. | `tests/security/test_round_four.py::test_settings_changes_are_authz_checked_and_audited` |
| **SEC-37** | Headless REST / MCP runs the same chokepoint scoped to the user - no weak path. | `tests/security/test_round_four.py::test_headless_parity_no_weak_path` |
| **SEC-38** | No unauthenticated access to tokens or connection details (mobile / web follow the same auth rules). | `tests/security/test_round_four.py::test_no_unauthenticated_access_to_tokens` |
| **SEC-39** | An authored verb with a destructive / outbound name defaults to high-consequence so the HITL gate engages. | `tests/security/test_round_four.py::test_authored_verbs_safe_by_default` |

### Round Five (kernel-governed structured memory)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-40** | The kernel is the memory isolation boundary at ingestion AND retrieval - a hostile cross-scope edge (incl multi-hop) cannot leak an out-of-scope fact. | `tests/security/test_round_five.py::test_kernel_is_the_isolation_boundary` |
| **SEC-41** | Recalled memory is data, never authority - it cannot grant a caller a verb they lack. | `tests/security/test_round_five.py::test_memory_cannot_escalate` |
| **SEC-42** | Content is screened for injection/malware before it becomes memory; poison is rejected, never persisted. | `tests/security/test_round_five.py::test_ingestion_screens_poison` |
| **SEC-43** | Sensitive memory must use a local endpoint; a misroute is blocked and audited. | `tests/security/test_round_five.py::test_sensitive_memory_stays_local` |
| **SEC-44** | Erasure is complete (node + derived edges/facts), engine-confirmed, ledgered and audited. | `tests/security/test_round_five.py::test_complete_audited_erasure` |
| **SEC-45** | Recall is least-privilege and audited - query and count recorded, fact contents never. | `tests/security/test_round_five.py::test_recall_is_audited_without_leaking_contents` |

### Round Six (pi runtime: continuity, model gateway, egress)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-46** | Conversation continuity is deterministic and append-only - an earlier turn's render is a prefix of a later one (prefix stability for the gateway cache) - and adds no authority (it composes only persisted text). | `tests/security/test_round_six.py::test_continuity_is_deterministic_and_append_only` |
| **SEC-47** | The model gateway binds per conversation (not per run), pins a conversation to one model across turns, and never re-routes sensitive data (residency preserved). | `tests/security/test_round_six.py::test_gateway_binds_per_conversation_not_run`, `::test_gateway_never_reroutes_sensitive_and_is_inert_when_unset` |
| **SEC-48** | The Pi sidecar's network egress is enforced by the deploy manifests (sandbox-only; internal in the secure overlay), not merely documented. | `tests/security/test_round_six.py::test_pi_sidecar_egress_is_enforced_in_manifests` |
| **SEC-49** | Continuity is scope-safe - only the caller's own tenant/conversation history is ever composed into a prompt. | `tests/security/test_round_six.py::test_continuity_only_composes_the_callers_own_conversation` |

### Round Seven (control plane: interpreter, live profiles, governed writes)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-CTL-01** | Agent / department profile config takes effect live (re-read per call via the provider), with no router reconstruction. | `tests/integration/test_round_seven.py::test_chief_of_staff_reloads_departments_live` |
| **FR-CTL-02** | The generic interpreter executes a stored workflow's steps in dependency order, each as its own durable boundary through the kernel, skipping descendants of a failed step. | `tests/integration/test_round_seven.py::test_interpreter_runs_steps_in_dependency_order_each_durable`, `::test_interpreter_skips_descendants_of_a_failed_step` |
| **SEC-50** | Every workflow step is dispatched through the kernel chokepoint under the caller's own grants - a step can neither escalate nor bypass governance. | `tests/security/test_round_seven.py::test_workflow_step_cannot_escalate_past_caller_grants` |
| **SEC-51** | Control-plane config writes are dispatched as kernel verbs (grant-checked, audited, HITL-gateable), not an ungoverned store write. | `tests/security/test_round_seven.py::test_control_plane_write_is_grant_checked`, `::test_control_plane_write_is_hitl_gated_and_audited` |

### Round Eight (node system: internet access as a governed verb)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-52** | `web.fetch` is SSRF-guarded and NetworkConfig-enforced - private/loopback/link-local/metadata targets, blocked or non-allowed domains, and air-gap are refused before any network call. | `tests/security/test_round_eight.py::test_ssrf_guard_blocks_internal_addresses`, `::test_network_policy_enforced`, `::test_adapter_refuses_internal_target_before_any_fetch` |
| **SEC-53** | Internet access is a governed verb - `web.fetch` runs the chokepoint (grant-checked and HITL-gated as a high-consequence verb), so it cannot bypass the kernel and injected content cannot escalate. | `tests/security/test_round_eight.py::test_web_fetch_is_grant_checked`, `::test_web_fetch_is_hitl_gated` |

### Round Nine (stack boundary)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-54** | The stack foundation layers never depend upward - `models`/`store`/`adapters` import only the foundation, keeping the seam a future repo-split would cleave along clean. | `tests/security/test_severability.py::test_foundation_layers_do_not_depend_upward` |

### Round Ten (the event backbone)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-EVT-01** | A verb invoked under a run publishes a paired `tool_call` + `tool_result` to that run's stream; a failed call reports status with no output leak. | `tests/security/test_round_ten.py::test_verb_publishes_paired_tool_events`, `::test_failed_verb_emits_error_result_without_leaking` |
| **FR-EVT-02** | Run events are a pure side-channel - a relay failure never breaks a call, a call with no run_id publishes nothing, and a paused call surfaces a `hitl` event. | `tests/security/test_round_ten.py::test_no_run_id_publishes_nothing_and_call_still_works`, `::test_relay_failure_never_breaks_dispatch`, `::test_pending_human_emits_hitl_event` |
| **SEC-55** | Run events are run-keyed and credential-free - a verb's events publish only to its own run's stream and never carry credential material. | `tests/security/test_round_ten.py::test_events_are_run_keyed_and_credential_free` |

### Round Fifteen (the extension contract)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-SKILL-01** | The skill shelf (`skill.search`) returns lightweight descriptions only, never the body, and filters by query (progressive disclosure). | `tests/security/test_round_fifteen.py::test_skill_search_returns_descriptions_not_bodies` |
| **FR-SKILL-02** | `skill.load` composes the inheritance-merged body bound to the job's context, validated against `context_requirements`. | `tests/security/test_round_fifteen.py::test_skill_load_composes_body_and_binds_context` |
| **SEC-57** | The skill shelf runs the chokepoint (grant-checked, tenant-scoped) and a loaded skill is data not authority - `load` returns the skill's `tool_grants` but does not grant them, so it cannot escalate. | `tests/security/test_round_fifteen.py::test_skill_shelf_is_governed_and_load_does_not_escalate` |
| **FR-EXT-01** | A project adapter declared in the manifest by `module_ref` (a non-builtin id) is imported and registered at boot - extend from outside, no core edit. | `tests/integration/test_round_fifteen_bundle.py::test_project_adapter_loads_by_module_ref` |
| **FR-EXT-02** | External MCP servers declared in the manifest `mcp.consume` register inert at boot, exposing no verbs until the review/activate gate (SEC-22 preserved). | `tests/integration/test_round_fifteen_bundle.py::test_consumed_mcp_servers_register_inert_pending_review` |

### Round Sixteen (security hardening - the buildable code controls)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-58** | Edge/web hardening - security headers on every response, Host validation, request-body cap (WEB-02/03/06, RES-01). | `tests/security/test_round_sixteen.py::test_security_headers_host_and_body_cap` |
| **SEC-59** | JWT verification pins an algorithm allowlist, rejects an ID token used as an access token, and rejects a token with no expiry (IAM-02/03/04). | `tests/security/test_round_sixteen.py::test_jwt_alg_allowlist_and_access_token_only` |
| **SEC-60** | Dev auth is impossible in production - the header-trusting resolver refuses to start with a production signal (IAM-09). | `tests/security/test_round_sixteen.py::test_dev_auth_refuses_production_signal` |
| **SEC-61** | The shared egress guard blocks cloud-metadata / link-local targets for every HTTP adapter, closing SSRF -> IMDS token theft (INJ-02 / CLOUD-03). | `tests/security/test_round_sixteen.py::test_shared_egress_guard_blocks_metadata` |
| **SEC-62** | A Unicode-confusable / non-canonical verb id can never match a grant (NFKC + safe charset) (UPLOAD-05 / AZ-02). | `tests/security/test_round_sixteen.py::test_confusable_verb_id_never_matches_a_grant` |
| **SEC-63** | An inbound webhook outside the replay window is rejected, so a captured signed request cannot replay forever (ADP-08). | `tests/security/test_round_sixteen.py::test_webhook_replay_window` |

### Round Seventeen (container hardening)

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-64** | The first-party app containers are hardened (INF-01) - read-only rootfs, all caps dropped, no-new-privileges, resource-capped, non-root images - enforced in the deploy manifests. | `tests/security/test_round_seventeen.py::test_app_containers_are_hardened`, `::test_app_images_run_non_root` |

## How a new invariant is added

1. Write the test and mark it: `@pytest.mark.invariant("NEW-ID")`.
2. Declare it in `tests/invariants.yaml` with a one-line description and the
   test node id(s).
3. Document it in the table above.
4. Run `make invariants` (gate must stay at debt 0) and `make test`.
