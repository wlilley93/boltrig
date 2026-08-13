import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BoltrigClient,
  WORKER_INTEGRATION_CATALOGUE,
  normalizeEvents,
  type ChatEvent,
} from "../src/index.js";

test("the reviewed Worker catalogue has forty explicit, uncertified entries", () => {
  assert.equal(WORKER_INTEGRATION_CATALOGUE.length, 40);
  assert.equal(new Set(WORKER_INTEGRATION_CATALOGUE.map((item) => item.id)).size, 40);
  assert.ok(WORKER_INTEGRATION_CATALOGUE.every((item) => item.certification === "uncertified"));
  for (const required of ["slack", "github", "figma", "stripe", "pagerduty", "playwright-browser"]) {
    assert.ok(WORKER_INTEGRATION_CATALOGUE.some((item) => item.id === required), required);
  }
});

test("model routing and Familiar genotype survive the shared normalizer", () => {
  const turn = normalizeEvents([
    {
      type: "model_routing",
      run_id: "r1",
      requested_profile_id: "fast",
      selected_profile_id: "sensitive-local",
      routing_class: "local",
      reason: "data classification",
      overridden: true,
    },
    {
      type: "subagent",
      child_run_id: "child",
      task: "Inspect",
      familiar_genotype: { body: "cassini", palette: ["blue"] },
    },
  ] as ChatEvent[]);
  assert.deepEqual(turn.modelRouting, {
    requestedProfileId: "fast",
    selectedProfileId: "sensitive-local",
    routingClass: "local",
    reason: "data classification",
    overridden: true,
  });
  assert.deepEqual(turn.subagents[0]?.familiarGenotype, {
    body: "cassini",
    palette: ["blue"],
  });
});

test("browser transport sends cookie credentials, CSRF, and the opaque chat model choice", async () => {
  let request: RequestInit | undefined;
  const fetcher: typeof fetch = async (_input, init) => {
    request = init;
    return new Response(
      'data: {"type":"message_start","run_id":"r1","conversation_id":"c1"}\n\n' +
      'data: {"type":"heartbeat","run_id":"r1"}\n\n' +
      'data: {"type":"message_end","run_id":"r1"}\n\n',
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  };
  const events: ChatEvent[] = [];
  const client = new BoltrigClient({
    fetch: fetcher,
    csrfToken: () => "csrf-value",
  });
  await client.streamChat(
    { message: "hello", model_choice_id: "approved-choice", origin: "worker" },
    (event) => events.push(event),
  );
  const headers = new Headers(request?.headers);
  assert.equal(request?.credentials, "include");
  assert.equal(headers.get("x-boltrig-csrf"), "csrf-value");
  assert.equal(JSON.parse(String(request?.body)).model_choice_id, "approved-choice");
  assert.deepEqual(events.map((event) => event.type), ["message_start", "message_end"]);
});

test("chat model choices expose exact names through the bounded Worker route", async () => {
  let url = "";
  const response = {
    status: "ok" as const,
    reason: null,
    choices: [{
      id: "approved-choice",
      model_name: "anthropic/claude-sonnet-4-5",
      available: true,
      is_default: true,
      modalities: ["text"],
    }],
    default_choice_id: "approved-choice",
    default_model_name: "anthropic/claude-sonnet-4-5",
    default_available: true,
    default_unavailable_reason: null,
  };
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.chatModelChoices(), response);
  assert.equal(url, "/v1/chat/model-choices");
});

test("Bifrost model discovery uses the server-owned redacted catalogue route", async () => {
  let url = "";
  const response = {
    status: "ok" as const,
    models: [{
      id: "anthropic/claude-sonnet-4-5",
      name: "Claude Sonnet 4.5",
      input_modalities: ["text", "image"],
    }],
    reason: null,
  };
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.bifrostModels(), response);
  assert.equal(url, "/v1/bifrost/models");
});

