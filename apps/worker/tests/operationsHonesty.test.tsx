// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  auditExport: vi.fn(),
  auditSearch: vi.fn(),
  auditVerify: vi.fn(),
  backupStatus: vi.fn(),
  budgets: vi.fn(),
  invokeApprovalState: vi.fn(),
  birthProfile: vi.fn(),
  modelTelemetry: vi.fn(),
  platformStatus: vi.fn(),
  readiness: vi.fn(),
  resetBudget: vi.fn(),
  upsertBudget: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { OperateView } from "../src/components/OperationsView";

beforeEach(() => {
  api.backupStatus.mockResolvedValue({
    backup: {
      state: "unavailable",
      evidence_kind: "shared_success_marker",
      maximum_age_seconds: 93600,
      last_success_at: null,
      age_seconds: null,
      off_box_state: "unknown_not_in_marker",
      encryption_state: "unknown_not_in_marker",
      restore_readiness: "unavailable_no_restore_drill_receipt",
      liveness_claimed: false,
    },
  });
  api.readiness.mockResolvedValue({
    status: "ready",
    checks: { postgres: { status: "ok", required: true } },
  });
  api.platformStatus.mockResolvedValue({
    components: [{ id: "codex", kind: "runtime", status: "ok" }],
    runtimes: [],
  });
  api.modelTelemetry.mockResolvedValue({ models: [] });
  api.birthProfile.mockResolvedValue({
    tenant_id: "acme",
    status: "process_kind_unavailable",
    reference: {
      status: "startup_snapshot_liveness_unknown",
      source_process: "api",
      reason: null,
      basis: "latest_api_startup_receipt",
      instance_identity: "bi_aaaaaaaaaaaaaaaaaaaaaaaa",
      manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
      addon_set_identity: "as_aaaaaaaaaaaaaaaaaaaaaaaa",
      codex_provider_identity: "cp_aaaaaaaaaaaaaaaaaaaaaaaa",
      codex_provider_state: "configured",
      sensitive_role_identity: "sr_aaaaaaaaaaaaaaaaaaaaaaaa",
      sensitive_role_state: "configured",
      observed_at: "2026-07-30T12:00:00Z",
      expires_at: "2026-07-30T12:05:00Z",
      liveness_claimed: false,
    },
    observations: [
      {
        process_kind: "api",
        instance_identity: "bi_aaaaaaaaaaaaaaaaaaaaaaaa",
        evidence_state: "matched_reference_liveness_unknown",
        reason: null,
        matches_reference: true,
        mismatches: [],
        manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
        addon_set_identity: "as_aaaaaaaaaaaaaaaaaaaaaaaa",
        codex_provider_identity: "cp_aaaaaaaaaaaaaaaaaaaaaaaa",
        codex_provider_state: "configured",
        sensitive_role_identity: "sr_aaaaaaaaaaaaaaaaaaaaaaaa",
        sensitive_role_state: "configured",
        receipt_kind: "startup_snapshot",
        observed_at: "2026-07-30T12:00:00Z",
        expires_at: "2026-07-30T12:05:00Z",
        liveness_claimed: false,
      },
      {
        process_kind: "fleet",
        instance_identity: "bi_bbbbbbbbbbbbbbbbbbbbbbbb",
        evidence_state: "mismatched_startup_liveness_unknown",
        reason: null,
        matches_reference: false,
        mismatches: ["codex_provider_identity"],
        manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
        addon_set_identity: "as_aaaaaaaaaaaaaaaaaaaaaaaa",
        codex_provider_identity: "cp_bbbbbbbbbbbbbbbbbbbbbbbb",
        codex_provider_state: "configured",
        sensitive_role_identity: "sr_aaaaaaaaaaaaaaaaaaaaaaaa",
        sensitive_role_state: "configured",
        receipt_kind: "startup_snapshot",
        observed_at: "2026-07-30T12:00:00Z",
        expires_at: "2026-07-30T12:05:00Z",
        liveness_claimed: false,
      },
      {
        process_kind: "hatchet",
        instance_identity: null,
        evidence_state: "unavailable",
        reason: "no_startup_receipt",
        matches_reference: null,
        mismatches: [],
        manifest_generation: null,
        addon_set_identity: null,
        codex_provider_identity: null,
        codex_provider_state: "unavailable",
        sensitive_role_identity: null,
        sensitive_role_state: "unavailable",
        receipt_kind: null,
        observed_at: null,
        expires_at: null,
        liveness_claimed: false,
      },
    ],
    summary: {
      mismatch_count: 1,
      stale_count: 0,
      unavailable_count: 1,
      retained_instance_count: 2,
      max_retained_instances_per_process: 32,
      max_returned_instances: 96,
      liveness_claimed: false,
      replica_coverage_claimed: false,
    },
  });
  api.budgets.mockResolvedValue({ budgets: [] });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("keeps independent posture evidence when model telemetry is unavailable", async () => {
  api.modelTelemetry.mockRejectedValue(new Error("telemetry unavailable"));

  render(<OperateView />);

  expect(await screen.findByText("Ready for traffic")).toBeTruthy();
  expect(await screen.findByText("Postgres")).toBeTruthy();
  expect(await screen.findByText("codex")).toBeTruthy();
  expect(screen.getByText(/Model receipts could not be refreshed/)).toBeTruthy();
  expect(screen.getByText(/no absence is inferred/)).toBeTruthy();
});

it("shows notifier acceptance without claiming provider or inbox delivery", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    password_reset_delivery: {
      configuration: "configured",
      configuration_reason: null,
      evidence_status: "available",
      last_attempt_at: "2026-07-30T12:00:00Z",
      last_outcome: "accepted_by_notifier",
      evidence_kind: "bounded_audit_attempt_not_provider_receipt",
      proves_recipient_delivery: false,
      target_disclosed: false,
      audit_tail_limit: 500,
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Password-reset notifier")).toBeTruthy();
  expect(screen.getByText(/Notifier accepted the delivery attempt/)).toBeTruthy();
  expect(screen.getByText(/not a provider receipt or proof/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("owner@example.io");
  expect(document.body.textContent).not.toContain("provider-message-id");
});

it("shows per-process maintenance attempts without claiming liveness", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    background_job_evidence: {
      status: "available",
      evidence_kind: "bounded_attempt_receipt_not_liveness",
      proves_liveness: false,
      process_coverage: "bounded_receipts_not_replica_inventory",
      max_retained_process_receipts_per_job: 4,
      max_returned_receipts: 8,
    },
    background_jobs: [
      {
        job_name: "hitl_expiry",
        process_instance_identity: "bjp_aaaaaaaaaaaaaaaaaaaaaaaa",
        state: "recent_succeeded_evidence",
        last_outcome: "succeeded",
        last_attempt_at: "2026-07-30T12:00:00Z",
        last_success_at: "2026-07-30T12:00:00Z",
        last_failure_at: null,
        failure_code: null,
        last_item_count: 2,
        interval_seconds: 60,
        lag_seconds: 15,
        stale_after_seconds: 150,
        evidence_kind: "bounded_attempt_receipt_not_liveness",
        proves_liveness: false,
        process_coverage: "bounded_receipts_not_replica_inventory",
      },
      {
        job_name: "retention",
        process_instance_identity: "bjp_bbbbbbbbbbbbbbbbbbbbbbbb",
        state: "recent_failed_evidence",
        last_outcome: "failed",
        last_attempt_at: "2026-07-30T12:00:00Z",
        last_success_at: null,
        last_failure_at: "2026-07-30T12:00:00Z",
        failure_code: "sweep_failed",
        last_item_count: 0,
        interval_seconds: 3600,
        lag_seconds: 15,
        stale_after_seconds: 7230,
        evidence_kind: "bounded_attempt_receipt_not_liveness",
        proves_liveness: false,
        process_coverage: "bounded_receipts_not_replica_inventory",
      },
    ],
  });

  render(<OperateView />);

  expect(await screen.findByText("Last observed attempts")).toBeTruthy();
  expect(screen.getByText(/HITL expiry · process bjp_aaaaaaaa/)).toBeTruthy();
  expect(screen.getByText(/Conversation retention · process bjp_bbbbbbbb/)).toBeTruthy();
  expect(screen.getByText("2 affected")).toBeTruthy();
  expect(screen.getByText("Attempt failed")).toBeTruthy();
  expect(screen.getByText(/not heartbeats/)).toBeTruthy();
  expect(screen.getByText(/do not prove current liveness or complete replica coverage/)).toBeTruthy();
});

it("shows bounded memory projection delivery without inventing replay", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    memory_projection_delivery: {
      status: "available",
      evidence_kind: "bounded_status_receipts_not_queue_or_worker_liveness",
      proves_queue_depth: false,
      proves_worker_liveness: false,
      queue_posture: {
        status: "configured",
        execution_mode: "durable_executor",
        configured_projection_count: 2,
        max_operation_attempts: 3,
        retry_scope: "single_task_invocation",
        enqueue_retry: "disabled_ambiguous_acceptance",
        payload_retention: "executor_owned_not_in_status_receipt",
        manual_retry: "unavailable_original_payload_not_retained",
        proves_worker_liveness: false,
      },
      receipts: [
        {
          receipt_identity: "mpr_aaaaaaaaaaaaaaaaaaaa",
          projection_identity: "mp_bbbbbbbbbbbbbbbbbbbb",
          operation: "remember",
          state: "terminal_after_retry_cap",
          status: "failed",
          enqueue_attempts: 1,
          operation_attempts: 3,
          max_operation_attempts: 3,
          queued_at: "2026-07-30T12:00:00Z",
          first_attempt_at: "2026-07-30T12:00:02Z",
          last_attempt_at: "2026-07-30T12:00:05Z",
          last_failure_at: "2026-07-30T12:00:05Z",
          last_failure_code: "projection_operation_failed",
          queue_wait_seconds: 2,
          pending_age_seconds: null,
          terminal_at: "2026-07-30T12:00:05Z",
          content_retained_in_receipt: false,
          manual_retry: "unavailable_original_payload_not_retained",
        },
        {
          receipt_identity: "mpr_cccccccccccccccccccc",
          projection_identity: "mp_dddddddddddddddddddd",
          operation: "forget",
          state: "delivered_after_retry",
          status: "deleted",
          enqueue_attempts: 1,
          operation_attempts: 2,
          max_operation_attempts: 3,
          queued_at: "2026-07-30T12:00:00Z",
          first_attempt_at: "2026-07-30T12:00:01Z",
          last_attempt_at: "2026-07-30T12:00:04Z",
          last_failure_at: "2026-07-30T12:00:03Z",
          last_failure_code: "projection_operation_failed",
          queue_wait_seconds: 1,
          pending_age_seconds: null,
          terminal_at: "2026-07-30T12:00:04Z",
          content_retained_in_receipt: false,
          manual_retry: "not_applicable",
        },
      ],
      max_returned_receipts: 50,
      truncated: false,
      manual_retry: "unavailable_original_payload_not_retained",
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Projection delivery")).toBeTruthy();
  expect(screen.getByText(/not queue depth or worker-liveness evidence/)).toBeTruthy();
  expect(screen.getByText(/Pending age is receipt age, not engine queue lag/)).toBeTruthy();
  expect(screen.getByText(/Remember · projection mp_bbbbbbbbb/)).toBeTruthy();
  expect(screen.getByText("3/3 attempts")).toBeTruthy();
  expect(screen.getByText("2/3 attempts")).toBeTruthy();
  expect(screen.getByText(/Manual retry is unavailable/)).toBeTruthy();
  expect(screen.getByText(/does not retain the original projection payload/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("fact-private-id");
  expect(document.body.textContent).not.toContain("projection-super-secret");
  expect(document.body.textContent).not.toContain("private-ref");
});

it("shows redacted effective web-fetch policy and separate egress boundaries", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    network_policy: {
      status: "available",
      policy_source: "live_adapter_process_start_snapshot",
      changes_require_restart: true,
      universal_egress_control: false,
      sensitive_values_redacted: true,
      web_fetch: {
        surface: "web.fetch",
        status: "enforced",
        policy_snapshot: "adapter_process_start",
        fields: {
          air_gapped: { enforcement: "enforced", enabled: false },
          https_proxy: { enforcement: "enforced", configured: true },
          ca_bundle: { enforcement: "enforced", configured: true },
          allowed_domains: {
            enforcement: "enforced",
            configured: true,
            entry_count: 2,
          },
          blocked_domains: {
            enforcement: "enforced",
            configured: false,
            entry_count: 0,
          },
        },
        controls: {
          ssrf_preflight: "enforced",
          redirects: "disabled",
          dns_pinning: "proxy_resolution_delegated",
        },
      },
      coverage: [
        {
          surface: "browser",
          status: "separate_policy",
          manifest_network_policy: "not_applied",
          controls: [
            "browser_specific_domain_allowlist",
            "shared_ssrf_preflight",
          ],
          limitation: "browser_process_performs_the_network_request",
        },
        {
          surface: "external_mcp",
          status: "separate_policy",
          manifest_network_policy: "not_applied",
          controls: ["shared_ssrf_and_dns_pinning"],
          limitation: "manifest_proxy_ca_and_domain_rules_not_applied",
        },
      ],
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Effective egress coverage")).toBeTruthy();
  expect(screen.getByText("web.fetch · CA bundle")).toBeTruthy();
  expect(screen.getByText("web.fetch · HTTPS proxy")).toBeTruthy();
  expect(screen.getByText("External MCP")).toBeTruthy();
  expect(screen.getByText(/not a universal egress firewall/)).toBeTruthy();
  expect(screen.getByText(/Proxy addresses, CA paths and contents/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("proxy.private.example");
  expect(document.body.textContent).not.toContain("/private/org/root-ca.pem");
});

it("shows the effective Codex OFF wall without implying cell readiness", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    codex_admission: {
      status: "available",
      evidence_kind: "process_composition_not_runtime_liveness",
      rollout: {
        policy_source: "immutable_off_scaffold",
        mode: "off",
        generation: 1,
        shadow_root_decisions: "active_execution_neutral",
        root_execution: "legacy_only",
        assignment_admission: "inactive_never_called",
        canary_decision: "unavailable_rollout_off",
      },
      runtime: {
        trusted_provider: "configured_development_only",
        runtime_config_production_ready: false,
        runtime_class_production_ready: false,
        production_activation: "refused_unresolved_isolation_controls",
        preflight_evidence: "unavailable_no_durable_cell_receipts",
        cell_liveness: "unavailable",
      },
      execution_changed_by_projection: false,
      sensitive_values_redacted: true,
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Rollout and admission wall")).toBeTruthy();
  expect(screen.getByText("Rollout mode · OFF")).toBeTruthy();
  expect(screen.getByText("Native production activation refused")).toBeTruthy();
  expect(screen.getByText("Cell evidence unavailable")).toBeTruthy();
  expect(screen.getByText(/process-composition evidence, not cell liveness/)).toBeTruthy();
  expect(screen.getByText(/No durable per-cell preflight receipts/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("NEVER-SERIALIZE");
});

it("shows process-local Langfuse attempts without claiming sink health", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    langfuse_delivery: {
      status: "available",
      evidence_kind: "process_local_attempt_counters_not_sink_health",
      process_coverage: "api_spawner_only_not_replica_inventory",
      sink_state: "enabled",
      reason: "configured",
      attempt_count: 5,
      success_count: 4,
      failure_count: 1,
      last_attempt_at: "2026-07-30T12:00:00Z",
      last_success_at: "2026-07-30T11:59:00Z",
      last_failure_at: "2026-07-30T11:58:00Z",
      delivery_lag: "unavailable",
      liveness_claimed: false,
      sensitive_values_redacted: true,
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Langfuse delivery attempts")).toBeTruthy();
  expect(screen.getByText("Sink Enabled")).toBeTruthy();
  expect(screen.getByText("5 attempts")).toBeTruthy();
  expect(screen.getByText("4 sent · 1 failed")).toBeTruthy();
  expect(screen.getByText(/do not prove sink health, delivery lag/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("LANGFUSE_SECRET_KEY");
});

it("shows effective authentication trust without disclosing OIDC values", async () => {
  api.platformStatus.mockResolvedValue({
    components: [],
    runtimes: [],
    identity_policy: {
      status: "available",
      mode: "oidc",
      oidc: {
        manifest_trio_configured: true,
        process_trio_configured: true,
        manifest_trio_state: "complete",
        process_trio_state: "complete",
        serving_state: "active_manifest_and_process_match",
        drift_policy: "exact_match_or_boot_refused",
      },
      generation: "a".repeat(64),
      changes_apply_at: "process_restart",
      sensitive_values_redacted: true,
    },
  });

  render(<OperateView />);

  expect(await screen.findByText("Effective trust mode")).toBeTruthy();
  expect(screen.getByText("Oidc")).toBeTruthy();
  expect(screen.getByText("Manifest OIDC trust")).toBeTruthy();
  expect(screen.getByText(/drift from simultaneously configured process trust refuses boot/)).toBeTruthy();
  expect(document.body.textContent).not.toContain("id.private.example");
  expect(document.body.textContent).not.toContain("private-audience");
});

it("shows per-instance birth-profile mismatch and absence without claiming parity", async () => {
  render(<OperateView />);

  expect(await screen.findByText("Birth-profile comparison")).toBeTruthy();
  expect(screen.getByText("Fleet worker")).toBeTruthy();
  expect(screen.getByText(/differs from API reference · liveness unknown/)).toBeTruthy();
  expect(screen.getByText("Codex Provider Identity")).toBeTruthy();
  expect(screen.getByText("Hatchet worker")).toBeTruthy();
  expect(screen.getByText("Startup receipt unavailable")).toBeTruthy();
  expect(screen.getByText(/reference, not desired state/)).toBeTruthy();
  expect(screen.getByText(/do not prove replica coverage or process liveness/)).toBeTruthy();
});

it("retains the last birth-profile evidence after an independent refresh failure", async () => {
  api.birthProfile
    .mockResolvedValueOnce(await api.birthProfile())
    .mockRejectedValueOnce(new Error("temporary"));

  render(<OperateView />);
  expect(await screen.findByText("Birth-profile comparison")).toBeTruthy();

  fireEvent.click(screen.getAllByRole("button", { name: "Refresh" })[0]);

  expect(await screen.findByText(
    /Process startup receipts could not be refreshed; showing the last result/,
  )).toBeTruthy();
  expect(screen.getByText("Fleet worker")).toBeTruthy();
});

it("retains the last authorized readiness result after a refresh failure", async () => {
  api.readiness
    .mockResolvedValueOnce({
      status: "ready",
      checks: { postgres: { status: "ok", required: true } },
    })
    .mockRejectedValueOnce(new Error("temporary"));

  render(<OperateView />);
  expect(await screen.findByText("Ready for traffic")).toBeTruthy();

  fireEvent.click(screen.getAllByRole("button", { name: "Refresh" })[0]);

  await waitFor(() => {
    expect(screen.getByText(/showing the last result/)).toBeTruthy();
  });
  expect(screen.getByText("Ready for traffic")).toBeTruthy();
  expect(screen.getByText("Postgres")).toBeTruthy();
});

it("states the actual budget boundary and does not author inert workflow scopes", async () => {
  render(<OperateView />);

  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));

  expect(await screen.findByText(/Hard stops currently cover model-backed work/)).toBeTruthy();
  expect(screen.getByText(/Realtime voice provider usage/)).toBeTruthy();
  expect(screen.getByText(/workflow-scoped spend are not charged here/)).toBeTruthy();
  expect(screen.getByLabelText("Scope type")).toBeTruthy();
  expect(screen.queryByRole("option", { name: "Workflow" })).toBeNull();
  expect(screen.getByText("Automatic window")).toBeTruthy();
  expect(screen.getByText(/daily and monthly windows roll automatically/)).toBeTruthy();
  expect(screen.getByText(/Stop spawned agent work when exhausted/)).toBeTruthy();
});

it("renders exact automatic budget-window evidence without inventing run aggregates", async () => {
  api.budgets.mockResolvedValue({
    budgets: [
      {
        id: "acme",
        scope_type: "tenant",
        window: "daily",
        hard_stop: true,
        token_limit: 1000,
        spent_tokens: 250,
        cost_limit_micros: 5_000_000,
        spent_micros: 1_000_000,
        usage_state: "current",
        window_key: "day:2026-07-30",
        window_started_at: "2026-07-30T00:00:00+00:00",
        window_ends_at: "2026-07-31T00:00:00+00:00",
      },
      {
        id: "research",
        scope_type: "department",
        window: "run",
        hard_stop: true,
        token_limit: 500,
        spent_tokens: 0,
        cost_limit_micros: null,
        spent_micros: 0,
        usage_state: "run_context_required",
        window_key: null,
        window_started_at: null,
        window_ends_at: null,
      },
    ],
  });

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));

  expect(await screen.findByText(/daily UTC window · automatic rollover/)).toBeTruthy();
  expect(screen.getByText("250 / 1,000 tokens")).toBeTruthy();
  expect(screen.getByText(/per run · aggregate usage is not inferred/)).toBeTruthy();
  expect(screen.getByText("— / 500 tokens")).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "Reset current window" })).toHaveLength(1);
});

it("continues an approved budget policy through the exact same SDK method", async () => {
  api.upsertBudget
    .mockResolvedValueOnce({
      status: "pending_human",
      hitl_request_id: "approval-budget",
    })
    .mockResolvedValueOnce({ status: "ok" });

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));
  fireEvent.change(await screen.findByLabelText("Token limit"), {
    target: { value: "1000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save budget" }));
  await screen.findByText("Budget policy change is waiting for approval");

  fireEvent.click(screen.getByRole("button", {
    name: "Check approval and apply exact change",
  }));
  await waitFor(() => expect(api.upsertBudget).toHaveBeenNthCalledWith(
    2,
    "tenant",
    "default",
    {
      window: "monthly",
      hard_stop: true,
      token_limit: 1000,
      cost_limit_micros: undefined,
    },
    "approval-budget",
  ));
  await screen.findByText("Budget policy saved.");
});

