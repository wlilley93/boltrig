import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient, type BirthProfileResponse } from "../src/index.js";

test("birth profiles use the canonical redacted startup-evidence route", async () => {
  let requested = "";
  const canonical: BirthProfileResponse = {
    tenant_id: "tenant-a",
    status: "observed_mismatch",
    reference: {
      status: "startup_snapshot_liveness_unknown",
      source_process: "api",
      reason: null,
      basis: "latest_api_startup_receipt",
      instance_identity: "bi_eeeeeeeeeeeeeeeeeeeeeeee",
      manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
      addon_set_identity: "as_bbbbbbbbbbbbbbbbbbbbbbbb",
      codex_provider_identity: "cp_cccccccccccccccccccccccc",
      codex_provider_state: "configured",
      sensitive_role_identity: "sr_dddddddddddddddddddddddd",
      sensitive_role_state: "configured",
      observed_at: "2026-07-30T12:00:00+00:00",
      expires_at: "2026-07-30T12:05:00+00:00",
      liveness_claimed: false,
    },
    observations: [
      {
        process_kind: "api",
        instance_identity: "bi_eeeeeeeeeeeeeeeeeeeeeeee",
        evidence_state: "matched_reference_liveness_unknown",
        reason: null,
        matches_reference: true,
        mismatches: [],
        manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
        addon_set_identity: "as_bbbbbbbbbbbbbbbbbbbbbbbb",
        codex_provider_identity: "cp_cccccccccccccccccccccccc",
        codex_provider_state: "configured",
        sensitive_role_identity: "sr_dddddddddddddddddddddddd",
        sensitive_role_state: "configured",
        receipt_kind: "startup_snapshot",
        observed_at: "2026-07-30T12:00:00+00:00",
        expires_at: "2026-07-30T12:05:00+00:00",
        liveness_claimed: false,
      },
      {
        process_kind: "fleet",
        instance_identity: "bi_ffffffffffffffffffffffff",
        evidence_state: "mismatched_startup_liveness_unknown",
        reason: null,
        matches_reference: false,
        mismatches: ["addon_set_identity"],
        manifest_generation: "mf_aaaaaaaaaaaaaaaaaaaaaaaa",
        addon_set_identity: "as_111111111111111111111111",
        codex_provider_identity: "cp_cccccccccccccccccccccccc",
        codex_provider_state: "configured",
        sensitive_role_identity: "sr_dddddddddddddddddddddddd",
        sensitive_role_state: "configured",
        receipt_kind: "startup_snapshot",
        observed_at: "2026-07-30T12:00:00+00:00",
        expires_at: "2026-07-30T12:05:00+00:00",
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
  };
  const client = new BoltrigClient({
    fetch: async (input) => {
      requested = String(input);
      return new Response(JSON.stringify(canonical), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.birthProfile(), canonical);
  assert.equal(requested, "/v1/birth-profile");
  assert.equal(canonical.summary.liveness_claimed, false);
});
