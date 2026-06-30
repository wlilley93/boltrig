# Binding invariants

A binding invariant is a guarantee Nankle enforces that is pinned by at least
one test. The catalogue below is the human-readable view; the machine-checkable
map is `tests/invariants.yaml`, and the gate that keeps them honest is
`scripts/check_invariants.py` (run it with `make invariants`).

The gate (the K-29 / K-30 ratchet) fails the build if:

- any declared invariant has **zero** bound tests (an unbound claim), or
- any `@pytest.mark.invariant("X")` marker in `tests/` is **not** declared here
  (an undeclared invariant), or
- the catalogue claims a test node id that no marker actually backs (drift).

Binding debt may only ever decrease. Today: **68 declared, debt 0** (87 bound
test node ids), per `python scripts/check_invariants.py`. `tests/invariants.yaml`
is the authoritative, machine-checked list; the table below is the curated
human-readable view and highlights the core kernel set plus each round's new
guarantees (it does not restate every id - the yaml does).

The ids draw from three families: SRS principles (`P*`), the kernel doctrine
(`K-*`), and SRS security / functional requirements (`SEC-*`, `FR-*`).

**Canonical source of the `K-*` ids (per [2026] VJS-CC NANKLE-CONSOLIDATION 001,
directive D2):** every `K-*` id in this catalogue is the canonical invariant id
from the doctrine's Appendix A, in the `agent-kernel-doctrine` repository
(`volume-1-the-rust-kernel/appendices/appendix-A-invariant-catalog.md`). Nankle
binds these ids to tests; it does not define or renumber them. The `P*`, `SEC*`
and `FR*` ids are Nankle-local (drawn from the SRS) and never restate a `K-*`.

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

## How a new invariant is added

1. Write the test and mark it: `@pytest.mark.invariant("NEW-ID")`.
2. Declare it in `tests/invariants.yaml` with a one-line description and the
   test node id(s).
3. Document it in the table above.
4. Run `make invariants` (gate must stay at debt 0) and `make test`.