test("approval posture uses the dedicated self route and exact full-access confirmation", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const response = {
    status: "ok" as const,
    posture: "full_access" as const,
    source: "user_override" as const,
    enforcement: {
      applies_to: "delegated_agent_adapter_calls" as const,
      workspace_blocking_verbs_remain: true as const,
      control_plane_approvals_remain: true as const,
      direct_human_consequence_gate_remains: true as const,
      authority_is_never_widened: true as const,
    },
  };
  const client = new BoltrigClient({
    csrfToken: () => "csrf-value",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.approvalPosture(), response);
  assert.deepEqual(
    await client.putApprovalPosture({ posture: "full_access", confirm: "full_access" }),
    response,
  );
  assert.equal(requests[0]?.url, "/v1/me/approval-posture");
  assert.equal(requests[0]?.init?.method, "GET");
  assert.equal(requests[1]?.url, "/v1/me/approval-posture");
  assert.equal(requests[1]?.init?.method, "PUT");
  assert.equal(new Headers(requests[1]?.init?.headers).get("x-boltrig-csrf"), "csrf-value");
  assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), {
    posture: "full_access",
    confirm: "full_access",
  });
});

test("device file listings use the governed invoke contract without a browser filesystem path", async () => {
  let url = "";
  let body: unknown;
  const client = new BoltrigClient({
    csrfToken: () => "csrf",
    fetch: async (input, init) => {
      url = String(input);
      body = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({
        status: "pending_human",
        hitl_request_id: "approval/list",
      }), {
        status: 202,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const result = await client.requestDeviceFileListLease(
    "device_a",
    "root_a",
    { relative_path: "src", max_entries: 40 },
    { idempotencyKey: "list/src", context: { run_id: "run/a" } },
  );

  assert.equal(url, "/v1/invoke");
  assert.deepEqual(body, {
    noun: "device",
    verb: "device.file.list",
    params: {
      device_id: "device_a",
      root_id: "root_a",
      relative_path: "src",
      max_entries: 40,
    },
    idempotency_key: "list/src",
    context: { run_id: "run/a" },
  });
  assert.deepEqual(result, {
    status: "pending_human",
    hitl_request_id: "approval/list",
  });
});

test("chat attachment preflight reads the server-owned limits contract", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        attachments: {
          max_count: 3,
          max_bytes: 64,
          max_total_bytes: 128,
          model_readable_media_types: ["text/*"],
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.chatConfig(), {
    attachments: {
      max_count: 3,
      max_bytes: 64,
      max_total_bytes: 128,
      model_readable_media_types: ["text/*"],
    },
  });
  assert.equal(url, "/v1/chat/config");
});

test("effective model policy uses the redacted author projection", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        policy: {
          state: "configured",
          source: "process_start_manifest",
          generation: "opaque",
          default: {
            endpoint_id: "default",
            state: "active",
            serving_state: "inactive_no_consumer",
          },
          sensitive: {
            endpoint_id: "private",
            state: "active",
            serving_state: "active_process_policy",
            eligible: true,
          },
          prices: [],
          price_serving_state: "not_configured",
          changes_apply_at: "process_restart",
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const result = await client.modelPolicy();
  assert.equal(url, "/v1/model-policy");
  assert.equal(result.policy.default.serving_state, "inactive_no_consumer");
  assert.equal(result.policy.sensitive.eligible, true);
});

test("spawn policy inventory and preview use their no-side-effect routes", async () => {
  const requests: Array<{ url: string; body?: unknown }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "csrf",
    fetch: async (input, init) => {
      requests.push({
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      return new Response(
        String(input).endsWith("/simulate")
          ? '{"status":"no_match","input_trust":"untrusted_preview_only","selection":null}'
          : '{"policy":{"state":"ready","source":"process_start_manifest","revision_id":null,"generation":"opaque","rules":[],"conflicts":[],"execution_input":"server_trusted_classification_only"}}',
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });

  await client.spawnRules();
  const preview = await client.simulateSpawnRules(["analysis"]);
  assert.deepEqual(requests, [
    { url: "/v1/spawn-rules", body: undefined },
    {
      url: "/v1/spawn-rules/simulate",
      body: { intent_tags: ["analysis"] },
    },
  ]);
  assert.equal(preview.input_trust, "untrusted_preview_only");
});

test("approval policy uses the author-scoped process evidence route", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        policy: {
          state: "configured",
          source: "process_start_manifest",
          generation: "opaque",
          blocking_verbs: ["finance.transfer"],
          approval_timeout_seconds: 900,
          routing: {
            primary_channel: "slack",
            notify_via: [],
            escalation_chain: [],
            serving_state: "inactive_no_consumer",
          },
          changes_apply_at: "process_restart",
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const result = await client.hitlPolicy();
  assert.equal(url, "/v1/hitl/policy");
  assert.equal(result.policy.routing.serving_state, "inactive_no_consumer");
});

test("privacy coverage uses the caller-visible process evidence route", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        policy: {
          state: "partial",
          source: "process_start_manifest",
          generation: "opaque",
          retention: {
            days: 30,
            serving_state: "closed_conversations_only",
            coverage: ["closed_conversation_messages"],
          },
          redaction: {
            configured: true,
            fields: ["email"],
            serving_state: "inactive_no_consumer",
          },
          residency: {
            region: "gb",
            serving_state: "inactive_no_consumer",
          },
          compliance_export: "account_summary_only",
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const result = await client.privacyPolicy();
  assert.equal(url, "/v1/privacy/policy");
  assert.equal(result.policy.redaction.serving_state, "inactive_no_consumer");
});

test("backup status uses the safe freshness-evidence route", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        backup: {
          state: "fresh",
          evidence_kind: "shared_success_marker",
          maximum_age_seconds: 93600,
          last_success_at: "2026-07-29T12:00:00+00:00",
          age_seconds: 90,
          off_box_state: "unknown_not_in_marker",
          encryption_state: "unknown_not_in_marker",
          restore_readiness: "unavailable_no_restore_drill_receipt",
          liveness_claimed: false,
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const result = await client.backupStatus();
  assert.equal(url, "/v1/backup/status");
  assert.equal(result.backup.state, "fresh");
  assert.equal(result.backup.liveness_claimed, false);
  assert.equal(
    result.backup.restore_readiness,
    "unavailable_no_restore_drill_receipt",
  );
});

test("conversation follow uses projected cursor frames and ignores heartbeats", async () => {
  let url = "";
  let request: RequestInit | undefined;
  const client = new BoltrigClient({
    accessToken: () => "session",
    fetch: async (input, init) => {
      url = String(input);
      request = init;
      return new Response(
        'data: {"cursor":4,"event":{"type":"message_start","run_id":"r1","conversation_id":"c/1"},"replay_truncated":true}\n\n' +
        'data: {"cursor":5,"event":{"type":"heartbeat","run_id":"r1"}}\n\n' +
        'data: {"cursor":6,"event":{"type":"tool_call","run_id":"r1","tool":"ticket.create","call_id":"x","args_summary":{"keys":["title"],"count":1}}}\n\n' +
        'data: {"cursor":6,"event":{"type":"message_end","run_id":"r1"}}\n\n',
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  const frames: Array<{ cursor: number; event: ChatEvent; replay_truncated?: boolean }> = [];
  const result = await client.followConversation(
    "c/1",
    (frame) => frames.push(frame),
    { since: 3 },
  );

  assert.equal(url, "/v1/conversations/c%2F1/events?follow=1&since=3");
  assert.equal(request?.method, "GET");
  assert.equal(request?.credentials, "include");
  assert.equal(new Headers(request?.headers).get("authorization"), "Bearer session");
  assert.deepEqual(frames.map((frame) => frame.event.type), [
    "message_start",
    "tool_call",
    "message_end",
  ]);
  assert.equal(frames[0]?.replay_truncated, true);
  assert.deepEqual(result, { status: "ended", cursor: 6 });
});

test("conversation follow reports an idle active-run lookup without inventing a run", async () => {
  const client = new BoltrigClient({
    fetch: async () => new Response(
      '{"status":"idle","conversation_id":"c1"}',
      { status: 409, headers: { "content-type": "application/json" } },
    ),
  });
  assert.deepEqual(
    await client.followConversation("c1", () => undefined, { since: 9 }),
    { status: "idle", cursor: 9 },
  );
});

test("desktop artifact download carries only the rotating Boltrig session", async () => {
  let headers = new Headers();
  const client = new BoltrigClient({
    accessToken: () => "device-session",
    fetch: async (_input, init) => {
      headers = new Headers(init?.headers);
      return new Response(new Uint8Array([1, 2, 3]), { status: 200 });
    },
  });
  assert.deepEqual(await client.downloadArtifact("a/1"), new Uint8Array([1, 2, 3]));
  assert.equal(headers.get("authorization"), "Bearer device-session");
  assert.equal(headers.has("x-api-key"), false);
});

test("certified integration setup posts only the declared field map", async () => {
  let url = "";
  let body: unknown;
  const client = new BoltrigClient({
    fetch: async (input, init) => {
      url = String(input);
      body = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({
        status: "connected",
        connection: {
          id: "conn-1",
          integration_id: "tickets",
          label: "Support",
          health: "pending",
          credential_ref_present: true,
          accounts: [{ id: "support", label: "Support", selected: true }],
          enabled_tools: [],
          created_at: "2026-07-29T00:00:00Z",
        },
      }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const result = await client.submitIntegrationSecret("tickets/a", {
    label: "Support",
    fields: { token: "write-only", account_id: "support" },
  });
  assert.equal(url, "/v1/integrations/tickets%2Fa/secrets");
  assert.deepEqual(body, {
    label: "Support",
    fields: { token: "write-only", account_id: "support" },
  });
  assert.equal(result.connection.credential_ref_present, true);
});

test("artifact pages carry the conversation, limit, and opaque server cursor", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response('{"artifacts":[],"next_cursor":null}', {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  await client.artifacts({
    conversationId: "conversation/a",
    limit: 25,
    cursor: "cursor/a+b",
  });
  assert.equal(
    url,
    "/v1/artifacts?conversation_id=conversation%2Fa&limit=25&cursor=cursor%2Fa%2Bb",
  );
});

test("platform status preserves bounded password-reset attempt evidence", async () => {
  let url = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      url = String(input);
      return new Response(JSON.stringify({
        generated_at: "2026-07-30T12:00:00Z",
        tenant_id: "acme",
        components: [],
        runtimes: [],
        password_reset_delivery: {
          configuration: "configured",
          configuration_reason: null,
          evidence_status: "available",
          last_attempt_at: "2026-07-30T11:59:00Z",
          last_outcome: "accepted_by_notifier",
          evidence_kind: "bounded_audit_attempt_not_provider_receipt",
          proves_recipient_delivery: false,
          target_disclosed: false,
          audit_tail_limit: 500,
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const response = await client.platformStatus();
  assert.equal(url, "/v1/platform/status");
  assert.deepEqual(response.password_reset_delivery, {
    configuration: "configured",
    configuration_reason: null,
    evidence_status: "available",
    last_attempt_at: "2026-07-30T11:59:00Z",
    last_outcome: "accepted_by_notifier",
    evidence_kind: "bounded_audit_attempt_not_provider_receipt",
    proves_recipient_delivery: false,
    target_disclosed: false,
    audit_tail_limit: 500,
  });
});

test("gateway session recovery stays on the admin mint route with an exact channel scope", async () => {
  let url = "";
  let init: RequestInit | undefined;
  const client = new BoltrigClient({
    csrfToken: () => "csrf-value",
    fetch: async (input, requestInit) => {
      url = String(input);
      init = requestInit;
      return new Response(JSON.stringify({
        status: "ok",
        token: "show-once",
        channels: ["channel/a"],
        gateway_id: "channel-gateway",
        expires_in: 3600,
        bootstrap: {
          token_delivery: "show_once",
          recovery: "replace_token_file_or_restart",
          owner_election: "durable_per_channel_lease",
          provider_credentials_included: false,
        },
      }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const response = await client.channelGatewaySession({
    channels: ["channel/a"],
    gateway_id: "channel-gateway",
  });
  assert.equal(url, "/v1/channels/gateway/session");
  assert.equal(init?.method, "POST");
  assert.equal(new Headers(init?.headers).get("x-boltrig-csrf"), "csrf-value");
  assert.deepEqual(JSON.parse(String(init?.body)), {
    channels: ["channel/a"],
    gateway_id: "channel-gateway",
  });
  assert.equal(response.bootstrap?.owner_election, "durable_per_channel_lease");
});

test("Worker parity methods stay on the canonical scoped kernel routes", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "csrf-value",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.meSettings();
  await client.conversationsPage(25, 50);
  await client.searchConversations("renewal / terms", 25, 50);
  await client.login({ email: "worker@example.com", password: "not-a-real-secret" });
  await client.sessionCsrf();
  await client.requestPasswordReset({ email: "worker@example.com" });
  await client.confirmPasswordReset({
    token: "reset-token",
    new_password: "a-new-long-password",
  });
  await client.twoFactorChallenge({ challenge_token: "challenge", code: "123456" });
  await client.acceptInvite({ token: "invite-token", password: "a-longer-password" });
  await client.twoFactorEnrollBegin();
  await client.twoFactorVerifyEnroll({ code: "123456" });
  await client.twoFactorDisable("654321");
  await client.changePassword({ current_password: "old", new_password: "new-password-value" });
  await client.refreshSession();
  await client.logout();
  await client.capabilities();
  await client.runs();
  await client.auditTree("run/a");
  await client.work("awaiting_human");
  await client.workDetail("work/a");
  await client.createWork({
    intent: "Prepare launch",
    owner_member: "engineering",
    parent_id: null,
    convergent: true,
    idempotency_key: "create-work",
  });
  await client.assignWork("work/a", null, "assign-work");
  await client.transitionWork("work/a", "blocked");
  await client.reparentWork("work/a", "work/root");
  await client.knowledgeAssets();
  await client.knowledgeAsset("asset/a");
  await client.knowledgeSearch("renewal period", 7);
  await client.knowledgeProviders();
  await client.memoryFacts({ kind: "decision", limit: 11 });
  await client.memoryFact("fact/a");
  await client.memoryRecall({ query: "renewal", mode: "similarity" });
  await client.memoryRemember({ content: "The renewal period is annual." });
  await client.memoryImprove({ target: "fact/a", signal: "up" });
  await client.memoryForget({ target: "fact/a" });
  await client.workflows();
  await client.workflow("workflow/a");
  await client.upsertWorkflow({
    id: "workflow/a",
    definition: { steps: [] },
  });
  await client.scheduleWorkflow("workflow/a", { cron: "0 9 * * 1-5", timezone: "UTC" });
  await client.unscheduleWorkflow("workflow/a");
  await client.archiveWorkflow("workflow/a");
  await client.restoreWorkflow("workflow/a");
  await client.triggerWorkflow("workflow/a", { inputs: { account: "example" } });
  await client.executeWorkflow("workflow/a", { account: "example" });
  await client.workflowRuns("workflow/a");
  await client.workflowStats();
  await client.workflowTriggers("workflow/a");
  await client.workflowTriggerFinalizations("workflow/a");
  await client.createWorkflowTrigger("workflow/a", {
    name: "release events",
    source: "channel",
    channel_id: "channel/a",
  });
  await client.enableWorkflowTrigger("workflow/a", "trigger/a");
  await client.disableWorkflowTrigger("workflow/a", "trigger/a");
  await client.rotateWorkflowTriggerSecret("workflow/a", "trigger/a");
  await client.workflowTriggerDeliveries("workflow/a", "trigger/a");
  const call = await client.createCall({ conversation_id: "conversation/a" });
  await client.calls(20, "conversation/a");
  await client.currentCall("conversation/a");
  await client.getCall("call/a");
  await client.reopenCall("call/a");
  await client.refreshCallMedia("call/a");
  await client.callEvents("call/a");
  await client.callUsage("call/a");
  await client.endCall("call/a");

  assert.deepEqual(requests.map((item) => item.url), [
    "/v1/me/settings",
    "/v1/conversations?limit=25&offset=50",
    "/v1/conversations/search?q=renewal+%2F+terms&limit=25&offset=50",
    "/v1/auth/login",
    "/v1/auth/csrf",
    "/v1/auth/password-reset/request",
    "/v1/auth/password-reset/confirm",
    "/v1/auth/2fa/challenge",
    "/v1/auth/accept-invite",
    "/v1/auth/2fa/enroll",
    "/v1/auth/2fa/verify-enroll",
    "/v1/auth/2fa/disable",
    "/v1/auth/change-password",
    "/v1/auth/refresh",
    "/v1/auth/logout",
    "/v1/capabilities",
    "/v1/runs",
    "/v1/audit/tree/run%2Fa",
    "/v1/work?status=awaiting_human",
    "/v1/work/work%2Fa",
    "/v1/work",
    "/v1/work/work%2Fa/assignment",
    "/v1/work/work%2Fa/status",
    "/v1/work/work%2Fa/parent",
    "/v1/knowledge/assets?limit=50&offset=0",
    "/v1/knowledge/assets/asset%2Fa",
    "/v1/knowledge/search",
    "/v1/knowledge/providers",
    "/v1/memory/facts?kind=decision&limit=11",
    "/v1/memory/facts/fact%2Fa",
    "/v1/memory/recall",
    "/v1/memory/remember",
    "/v1/memory/improve",
    "/v1/memory/forget",
    "/v1/workflows",
    "/v1/workflows/workflow%2Fa",
    "/v1/workflows",
    "/v1/workflows/workflow%2Fa/schedule",
    "/v1/workflows/workflow%2Fa/unschedule",
    "/v1/workflows/workflow%2Fa/archive",
    "/v1/workflows/workflow%2Fa/restore",
    "/v1/workflows/workflow%2Fa/trigger",
    "/v1/workflows/workflow%2Fa/execute",
    "/v1/workflows/workflow%2Fa/runs",
    "/v1/workflow-stats",
    "/v1/workflows/workflow%2Fa/triggers",
    "/v1/workflows/workflow%2Fa/trigger-finalizations",
    "/v1/workflows/workflow%2Fa/triggers",
    "/v1/workflows/workflow%2Fa/triggers/trigger%2Fa/enable",
    "/v1/workflows/workflow%2Fa/triggers/trigger%2Fa/disable",
    "/v1/workflows/workflow%2Fa/triggers/trigger%2Fa/rotate",
    "/v1/workflows/workflow%2Fa/triggers/trigger%2Fa/deliveries",
    "/v1/calls",
    "/v1/calls?limit=20&conversation_id=conversation%2Fa",
    "/v1/calls/current?conversation_id=conversation%2Fa",
    "/v1/calls/call%2Fa",
    "/v1/calls/call%2Fa/reopen",
    "/v1/calls/call%2Fa/media-token",
    "/v1/calls/call%2Fa/events",
    "/v1/calls/call%2Fa/usage",
    "/v1/calls/call%2Fa/end",
  ]);
  for (const item of requests.filter((request) => request.init?.method === "POST")) {
    assert.equal(new Headers(item.init?.headers).get("x-boltrig-csrf"), "csrf-value");
  }
  assert.deepEqual(
    JSON.parse(String(requests.find((item) => item.url === "/v1/knowledge/search")?.init?.body)),
    { query: "renewal period", limit: 7 },
  );
  assert.deepEqual(
    JSON.parse(String(requests.find((item) => item.url === "/v1/auth/login")?.init?.body)),
    { email: "worker@example.com", password: "not-a-real-secret" },
  );
  assert.deepEqual(
    JSON.parse(String(
      requests.find((item) => item.url === "/v1/auth/password-reset/confirm")?.init?.body,
    )),
    { token: "reset-token", new_password: "a-new-long-password" },
  );
  assert.deepEqual(
    JSON.parse(String(requests.find((item) => item.url.endsWith("/trigger"))?.init?.body)),
    { inputs: { account: "example" } },
  );
  assert.deepEqual(
    JSON.parse(String(requests.find((item) => item.url.endsWith("/execute"))?.init?.body)),
    { inputs: { account: "example" } },
  );
  assert.deepEqual(
    JSON.parse(String(
      requests.find((item) => (
        item.url === "/v1/workflows/workflow%2Fa/triggers"
        && item.init?.method === "POST"
      ))?.init?.body,
    )),
    {
      name: "release events",
      source: "channel",
      channel_id: "channel/a",
    },
  );
  assert.deepEqual(
    JSON.parse(String(
      requests.find((item) => item.url === "/v1/work/work%2Fa/parent")?.init?.body,
    )),
    { parent_id: "work/root" },
  );
  assert.equal(call.call.status, "realtime_unavailable");
  assert.equal(call.text_continuation_conversation_id, "conversation/a");
});

test("pagination and replacement-safe author reads remain canonical", async () => {
  const requests: string[] = [];
  const client = new BoltrigClient({
    fetch: async (input) => {
      requests.push(String(input));
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.runs({
    limit: 40,
    cursor: "run/cursor",
    owner: "ops",
    onBehalfOf: "alice",
    label: "renewal",
    source: "chat",
    externalRef: "matter/a",
  });
  await client.work("in_flight", { limit: 30, cursor: "work/cursor" });
  await client.skill("analysis/risk");
  await client.noun("case/type");
  await client.verb("case/review");
  await client.modelEndpoint("local/model");

  assert.deepEqual(requests, [
    "/v1/runs?limit=40&cursor=run%2Fcursor&owner=ops&on_behalf_of=alice&label=renewal&source=chat&external_ref=matter%2Fa",
    "/v1/work?status=in_flight&limit=30&cursor=work%2Fcursor",
    "/v1/skills/analysis%2Frisk",
    "/v1/nouns/case%2Ftype",
    "/v1/verbs/case%2Freview",
    "/v1/model-endpoints/local%2Fmodel",
  ]);
});

test("webhook secret finalization replays the exact approval without persisting plaintext", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "csrf-value",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response('{"status":"ok","secret":"wft_once"}', {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.createWorkflowTrigger(
    "workflow/a",
    { name: "events", source: "webhook" },
    "approval/create",
  );
  await client.rotateWorkflowTriggerSecret(
    "workflow/a",
    "trigger/a",
    "approval/rotate",
  );

  assert.deepEqual(requests.map(({ url, init }) => ({
    url,
    body: JSON.parse(String(init?.body)),
  })), [
    {
      url: "/v1/workflows/workflow%2Fa/triggers",
      body: {
        name: "events",
        source: "webhook",
        approval_id: "approval/create",
      },
    },
    {
      url: "/v1/workflows/workflow%2Fa/triggers/trigger%2Fa/rotate",
      body: { approval_id: "approval/rotate" },
    },
  ]);
});
