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

Binding debt may only ever decrease. Today: **245 declared, debt 0** (492 bound
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
| **FR-GW-03** | Platform status reports the stack-owned model gateway as configured or inert, with cache/profile posture only, and never exposes gateway URLs, keys, tokens, or credentials. | `tests/security/test_platform_status.py::test_model_gateway_status_is_bounded_and_redacted`, `::test_model_gateway_status_reports_inert_when_unconfigured` |
| **FR-GW-04** | Optional model-gateway live health polling is internal-host-only, bounded, fail-safe, and exposes only coarse health/cache/provider counts without gateway URLs, keys, tokens, or credentials. | `tests/security/test_model_gateway_live_health.py::test_model_gateway_live_health_polls_internal_endpoint_and_redacts_payload`, `::test_model_gateway_live_health_rejects_external_hosts_without_polling`, `::test_model_gateway_live_health_probe_failure_degrades_not_crashes`, `tests/security/test_model_routing.py::test_manifest_model_profiles_feed_runtime_resolver` |
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

### Self-improvement competence ([2026] VJS-COUNTY 5)

The self-improvement loop may raise COMPETENCE (reuse ranking / likelihood) but
never AUTHORITY (grants, scope, tier, or the HITL gate). SEC-84 pins that
provenance carries no authority; these pin the newer legs that only ever move
ranking, always through the one dispatch chokepoint under the caller ceiling.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **US-WFL-08** | Reuse promotion is eval-gated and competence-only - a generated/learned workflow is preferred only after it passes its eval cases (run through the chokepoint under the initiator ceiling, SEC-29); a later fail demotes it; the `WorkflowPromotion` record carries no authority field, so promotion changes ranking, never grants/scope/tier or the executable content. | `tests/security/test_self_improvement_competence.py::test_promotion_record_carries_no_authority_field`, `::test_promotion_is_eval_gated_and_changes_ranking_only` |
| **US-WFL-09** | Harvested free signals (regenerate-supersede, HITL verdict) reweight reuse via `memory.improve` (reweight-only, no scope/grant argument) and a bounded promotion score in [-1, 1] that never moves the eval-gated state; every harvest is best-effort so it can never fail the run that produced it (P9). | `tests/security/test_self_improvement_competence.py::test_harvested_signal_reweights_reuse_only`, `::test_harvest_reuse_signal_is_reweight_only_and_best_effort` |
| **US-WFL-10** | Post-run reflection is opt-in and rides the chokepoint - enabled, a terminal item stores exactly one lesson through `kernel.invoke` (audited `memory.remember`); disabled, none; `build_org` wires the pump the kernel so the memory verb is reachable but stays off by default. | `tests/security/test_self_improvement_competence.py::test_reflection_is_opt_in_through_the_chokepoint`, `::test_build_org_wires_the_kernel_so_reflection_is_reachable` |

### Streaming-richness chat contracts (tool events / heartbeat / questions)

Three additive contracts on the conversational SSE stream, each built on the
existing kernel machinery (the one dispatch chokepoint, the event relay, the HITL
manager), never a parallel mechanism. The run relay keeps the full tool payloads
for the run canvas + durable audit (FR-EVT-01); the chat stream forwards a bounded
projection so the browser never receives raw verb input/output.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **US-CHAT-10** | Tool events on the chat stream are keys + summaries only and paired - a verb dispatched under a turn publishes a `tool_call` (`tool`, `call_id`, `args_summary` = key names + count) and a paired `tool_result` (`call_id`, `status`, `result_summary` = key names), carrying no raw input/output, so a client can render a tool callout without the payload. | `tests/security/test_chat_streaming_richness.py::test_chat_tool_events_are_bounded_and_paired` |
| **US-CHAT-11** | The SSE heartbeat keeps a slow-but-alive stream open and stops on a terminal event - periodic `heartbeat` frames at the `ChatConfig` interval until content/terminal arrives (none at/after terminal), never persisted as turn content, and a zero/negative interval disables it. | `tests/security/test_chat_streaming_richness.py::test_heartbeat_keeps_slow_stream_open_then_stops_on_terminal`, `::test_heartbeat_can_be_disabled` |
| **US-CHAT-12** | The governed `chat.ask_user` verb pauses the run on the existing HITL machinery - through the one chokepoint under the caller ceiling it creates a `HITLType.QUESTION` bound to the run/work item, emits a rich `question` event (`question_id`, `prompt`, `choices`), raises `PendingHuman` (audited `pending_human`), and is grant-ceilinged like any verb. | `tests/security/test_chat_streaming_richness.py::test_ask_user_pauses_via_hitl_and_emits_question`, `::test_ask_user_is_grant_ceilinged_like_any_verb` |
| **SEC-88** | Chat tool events never leak verb values (K-20 on the user-facing surface) - a secret/untrusted value passed to a verb appears nowhere on the chat stream nor in the persisted turn events (only key names + counts), while the full payload still exists on the run relay for the canvas + durable audit. | `tests/security/test_chat_streaming_richness.py::test_chat_tool_events_never_leak_verb_values` |
| **SEC-89** | The questions answer route is owner-only, fail-closed, audited and `wrap_untrusted`-enveloped - `POST /v1/hitl/{id}/answer` answers only a QUESTION (an approval id is refused 409, never laundered into clearing a gated verb), a non-owner/scoped-read caller is 403 with no write and no resume fired, the owner's answer is enveloped before it is recorded (the ordinary resume wiring replays it as data), and the audit row carries the answer length only, never the text. | `tests/security/test_chat_streaming_richness.py::test_answer_route_owner_only_wrapped_and_audited`, `::test_answer_route_refuses_to_answer_an_approval` |

### Conversation history: pagination + owner-scoped search (US-CONV-09/10)

Two additive read surfaces over the existing owner-scoped conversation store,
never a new search engine or a parallel store. Pagination bounds the list under a
`ChatConfig` ceiling with a deterministic order; search is a plain case-insensitive
substring over the caller's own titles + live message content, parameterised and
fail-closed to the caller's scope. The unpaginated list is untouched for callers
that do not opt in.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-CONV-07** | The conversation list paginates stably and bounded - `list_conversations_page` returns one owner-scoped page ordered `updated_at` DESC with an id ASC tiebreak (deterministic for equal timestamps) plus the next offset (None once exhausted), the page size is a `ChatConfig` ceiling a caller-supplied `limit` is clamped down to (None => the conservative default, never zero rows), and the original unpaginated `list_conversations` still returns everything. | `tests/store/test_conversation_pagination.py::test_page_is_stable_ordered_and_next_offset_walks_to_exhaustion`, `::test_id_tiebreak_is_deterministic_for_equal_updated_at`, `::test_page_is_owner_scoped`, `::test_unpaginated_list_still_returns_everything`, `::test_config_clamps_page_size_under_the_max_ceiling`, `tests/integration/test_chat.py::test_http_conversation_list_is_backward_compatible_and_paginates` |
| **SEC-94** | Conversation search is owner-scoped and fail-closed - `search_conversations` matches (case-insensitive substring) only over the caller's own conversation titles + live message content, so another user's conversation is never returned even when it matches the same term; it carries the matched live message content as a snippet (None when only the title matched); results are paginated + bounded. | `tests/security/test_conversation_search.py::test_search_is_owner_scoped_never_returns_another_users_conversation`, `::test_search_matches_title_and_live_message_with_snippet`, `::test_search_results_are_paginated_and_bounded`, `tests/integration/test_chat.py::test_http_conversation_search_is_owner_scoped` |
| **SEC-95** | Superseded turns never surface as a live search match ([2026] VJS-COUNTY 4) - search only considers messages with `superseded_by IS NULL`, so a regenerated-away reply's term yields no hit while the same term in the live replacement does. | `tests/security/test_conversation_search.py::test_superseded_message_is_not_a_live_search_hit` |
| **SEC-96** | Conversation search has no SQL/wildcard injection surface - the query is a bound parameter (never string-interpolated) with LIKE metacharacters escaped (`\` `%` `_`) and an ESCAPE clause, so a caller-supplied `%`/`_` is matched literally as a substring, never as a wildcard. | `tests/security/test_conversation_search.py::test_like_metacharacters_are_escaped_not_wildcards` |

### Org -> workspace tenancy foundation ([2026] VJS-COUNTY 8)

The foundation phase of org/workspace tenancy: the data model + membership, added
ON TOP of the existing `tenant_id` isolation key without rewiring any existing read.
The ORGANISATION is the tenant boundary - an org row's id IS the `tenant_id` (one
org per tenant_id) - so RLS stays keyed on `tenant_id`. A workspace belongs to an
org; `org_members` and `workspace_members` are the memberships. Later phases thread
a workspace scope through the InvocationContext, switching, per-org AI keys, and
workflow scoping.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-ORG-01** | A workspace always belongs to an org (D1/D2) - an organisation row's id IS the `tenant_id` (one org per tenant_id) and every workspace carries that org as its `tenant_id`, so a workspace is never an orphan; get/list workspace reads are tenant-scoped to the owning org. | `tests/store/test_tenancy.py::test_workspace_always_belongs_to_an_org` |
| **FR-ORG-02** | The organisation id IS the `tenant_id` and the default-org backfill is idempotent (D1) - `ensure_default_org` creates at most one org per tenant_id (id == tenant_id) and a repeat call never creates a second, so existing single-tenant deploys get exactly one implicit org. | `tests/store/test_tenancy.py::test_ensure_default_org_is_idempotent_and_id_is_tenant_id` |
| **SEC-103** | Org/workspace tenancy reads are tenant-scoped and never cross tenants (SEC-08) - get/list of org, workspace and both memberships, plus the switching-seam queries (`list_orgs_for_user` / `list_workspaces_for_user`), only ever return rows inside the bound tenant, and a remove under the wrong tenant is a no-op. | `tests/security/test_tenancy_isolation.py::test_tenancy_reads_are_tenant_scoped_never_cross_tenant` |
| **SEC-104** | A per-workspace role is always one of the allowed set (owner/admin/member/viewer/agent, D3) - `add_workspace_member` refuses an out-of-set role (`SchemaValidationError`) so it can never be persisted, while every allowed role is accepted. | `tests/security/test_tenancy_isolation.py::test_workspace_role_must_be_in_the_allowed_set` |
| **SEC-105** | The four tenancy tables are RLS-fenced (SEC-08) - `workspaces`, `org_members` and `workspace_members` are in the `rls.sql` generic `tenant_id`-scoped set, and `organisations` is fenced by its own id-keyed policy (its id IS the tenant_id), all four defined in `schema.sql`. | `tests/security/test_tenancy_isolation.py::test_the_four_tenancy_tables_are_rls_scoped` |

### Session active workspace context + switching ([2026] VJS-COUNTY 8, D4)

The active-context phase: the active WORKSPACE lives on the session and is threaded
through the `InvocationContext`, with an owner-only, membership-re-authorized switch.
Authorization is unchanged this phase (the plumbing half of D11): the workspace is
carried on the context but not yet read to compute grants. The active workspace is
only a hint - the session resolver RE-AUTHORIZES it against `workspace_members` on
every request, fail-closed to no active workspace, so a stale or client-supplied
value never confers access.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-ORG-03** | The active workspace is plumbed through the session onto the `InvocationContext` and login seeds a deterministic default (D4) - login picks a stable default active workspace from membership (or None when the user belongs to none), persists it on the session, and the resolver surfaces it onto the principal so `principal.context().workspace_id` carries it; `pick_default_workspace` is deterministic regardless of store iteration order. | `tests/security/test_active_context.py::test_login_seeds_deterministic_default_and_context_carries_workspace`, `::test_pick_default_workspace_is_deterministic_or_none` |
| **SEC-106** | Switching the active workspace is membership-re-authorized and fail-closed (D4) - `POST /v1/me/active-context` refuses an unknown workspace 404 and a non-member workspace 403, both with NO write, so a client can never set an active workspace it is not a member of; a valid member switch persists on the session and is audited keys-only. | `tests/security/test_active_context.py::test_switch_is_membership_reauthorized_and_fail_closed` |
| **SEC-107** | A revoked-membership session drops to no active workspace (D4, fail-closed re-auth) - the resolver re-authorizes the persisted active workspace against CURRENT membership every request via `resolve_active_workspace`, so once membership is revoked (or the workspace deleted) the resolved active workspace becomes None (never the stale value) and the `InvocationContext` carries no workspace. | `tests/security/test_active_context.py::test_revoked_membership_session_drops_to_no_active_workspace` |

### Grant resolution from workspace membership ([2026] VJS-COUNTY 8, D11)

The authorization leg: when a caller operates INSIDE an active workspace they are a
member of, their org/user grants are NARROWED by that workspace role's ceiling
(`effective = org grants ∩ ceiling`) at the grant-resolution path
(`effective_grants_for_request`, called by the session resolver). This composes with
[2026] VJS-COUNTY 5 - authority is only ever intersected DOWN, never widened. The
one chokepoint (`GrantChecker`) then enforces these already-narrowed effective grants
unchanged, so no workspace logic scatters into the routes. The WorkspaceRole ceilings
(beside the RBAC role mapping in `rbac.py`): **owner** = broad (the org grants,
unchanged); **admin** = operate + configure (all but the owner-only
`control.workspace.*` self-administration); **member** / **agent** = operate only
(the `control.*` configure namespace denied); **viewer** = read-only (only concrete
read verbs survive; wildcards collapse fail-closed). THE CRITICAL RULE: a caller with
NO active workspace (every existing single-tenant deploy, and the backfilled default
org with no workspaces) keeps EXACTLY today's grants - no narrowing.

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-108** | An active-workspace member's authority is the INTERSECTION of their org/user grants and their workspace-role ceiling, never a union (D11, composes with COUNTY 5) - `effective_grants_for_request` narrows via `narrow_grants_to_workspace` for a member of an active workspace, so the result is always a SUBSET of the org grants (owner keeps them broad, member loses the `control.*` configure namespace) and a membership can only intersect authority DOWN, never widen it. | `tests/security/test_workspace_grants.py::test_active_member_authority_is_org_grants_intersected_with_ceiling`, `::test_membership_only_narrows_never_widens` |
| **SEC-109** | A viewer in a workspace cannot perform a write verb their org role would otherwise allow (D11 read-only ceiling) - the viewer narrowing keeps only base allow-patterns that authorise a concrete read action (wildcards collapse, fail-closed), so a caller whose org grants include a write verb (or `ticket.*`) is denied that write while retaining their explicit read grants. | `tests/security/test_workspace_grants.py::test_viewer_cannot_write_but_keeps_reads` |
| **SEC-110** | A caller with NO active workspace keeps their FULL org grants unchanged (D11 backward-compat, the critical rule) - `effective_grants_for_request` returns exactly `current_grants_for_user` when `active_workspace_id` is None, and applies no narrowing when the caller is not a member of the active workspace (fail-closed to the org ceiling, never widening). | `tests/security/test_workspace_grants.py::test_no_active_workspace_keeps_full_org_grants`, `::test_non_member_active_workspace_applies_no_narrowing` |
| **SEC-111** | `get_workspace_member` is tenant-scoped and fail-closed (D11, SEC-08) - the single-membership lookup only ever returns a row inside the bound tenant, so a membership under another `tenant_id` resolves to None and can never confer a workspace role across a tenant boundary. | `tests/store/test_tenancy.py::test_get_workspace_member_is_tenant_scoped` |

### Per-org / workspace / user AI keys ([2026] VJS-COUNTY 8, D5)

An org / workspace / user may configure its OWN AI key. Config rows live in ONE
unified `ai_configs` table keyed by `(tenant_id, level, scope_id)` (level =
org / workspace / user). Each row carries a provider/model selection and a
`credential_ref` - the id of a SEALED credential in `credential_refs` - NEVER the raw
key (no plaintext key column). `resolve_ai_key(store, tenant_id, workspace_id,
user_id)` chooses the key with precedence **user -> workspace -> org -> manifest/env
default**, gated by the org's `allow_own_ai_keys`: when the org forbids member-owned
keys a workspace/user row is IGNORED and only the org (or env) key is used. The
spawner wires the resolved, sealed key into the model-key seam (`build_runtime` ->
the network runtime's `_api_key()`); a tenant with no config falls straight through
to the env-configured provider key, so every existing single-tenant deploy is
unchanged (THE CRITICAL RULE). The governed `PUT /v1/ai-keys` accepts the key once,
seals it through `set_credential_ref`, and is role-scoped (org = admin; workspace =
workspace owner/admin + allow_own; user = self + allow_own).

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-AIKEY-01** | An AI key config lives in ONE unified `ai_configs` table keyed by `(tenant_id, level, scope_id)` holding a provider/model selection and a SEALED `credential_ref`, never a raw key (D5) - the `AiConfig` row has no plaintext key field, `set_ai_config` upserts (never duplicates) and rejects an out-of-set level (`SchemaValidationError`), and every allowed level round-trips. | `tests/store/test_ai_config.py::test_ai_config_row_holds_a_credential_ref_never_a_raw_key`, `::test_ai_config_level_must_be_valid` |
| **FR-AIKEY-02** | `resolve_ai_key` honours precedence user -> workspace -> org -> manifest/env default and the spawner wires the resolved SEALED key into the model-key seam (D5) - the resolver returns the highest-precedence configured level (material loaded from the sealed store) and, when nothing is configured, the default level with no ref so the runtime falls back to the env provider key exactly as before (backward-compat). | `tests/security/test_ai_keys.py::test_resolve_precedence_user_workspace_org_default`, `::test_no_config_tenant_falls_back_to_env_key`, `::test_spawner_wires_resolved_sealed_key_into_the_runtime` |
| **FR-AIKEY-03** | A resolved (non-default) `ai_config` drives model/provider ROUTING (D5) - its `provider` selects the RUNTIME (via `runtime_for_provider`) and its `model` / optional `base_url` override the endpoint the runtime pins to, so a config routes the call and not merely the key; a tenant with NO config dispatches the capability's env-default runtime + endpoint model byte-for-byte as before (backward-compat), a config omitting `base_url` keeps the endpoint's own host, and an UNKNOWN provider degrades to the env default runtime (`runtime_for_provider -> None`) without crashing the run while the sealed key still resolves. Sensitive data is EXEMPT (the local endpoint wins regardless - SEC-12). | `tests/security/test_model_routing.py::test_no_config_dispatches_the_env_default_runtime_and_model`, `::test_ai_config_provider_and_model_select_runtime_and_endpoint`, `::test_config_without_base_url_keeps_the_endpoint_host`, `::test_unknown_provider_degrades_to_the_env_default_without_crashing` |
| **SEC-112** | `allow_own_ai_keys=False` makes a workspace/user AI key IGNORED at resolution (D5) - when the org forbids member-owned keys, `resolve_ai_key` skips any workspace/user row and uses only the org key (or the env default when the org has none), so a member cannot bring their own key unless the org opts in. | `tests/security/test_ai_keys.py::test_allow_own_false_ignores_workspace_and_user_keys` |
| **SEC-113** | An AI key is stored ONLY as a sealed credential ref and never returned or audited in plaintext (D5, SEC-05/K-20) - `PUT /v1/ai-keys` accepts the key once, stores it through `set_credential_ref` (the `ai_configs` row holds only the `credential_ref`), never echoes it, and writes a keys-only audit row, so the raw key appears in no audit detail; it remains retrievable only kernel-side from the sealed store. | `tests/security/test_ai_keys.py::test_ai_key_is_sealed_never_returned_or_audited` |
| **SEC-114** | `ai_config` reads are tenant-scoped and never cross tenants (D5, SEC-08) - get/list of an AI-config are keyed on `tenant_id`, so a caller can never read another org/workspace's AI key (a lookup/list under a different tenant is None/empty) and a cross-tenant delete is a no-op. | `tests/store/test_ai_config.py::test_ai_config_reads_are_tenant_scoped` |
| **SEC-115** | The governed set-key route is role-scoped (D5, SEC-36) - `PUT /v1/ai-keys` refuses an org-level key from a non-admin, a workspace-level key from a non-owner/admin of that workspace, and a user-level key for anyone but the caller; workspace/user levels additionally require the org `allow_own_ai_keys` gate, while the org may always set its own key. | `tests/security/test_ai_keys.py::test_set_key_route_is_role_scoped` |

### Opbox-depth audit ([2026] VJS-COUNTY 9)

The tamper-evident, hash-chained audit (SEC-16 / K-19) is deepened to an
Opbox-grade forensic surface WITHOUT touching the existing chain. Five nullable
fields (`ip_address`, `user_agent`, `resource`, `resource_id`, `workspace_id`) are
added to the audit row; they fold into the row hash ONLY when non-None, so a
pre-existing row canonicalises byte-for-byte as before and its stored hash still
verifies (strictly additive, D1). ip/ua ride from the request door, `workspace_id`
from the `InvocationContext`, and `resource`/`resource_id` name the acted-on object
best-effort. An MCP-initiated action carries the caller's identity + org/workspace +
ip/ua at the SAME depth as a human action (D2). A DISTINCT `SecurityEvent` stream -
its own hash chain, its own `security_log` table - captures security SIGNALS (login
failure, rate-limit trip, permission denial, MCP auth failure), keys-only and
separate from the business trail (D3). A periodic per-org/workspace ROLLUP ANCHOR
(`audit_rollup_anchors`) records a deterministic root over a chain segment; the
LOCAL dev-fallback ships now (`is_dev_fallback=True`) with the RFC3161 TSA token +
KMS signature left as a NULL seam behind a documented env credential - wiring a live
TSA/KMS is a Principal dependency (D4). The audit browser (`/v1/audit/search`) filters
by user / resource / date-range and pivots to the security stream, and a new
`/v1/audit/verify` endpoint recomputes the chain + latest anchor and reports
intact/broken; both reads are org/workspace-scoped fail-closed (D5). Secrets never
enter a row (K-20), reads are tenant + workspace fenced, and rows are append-only (D6).

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **SEC-120** | An MCP-initiated audit row carries the caller's identity + org/workspace + ip/ua at the SAME field-depth as a human action (D2) - a human invoke and an MCP `tools/call` through the same chokepoint both populate actor / workspace_id / ip_address / user_agent / resource (identity + workspace from the run token, ip/ua from the request), so a headless MCP action is as attributable as a site action. | `tests/kernel/test_audit_opbox_depth.py::test_mcp_action_is_audited_at_the_same_depth_as_a_human_action` |
| **SEC-121** | The `SecurityEvent` stream is its OWN tamper-evident (hash-chained), append-only, keys-only stream, SEPARATE from the audit log (D3) - signals chain seq/prev_hash/hash and verify detects a tamper, a secret in `detail` is scrubbed (K-20), a business action never lands in it, and it is wired at permission denial (chokepoint), MCP auth failure, and login failure + login throttle (auth_routes). | `tests/security/test_security_event_stream.py::test_security_stream_is_hash_chained_and_keys_only`, `::test_security_stream_is_separate_from_the_audit_log`, `::test_permission_denial_at_chokepoint_records_a_security_signal`, `::test_bad_mcp_run_token_records_an_mcp_auth_failure`, `::test_login_failure_and_throttle_record_security_signals` |
| **SEC-122** | A rollup anchor's root hash equals a recompute over the anchored segment and the LOCAL dev-fallback is flagged with the RFC3161/KMS fields left as a NULL seam (D4) - `rollup_root_hash == segment_root_hash([seq_start, seq_end])`, `is_dev_fallback=True`, `rfc3161_token`/`kms_signature` None; `verify_latest` confirms the intact anchor and detects a REWRITE of a row in the anchored segment, and a later anchor advances only over the un-anchored tail. | `tests/kernel/test_audit_opbox_depth.py::test_rollup_anchor_root_matches_recompute_and_flags_dev_fallback`, `::test_anchor_advances_only_over_the_unanchored_tail` |
| **SEC-123** | The audit browser reads are org/workspace-scoped fail-closed and the verify endpoint detects a broken chain (D5) - a caller with an active workspace sees only org-wide (NULL) + its OWN workspace's rows, search filters by user/resource and can pivot to the security stream (filtered by type), `/v1/audit/verify` reports the chain + latest anchor intact then flags a broken chain with the first bad seq, and both are author/admin gated (a non-author is 403). | `tests/security/test_audit_browser.py::test_audit_search_is_workspace_scoped_fail_closed`, `::test_audit_search_filters_by_user_and_resource`, `::test_audit_search_can_pivot_to_the_security_stream`, `::test_verify_endpoint_reports_intact_then_detects_a_broken_chain`, `::test_verify_and_search_are_gated_and_fail_closed_for_non_authors` |
| **SEC-124** | The new audit fields are additive - a row written without them canonicalises byte-for-byte as before so the existing hash chain is unchanged (D1) - a row with all enrichment fields None serialises WITHOUT the new keys (its stored hash still verifies), a chain of un-enriched rows verifies and an enriched row appended after them stays contiguous + verifiable, tampering a NEW field on an enriched row is detected, and the fields round-trip identically on the in-memory and Postgres stores. | `tests/kernel/test_audit_opbox_depth.py::test_new_fields_are_additive_old_rows_unchanged`, `tests/store/test_store_parity.py::test_audit_enrichment_and_security_stream_roundtrip_on_both_stores` |

### Boltrig v2 stack-owned tool state

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-HOST-09** | Herdr host-control uses stack-owned home/config state in compose, with writable service-owned image roots, and production doctor rejects developer-user Herdr state paths. | `tests/adapters/test_herdr_adapter.py::test_herdr_uses_stack_owned_home_when_configured`, `tests/unit/test_doctor.py::test_production_doctor_rejects_personal_herdr_opencode_state`, `tests/deploy/test_compose_hardening.py::test_herdr_opencode_state_is_stack_owned_in_compose`, `tests/deploy/test_compose_hardening.py::test_herdr_opencode_state_roots_are_owned_by_service_user_in_images` |
| **FR-RUN-17** | OpenCodeRuntime uses stack-owned home/config/state in compose, with writable service-owned image roots, and production doctor rejects developer-user OpenCode state paths. | `tests/security/test_opencode_runtime.py::test_opencode_uses_stack_owned_home_when_configured`, `tests/unit/test_doctor.py::test_production_doctor_rejects_personal_herdr_opencode_state`, `tests/deploy/test_compose_hardening.py::test_herdr_opencode_state_is_stack_owned_in_compose`, `tests/deploy/test_compose_hardening.py::test_herdr_opencode_state_roots_are_owned_by_service_user_in_images` |
| **FR-HOST-10** | The kernel image ships a pinned Herdr CLI binary inside the stack image, and production doctor rejects missing or developer-user Herdr binary paths. | `tests/deploy/test_compose_hardening.py::test_herdr_opencode_clis_ship_inside_first_party_images`, `tests/unit/test_doctor.py::test_production_doctor_rejects_missing_or_personal_herdr_opencode_bins` |
| **FR-HOST-11** | Browser CLI automation ships a pinned hash-locked Browser Use CLI tool venv, uses stack-owned Browser Use CLI state in compose/image env, and production doctor rejects developer-user Browser CLI state or missing/personal `browser-use` binary paths. | `tests/adapters/test_browser_cli_adapter.py::test_browser_cli_uses_stack_owned_home_when_configured`, `tests/unit/test_doctor.py::test_production_doctor_rejects_personal_or_missing_browser_cli`, `tests/deploy/test_compose_hardening.py::test_herdr_opencode_state_is_stack_owned_in_compose`, `tests/deploy/test_compose_hardening.py::test_browser_cli_state_roots_are_stack_owned` |
| **FR-HOST-12** | Platform status reports Herdr, OpenCode, and Browser CLI as shipped stack tools with stack-owned state posture, and never exposes user profile paths, binary paths, browser auth/session state, tokens, or credentials. | `tests/security/test_platform_status.py::test_stack_tool_status_reports_shipped_tools_without_user_paths`, `tests/security/test_platform_status.py::test_stack_tool_status_degrades_personal_state_without_leaking_it` |
| **FR-HOST-13** | Browser CLI child processes receive a minimal stack-owned environment; provider/user secrets and personal Browser Use profile variables are not inherited, and Browser Use cloud profile values flow only from explicit `BOLTRIG_BROWSER_CLOUD_*` stack handoff variables. | `tests/adapters/test_browser_cli_adapter.py::test_browser_cli_child_env_does_not_inherit_user_or_provider_secrets`, `tests/adapters/test_browser_cli_adapter.py::test_browser_cli_cloud_profile_uses_only_stack_prefixed_handoff`, `tests/integration/test_round_two_manifest.py::test_manifest_exports_browser_cloud_policy_without_secret_material`, `tests/integration/test_round_two_manifest.py::test_manifest_export_does_not_override_browser_cloud_policy`, `tests/deploy/test_compose_hardening.py::test_browser_cli_cloud_policy_is_stack_prefixed_in_deploy_config` |
| **FR-HOST-14** | Herdr and OpenCode child processes receive a minimal stack-owned environment; provider/user secrets, personal sockets, and deployment posture variables are not inherited unless a scoped runtime handoff explicitly adds them. | `tests/adapters/test_herdr_adapter.py::test_herdr_child_env_does_not_inherit_user_or_provider_secrets`, `tests/security/test_opencode_runtime.py::test_opencode_child_env_does_not_inherit_user_or_provider_secrets` |
| **FR-RUN-18** | The fleet image ships a pinned OpenCode CLI binary inside the stack image, and production doctor rejects missing or developer-user OpenCode binary paths. | `tests/deploy/test_compose_hardening.py::test_herdr_opencode_clis_ship_inside_first_party_images`, `tests/unit/test_doctor.py::test_production_doctor_rejects_missing_or_personal_herdr_opencode_bins` |

### Migration authority

| Invariant | Meaning | Bound test(s) |
| --- | --- | --- |
| **FR-OPS-01** | Alembic is the authoritative ordered schema chain: revision 0001 reads an immutable snapshot, and replaying through head produces the same tables, columns, constraints, indexes, and sequences as the `schema.sql` first-boot bootstrap. | `tests/integration/test_migration_parity.py::test_alembic_baseline_is_immutable`, `::test_alembic_head_matches_bootstrap_schema` |
| **FR-OPS-02** | Compose validation works from a clean checkout with the checked non-secret environment fixture and a validation-only database password, while normal operator launches retain the ignored `.env` default. | `tests/deploy/test_compose_hardening.py::test_compose_validation_is_clean_checkout_safe` |
| **FR-OPS-03** | `/readyz` is a bounded, redacted, fail-closed deep readiness gate: production requires Postgres, Redis, the exact Alembic head, a kernel-local Herdr execution probe, and a fresh HMAC-authenticated, deployment-scoped fleet receipt proving OpenCode, Browser Use, and Chromium CDP health without assuming shared containers; concurrent calls are coalesced/cached to bound the unauthenticated surface; enabled Hatchet/model-gateway seams are live-probed; a failed requirement returns 503 without exposing deployment secrets or command output. | `tests/unit/test_readiness.py`, `tests/unit/test_stack_tool_health.py`, `tests/integration/test_migration_parity.py::test_packaged_readiness_head_matches_alembic_head` |
| **SEC-137** | Protected semantic tags create a draft release, build and scan all five images, sign and attest run-scoped candidate digests, refuse mutable public tags or overwritten evidence, and publish only after every exact digest is reverified and promoted. | `tests/deploy/test_compose_hardening.py::test_release_publishes_only_scanned_signed_digest_images_with_sboms` |

## How a new invariant is added

1. Write the test and mark it: `@pytest.mark.invariant("NEW-ID")`.
2. Declare it in `tests/invariants.yaml` with a one-line description and the
   test node id(s).
3. Document it in the table above.
4. Run `make invariants` (gate must stay at debt 0) and `make test`.