it("invalidates a pending budget policy when an exact field changes", async () => {
  api.upsertBudget.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-stale-budget",
  });

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));
  fireEvent.change(await screen.findByLabelText("Token limit"), {
    target: { value: "1000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save budget" }));
  await screen.findByText("Budget policy change is waiting for approval");

  fireEvent.change(screen.getByLabelText("Token limit"), {
    target: { value: "2000" },
  });
  await screen.findByText("Budget policy change changed");
  expect(api.upsertBudget).toHaveBeenCalledTimes(1);
  expect(api.invokeApprovalState).not.toHaveBeenCalled();
});

it.each([
  ["rejected", "Budget policy change was rejected"],
  ["expired", "Budget policy change approval expired"],
  ["consumed", "Budget policy change approval was already consumed"],
])("renders a %s budget decision without applying it", async (status, label) => {
  api.upsertBudget.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: `approval-budget-${status}`,
  });
  api.invokeApprovalState.mockResolvedValue({ status });

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save budget" }));
  fireEvent.click(await screen.findByRole("button", {
    name: "Check approval and apply exact change",
  }));

  await screen.findByText(label);
  expect(api.upsertBudget).toHaveBeenCalledTimes(1);
});

it("renders unavailable caller-owned approval state without inferring a budget write", async () => {
  api.upsertBudget.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval-budget-unavailable",
  });
  api.invokeApprovalState.mockRejectedValue(new Error("approval read unavailable"));

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Budgets" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save budget" }));
  fireEvent.click(await screen.findByRole("button", {
    name: "Check approval and apply exact change",
  }));

  await screen.findByText("Budget policy change approval is unavailable");
  expect(api.upsertBudget).toHaveBeenCalledTimes(1);
});

it("keeps audit-chain integrity distinct from independent anchor evidence", async () => {
  api.auditVerify.mockResolvedValue({
    tenant_id: "acme",
    chain_intact: true,
    security_chain_intact: true,
    anchor_intact: true,
    intact: true,
    anchor: {
      id: "anchor-7",
      seq_start: 11,
      seq_end: 42,
      rollup_root_hash: "hash",
      anchored_at: "2026-07-29T12:00:00Z",
      is_dev_fallback: true,
      rfc3161_token: null,
      kms_signature: null,
    },
  });

  render(<OperateView />);
  fireEvent.click(screen.getByRole("button", { name: "Audit" }));
  fireEvent.click(screen.getByRole("button", { name: "Verify chains" }));

  expect(await screen.findByText(/Intact · local fallback/)).toBeTruthy();
  expect(screen.getByText((_content, element) => element?.textContent === "11–42")).toBeTruthy();
  expect(screen.getByText("Local development fallback")).toBeTruthy();
  expect(screen.getByText(/not independent timestamp or KMS evidence/)).toBeTruthy();
});
