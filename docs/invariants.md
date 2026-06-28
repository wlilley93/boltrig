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

Binding debt may only ever decrease. Today: **16 declared, 16 bound, debt 0**
(22 bound test node ids).

The ids draw from three families: SRS principles (`P*`), the kernel doctrine
(`K-*`), and SRS security / functional requirements (`SEC-*`, `FR-*`).

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

## How a new invariant is added

1. Write the test and mark it: `@pytest.mark.invariant("NEW-ID")`.
2. Declare it in `tests/invariants.yaml` with a one-line description and the
   test node id(s).
3. Document it in the table above.
4. Run `make invariants` (gate must stay at debt 0) and `make test`.
