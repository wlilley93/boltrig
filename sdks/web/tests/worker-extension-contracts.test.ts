import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient } from "../src/index.js";

test("agent lifecycle replay carries internal approval on the exact route", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "profile-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.retireAgentCapability("profile/a", "approval/a");
  await client.restoreAgentCapability("profile/a", "approval/b");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/agent-capabilities/profile%2Fa/retire",
    "/v1/agent-capabilities/profile%2Fa/restore",
  ]);
  assert.equal(
    new Headers(requests[0]?.init?.headers).get("x-boltrig-approval-id"),
    "approval/a",
  );
  assert.equal(
    new Headers(requests[1]?.init?.headers).get("x-boltrig-approval-id"),
    "approval/b",
  );
  assert.equal(
    new Headers(requests[0]?.init?.headers).get("x-boltrig-csrf"),
    "profile-csrf",
  );
});

test("external MCP lifecycle and correction replay use exact routes, bodies, and approval headers", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "mcp-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.probeMcpServer("docs/a", "approval/probe");
  await client.activateMcpServer("docs/a", "approval/activate");
  await client.deactivateMcpServer("docs/a", "approval/deactivate");
  await client.retireMcpServer("docs/a", "approval/retire");
  await client.restoreMcpServer("docs/a", "approval/restore");
  await client.updateMcpServer("docs/a", {
    url: "https://new.example.test/private/mcp",
    allow_internal: false,
    credential_mode: "replace",
    credential_ref: "DOCS_TOKEN_V2",
    credential_id: "docs-v2",
    credential_store: "env",
    credential_kind: "bearer",
  }, "approval/update");
  await client.deleteMcpServer("docs/a", "approval/delete");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/mcp/servers/docs%2Fa/probe",
    "/v1/mcp/servers/docs%2Fa/activate",
    "/v1/mcp/servers/docs%2Fa/deactivate",
    "/v1/mcp/servers/docs%2Fa/retire",
    "/v1/mcp/servers/docs%2Fa/restore",
    "/v1/mcp/servers/docs%2Fa",
    "/v1/mcp/servers/docs%2Fa",
  ]);
  assert.deepEqual(requests.map(({ init }) => init?.method), [
    "POST",
    "POST",
    "POST",
    "POST",
    "POST",
    "PUT",
    "DELETE",
  ]);
  assert.deepEqual(JSON.parse(String(requests[5]?.init?.body)), {
    url: "https://new.example.test/private/mcp",
    allow_internal: false,
    credential_mode: "replace",
    credential_ref: "DOCS_TOKEN_V2",
    credential_id: "docs-v2",
    credential_store: "env",
    credential_kind: "bearer",
  });
  assert.equal(requests[6]?.init?.body, undefined);
  assert.deepEqual(
    requests.map(({ init }) => (
      new Headers(init?.headers).get("x-boltrig-approval-id")
    )),
    [
      "approval/probe",
      "approval/activate",
      "approval/deactivate",
      "approval/retire",
      "approval/restore",
      "approval/update",
      "approval/delete",
    ],
  );
  for (const { init } of requests) {
    assert.equal(new Headers(init?.headers).get("x-boltrig-csrf"), "mcp-csrf");
  }
});

test("adapter lifecycle and integration revocation replay exact approval-bound routes", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "surface-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.activateAdapter(
    "tickets/a",
    { reviewer: "reviewer/a" },
    "approval/activate",
  );
  await client.deactivateAdapter("tickets/a", "approval/deactivate");
  await client.deleteAdapter("tickets/a", "approval/delete");
  await client.disconnectIntegration("connection/a", "approval/revoke");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/adapters/tickets%2Fa/activate",
    "/v1/adapters/tickets%2Fa/deactivate",
    "/v1/adapters/tickets%2Fa",
    "/v1/integrations/connections/connection%2Fa",
  ]);
  assert.deepEqual(requests.map(({ init }) => init?.method), [
    "POST",
    "POST",
    "DELETE",
    "DELETE",
  ]);
  assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), {
    reviewer: "reviewer/a",
  });
  assert.equal(requests[1]?.init?.body, undefined);
  assert.equal(requests[2]?.init?.body, undefined);
  assert.equal(requests[3]?.init?.body, undefined);
  assert.deepEqual(
    requests.map(({ init }) => (
      new Headers(init?.headers).get("x-boltrig-approval-id")
    )),
    [
      "approval/activate",
      "approval/deactivate",
      "approval/delete",
      "approval/revoke",
    ],
  );
  for (const { init } of requests) {
    assert.equal(
      new Headers(init?.headers).get("x-boltrig-csrf"),
      "surface-csrf",
    );
  }
});

test("fixed fleet and endpoint replay carries approval on the exact SDK routes", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "fixed-control-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const hierarchy = {
    chief: {
      name: "chief-of-staff",
      routing_id: "cos",
      purpose: "Route work",
      brief: "",
      runtime: "codex" as const,
      model_endpoint: null,
      supported_skills: ["*"],
      max_depth: 4,
      cost_tier: "standard" as const,
      budget: null,
    },
    departments: [{
      name: "research-head",
      routing_id: "research",
      purpose: "Own research",
      brief: "",
      runtime: "codex" as const,
      model_endpoint: null,
      supported_skills: ["research"],
      max_depth: 3,
      cost_tier: "standard" as const,
      budget: null,
    }],
  };

  await client.applyPermanentFleet(hierarchy, "approval/fleet");
  await client.retireModelEndpoint("endpoint/a", "approval/retire");
  await client.restoreModelEndpoint("endpoint/a", "approval/restore");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/permanent-fleet",
    "/v1/model-endpoints/endpoint%2Fa/retire",
    "/v1/model-endpoints/endpoint%2Fa/restore",
  ]);
  assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), { hierarchy });
  assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), {});
  assert.deepEqual(JSON.parse(String(requests[2]?.init?.body)), {});
  assert.deepEqual(
    requests.map(({ init }) => (
      new Headers(init?.headers).get("x-boltrig-approval-id")
    )),
    ["approval/fleet", "approval/retire", "approval/restore"],
  );
  for (const { init } of requests) {
    assert.equal(
      new Headers(init?.headers).get("x-boltrig-csrf"),
      "fixed-control-csrf",
    );
  }
});

test("authored definition replay carries approval on every exact SDK route", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "definition-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/definition";
  const skill = { id: "records/review", prompt_fragment: "Review." };
  const noun = { id: "ticket", description: "Ticket" };
  const verb = { id: "ticket.read", noun_id: "ticket" };
  const binding = { target_type: "adapter" as const, target_ref: "tickets" };

  await client.upsertSkill(skill, approval);
  await client.archiveSkill("records/review", approval);
  await client.restoreSkill("records/review", approval);
  await client.upsertNoun(noun, approval);
  await client.archiveNoun("ticket", approval);
  await client.restoreNoun("ticket", approval);
  await client.upsertVerb(verb, approval);
  await client.archiveVerb("ticket.read", approval);
  await client.restoreVerb("ticket.read", approval);
  await client.setBinding("ticket.read", binding, approval);

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/skills",
    "/v1/skills/records%2Freview/archive",
    "/v1/skills/records%2Freview/restore",
    "/v1/nouns",
    "/v1/nouns/ticket/archive",
    "/v1/nouns/ticket/restore",
    "/v1/verbs",
    "/v1/verbs/ticket.read/archive",
    "/v1/verbs/ticket.read/restore",
    "/v1/verbs/ticket.read/binding",
  ]);
  assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), skill);
  assert.deepEqual(JSON.parse(String(requests[3]?.init?.body)), noun);
  assert.deepEqual(JSON.parse(String(requests[6]?.init?.body)), verb);
  assert.deepEqual(JSON.parse(String(requests[9]?.init?.body)), binding);
  for (const { init } of requests) {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "definition-csrf");
  }
});

test("Knowledge mutation replay carries internal approval on the exact route", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "knowledge-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.setKnowledgeProvider("graph/a", true, "approval/provider");
  await client.eraseKnowledgeAsset("asset/a", "approval/erase");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/knowledge/providers/graph%2Fa",
    "/v1/knowledge/assets/asset%2Fa",
  ]);
  assert.equal(
    new Headers(requests[0]?.init?.headers).get("x-boltrig-approval-id"),
    "approval/provider",
  );
  assert.equal(
    new Headers(requests[1]?.init?.headers).get("x-boltrig-approval-id"),
    "approval/erase",
  );
  assert.equal(requests[1]?.init?.method, "DELETE");
});

test("Memory mutation replay carries internal approval on each exact route", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "memory-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/memory";

  await client.memoryRemember({ content: "fact" }, approval);
  await client.memoryImprove({ target: "fact/a", signal: "up" }, approval);
  await client.memoryForget({ source_ref: "source/a" }, approval);
  await client.memoryIngest({
    source_kind: "document",
    source_ref: "source/a",
    items: ["fact"],
  }, approval);

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/memory/remember",
    "/v1/memory/improve",
    "/v1/memory/forget",
    "/v1/memory/ingest",
  ]);
  for (const { init } of requests) {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "memory-csrf");
  }
});

test("Work mutation replay preserves its exact body and internal approval", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "work-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/work";

  await client.createWork({
    intent: "Exact task",
    idempotency_key: "create-key",
  }, approval);
  await client.assignWork("work/a", "operations", "assign-key", approval);
  await client.transitionWork("work/a", "blocked", "status-key", approval);
  await client.reparentWork("work/a", "work/root", "parent-key", approval);

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/work",
    "/v1/work/work%2Fa/assignment",
    "/v1/work/work%2Fa/status",
    "/v1/work/work%2Fa/parent",
  ]);
  assert.deepEqual(JSON.parse(String(requests[2]?.init?.body)), {
    status: "blocked",
    idempotency_key: "status-key",
  });
  for (const { init } of requests) {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "work-csrf");
  }
});

test("evaluation history preserves the server-recorded target and verdict detail", async () => {
  let requested = "";
  const client = new BoltrigClient({
    fetch: async (input) => {
      requested = String(input);
      return new Response(JSON.stringify({
        runs: [{
          id: "eval-run/a",
          case_id: "case/a",
          passed: true,
          score: 1,
          run_id: "run/a",
          target_kind: "workflow",
          target_ref: "workflow/a",
          detail: {
            target: { kind: "workflow", ref: "workflow/a" },
            workflow_status: "completed",
          },
          created_at: "2026-07-29T00:00:00+00:00",
        }],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const response = await client.evalRuns("case/a");

  assert.equal(requested, "/v1/eval/runs?case_id=case%2Fa");
  assert.deepEqual(response.runs[0], {
    id: "eval-run/a",
    case_id: "case/a",
    passed: true,
    score: 1,
    run_id: "run/a",
    target_kind: "workflow",
    target_ref: "workflow/a",
    detail: {
      target: { kind: "workflow", ref: "workflow/a" },
      workflow_status: "completed",
    },
    created_at: "2026-07-29T00:00:00+00:00",
  });
});

test("channel delivery recovery carries only the exact safe receipt revision", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "delivery-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ deliveries: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.channelDeliveries("channel/a", 500);
  await client.retryChannelDelivery(
    "channel/a",
    "message/a",
    "2026-07-30T08:05:00+00:00",
    "approval/a",
  );

  assert.equal(
    requests[0]?.url,
    "/v1/channels/channel%2Fa/deliveries?limit=100",
  );
  assert.equal(
    requests[1]?.url,
    "/v1/channels/channel%2Fa/deliveries/message%2Fa/retry",
  );
  assert.equal(requests[1]?.init?.method, "POST");
  assert.equal(
    new Headers(requests[1]?.init?.headers).get("x-boltrig-csrf"),
    "delivery-csrf",
  );
  assert.deepEqual(
    JSON.parse(String(requests[1]?.init?.body)),
    {
      expected_updated_at: "2026-07-30T08:05:00+00:00",
    },
  );
  assert.equal(
    new Headers(requests[1]?.init?.headers).get("x-boltrig-approval-id"),
    "approval/a",
  );
});

test("channel mutations replay on exact SDK routes and pairing discovery is read-only", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "channel-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({
        status: "ok",
        channel_id: "channel/a",
        finalizations: [],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/channel";

  await client.connectChannel({
    platform: "webhook",
    name: "Support",
    signing_secret_ref: "SUPPORT_SIGNING",
  }, approval);
  await client.configureChannel("channel/a", {
    name: "Priority support",
    enabled: true,
  }, approval);
  await client.disconnectChannel("channel/a", approval);
  await client.pairChannel("channel/a", {
    external_user_id: "sender/a",
    subject: "user:alice",
    role: "member",
    ttl_minutes: 15,
  }, approval);
  await client.channelPairFinalizations("channel/a");
  await client.bindChannel("channel/a", {
    external_user_id: "sender/b",
    subject: "user:bob",
    role: "member",
  }, approval);
  await client.deleteChannelBinding("channel/a", "binding/a", approval);

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/channels",
    "/v1/channels/channel%2Fa",
    "/v1/channels/channel%2Fa",
    "/v1/channels/channel%2Fa/pair",
    "/v1/channels/channel%2Fa/pair-finalizations",
    "/v1/channels/channel%2Fa/bindings",
    "/v1/channels/channel%2Fa/bindings/binding%2Fa",
  ]);
  assert.deepEqual(requests.map(({ init }) => init?.method ?? "GET"), [
    "POST",
    "PATCH",
    "DELETE",
    "POST",
    "GET",
    "POST",
    "DELETE",
  ]);
  for (const index of [0, 1, 2, 3, 5, 6]) {
    const headers = new Headers(requests[index]?.init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "channel-csrf");
    assert.doesNotMatch(String(requests[index]?.init?.body), /approval_id/);
  }
  assert.equal(
    new Headers(requests[4]?.init?.headers)
      .get("x-boltrig-approval-id"),
    null,
  );
});

test("workflow occurrence recovery replays one exact logical run with internal approval evidence", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "occurrence-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ occurrences: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const scheduledFor = "2026-07-30T09:00:00+00:00";

  await client.workflowScheduleOccurrences("workflow/a", 500);
  await client.retryWorkflowScheduleOccurrence(
    "workflow/a",
    scheduledFor,
    "wfs_exact",
    "approval/a",
  );

  assert.equal(
    requests[0]?.url,
    "/v1/workflows/workflow%2Fa/schedule/occurrences?limit=50",
  );
  assert.equal(
    requests[1]?.url,
    "/v1/workflows/workflow%2Fa/schedule/occurrences/2026-07-30T09%3A00%3A00%2B00%3A00/retry",
  );
  assert.equal(requests[1]?.init?.method, "POST");
  assert.equal(
    new Headers(requests[1]?.init?.headers).get("x-boltrig-csrf"),
    "occurrence-csrf",
  );
  assert.deepEqual(
    JSON.parse(String(requests[1]?.init?.body)),
    { run_id: "wfs_exact", approval_id: "approval/a" },
  );
});

test("workflow and evaluation caller-lane replay stays on each exact SDK route", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "caller-lane-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/caller-lane";

  await client.upsertWorkflow(
    { id: "workflow/a", definition: { steps: [] } },
    approval,
  );
  await client.scheduleWorkflow(
    "workflow/a",
    { cron: "0 9 * * *", timezone: "UTC" },
    approval,
  );
  await client.unscheduleWorkflow("workflow/a", approval);
  await client.archiveWorkflow("workflow/a", approval);
  await client.restoreWorkflow("workflow/a", approval);
  await client.triggerWorkflow(
    "workflow/a", { inputs: { source: "manual" } }, approval,
  );
  await client.executeWorkflow(
    "workflow/a", { source: "manual" }, approval,
  );
  await client.createEvalCase({
    id: "eval/a",
    target_kind: "workflow",
    target_ref: "workflow/a",
  }, approval);
  await client.archiveEvalCase("eval/a", approval);
  await client.restoreEvalCase("eval/a", approval);

  assert.deepEqual(requests.map((request) => request.url), [
    "/v1/workflows",
    "/v1/workflows/workflow%2Fa/schedule",
    "/v1/workflows/workflow%2Fa/unschedule",
    "/v1/workflows/workflow%2Fa/archive",
    "/v1/workflows/workflow%2Fa/restore",
    "/v1/workflows/workflow%2Fa/trigger",
    "/v1/workflows/workflow%2Fa/execute",
    "/v1/eval/cases",
    "/v1/eval/cases/eval%2Fa/archive",
    "/v1/eval/cases/eval%2Fa/restore",
  ]);
  for (const request of requests) {
    const headers = new Headers(request.init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "caller-lane-csrf");
  }
  assert.deepEqual(
    JSON.parse(String(requests[5]?.init?.body)),
    { inputs: { source: "manual" } },
  );
  assert.deepEqual(
    JSON.parse(String(requests[6]?.init?.body)),
    { inputs: { source: "manual" } },
  );
});

test("fixed governed SDK methods replay through their same route with internal approval evidence", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "fixed-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const approval = "approval/fixed";

  await client.putMeNotification({
    event_type: "approval",
    channel: "channel/a",
    target: "user/a",
    enabled: true,
  }, approval);
  await client.patchUser("user/a", { role: "member" }, approval);
  await client.createInvitation({
    email: "member@example.test",
    role: "member",
  }, approval);
  await client.revokeInvitation("invite/a", approval);
  await client.updateCurrentOrg({ name: "Acme" }, approval);
  await client.createWorkspace({ name: "Ops" }, approval);
  await client.updateWorkspace("workspace/a", { status: "archived" }, approval);
  await client.addWorkspaceMember(
    "workspace/a", { user_id: "user/a", role: "member" }, approval,
  );
  await client.removeWorkspaceMember("workspace/a", "user/a", approval);
  await client.upsertBudget(
    "tenant",
    "acme",
    { window: "monthly", hard_stop: true, token_limit: 1000 },
    approval,
  );
  await client.resetBudget("tenant", "acme", "monthly", approval);

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/me/notifications",
    "/v1/admin/users/user%2Fa",
    "/v1/admin/invitations",
    "/v1/admin/invitations/invite%2Fa",
    "/v1/orgs/current",
    "/v1/workspaces",
    "/v1/workspaces/workspace%2Fa",
    "/v1/workspaces/workspace%2Fa/members",
    "/v1/workspaces/workspace%2Fa/members/user%2Fa",
    "/v1/budgets/tenant/acme",
    "/v1/budgets/tenant/acme/reset",
  ]);
  for (const { init } of requests) {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("x-boltrig-approval-id"), approval);
    assert.equal(headers.get("x-boltrig-csrf"), "fixed-csrf");
  }
  assert.deepEqual(
    JSON.parse(String(requests.at(-1)?.init?.body)),
    { reason: "Worker-authorised current-window usage reset" },
  );
});

test("Worker build, knowledge, memory, and run controls use canonical routes", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "extension-csrf",
    fetch: async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      const body = url === "/v1/knowledge/uploads"
        ? JSON.stringify({ upload_id: "upload/a" })
        : "{}";
      return new Response(body, {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.runTopology("run/a");
  await client.capabilityChangelog();
  await client.aiKeys();
  await client.setAiKey({
    level: "user",
    provider: "openai",
    model: "approved",
    api_key: "write-only",
  });
  await client.activateAiKey({ level: "user", scope_id: "user/a" });
  await client.aiKeyProposals();
  await client.aiKeyProposal("proposal/a");
  await client.finalizeAiKeyProposal("proposal/a");
  await client.approveAiKeyProposal("proposal/a");
  await client.invalidateAiKeyProposal("proposal/a");
  await client.deleteAiKey("user", "user/a", "approval/a");
  await client.agentCapabilities();
  await client.permanentFleet();
  await client.applyPermanentFleet({
    chief: {
      name: "chief-of-staff",
      routing_id: "cos",
      purpose: "Route work",
      brief: "",
      runtime: "codex",
      model_endpoint: null,
      supported_skills: ["*"],
      max_depth: 3,
      cost_tier: "standard",
      budget: null,
    },
    departments: [{
      name: "research-head",
      routing_id: "research",
      purpose: "Own research",
      brief: "",
      runtime: "codex",
      model_endpoint: null,
      supported_skills: ["research"],
      max_depth: 3,
      cost_tier: "standard",
      budget: null,
    }],
  });
  await client.retireAgentCapability("profile/a");
  await client.restoreAgentCapability("profile/a");
  await client.retireModelEndpoint("endpoint/a");
  await client.restoreModelEndpoint("endpoint/a");
  await client.archiveEvalCase("eval/a");
  await client.restoreEvalCase("eval/a");
  await client.invoke({ noun: "control", verb: "control.capability.upsert" });
  await client.spawn({ task: "bounded test", skills: ["review"] });
  await client.skills();
  await client.archiveSkill("review/a");
  await client.restoreSkill("review/a");
  await client.upsertSkill({ id: "review" });
  await client.testSpawn("review/a", { task: "test" });
  await client.nouns();
  await client.archiveNoun("ticket/a");
  await client.restoreNoun("ticket/a");
  await client.upsertNoun({ id: "ticket" });
  await client.verbs();
  await client.archiveVerb("ticket.read/a");
  await client.restoreVerb("ticket.read/a");
  await client.upsertVerb({ id: "ticket.read", noun_id: "ticket" });
  await client.setBinding("ticket.read", { target_type: "adapter", target_ref: "tickets" });
  await client.generateAdapter({ adapter_id: "tickets", spec: {} });
  await client.adapterSource("tickets/a");
  await client.activateAdapter("tickets/a", { reviewer: "reviewer/a" });
  await client.deactivateAdapter("tickets/a");
  await client.deleteAdapter("tickets/a");
  await client.registerMcpServer({
    id: "docs",
    url: "https://example.test/mcp",
    credential_ref: "DOCS_MCP_TOKEN",
  });
  await client.mcpServers();
  await client.mcpServer("docs/a");
  await client.activateMcpServer("docs/a");
  await client.deactivateMcpServer("docs/a");
  await client.probeMcpServer("docs/a");
  await client.retireMcpServer("docs/a");
  await client.restoreMcpServer("docs/a");
  await client.updateMcpServer("docs/a", {
    url: "https://example.test/mcp/v2",
    allow_internal: false,
    credential_mode: "preserve",
  });
  await client.deleteMcpServer("docs/a");
  await client.adapters();
  await client.setKnowledgeProvider("lexical/a", true);
  await client.eraseKnowledgeAsset("asset/a");
  await client.uploadKnowledge(
    new File(["source"], "source.txt", { type: "text/plain" }),
    "Source",
  );
  await client.knowledgeOriginal("asset/a");
  await client.memoryIngest({
    source_kind: "conversation",
    source_ref: "conversation/a",
    items: ["A screened fact"],
  });
  await client.memoryIngestions();
  await client.devices();
  await client.deviceLeases("device/a");
  await client.startDeviceEnrollment("Office Mac");
  await client.createDeviceRoot("device/a", {
    label: "Workspace",
    scope: "read",
  });
  await client.revokeDeviceRoot("device/a", "root/a");
  await client.revokeDevice("device/a");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/runs/run%2Fa/topology",
    "/v1/capabilities/changelog",
    "/v1/ai-keys",
    "/v1/ai-keys",
    "/v1/ai-keys/activate",
    "/v1/ai-keys/proposals",
    "/v1/ai-keys/proposals/proposal%2Fa",
    "/v1/ai-keys/proposals/proposal%2Fa/finalize",
    "/v1/ai-keys/proposals/proposal%2Fa/approve",
    "/v1/ai-keys/proposals/proposal%2Fa",
    "/v1/ai-keys/user/user%2Fa",
    "/v1/agent-capabilities",
    "/v1/permanent-fleet",
    "/v1/permanent-fleet",
    "/v1/agent-capabilities/profile%2Fa/retire",
    "/v1/agent-capabilities/profile%2Fa/restore",
    "/v1/model-endpoints/endpoint%2Fa/retire",
    "/v1/model-endpoints/endpoint%2Fa/restore",
    "/v1/eval/cases/eval%2Fa/archive",
    "/v1/eval/cases/eval%2Fa/restore",
    "/v1/invoke",
    "/v1/spawn",
    "/v1/skills",
    "/v1/skills/review%2Fa/archive",
    "/v1/skills/review%2Fa/restore",
    "/v1/skills",
    "/v1/skills/review%2Fa/test-spawn",
    "/v1/nouns",
    "/v1/nouns/ticket%2Fa/archive",
    "/v1/nouns/ticket%2Fa/restore",
    "/v1/nouns",
    "/v1/verbs",
    "/v1/verbs/ticket.read%2Fa/archive",
    "/v1/verbs/ticket.read%2Fa/restore",
    "/v1/verbs",
    "/v1/verbs/ticket.read/binding",
    "/v1/adapters/generate",
    "/v1/adapters/tickets%2Fa/source",
    "/v1/adapters/tickets%2Fa/activate",
    "/v1/adapters/tickets%2Fa/deactivate",
    "/v1/adapters/tickets%2Fa",
    "/v1/mcp/servers",
    "/v1/mcp/servers",
    "/v1/mcp/servers/docs%2Fa",
    "/v1/mcp/servers/docs%2Fa/activate",
    "/v1/mcp/servers/docs%2Fa/deactivate",
    "/v1/mcp/servers/docs%2Fa/probe",
    "/v1/mcp/servers/docs%2Fa/retire",
    "/v1/mcp/servers/docs%2Fa/restore",
    "/v1/mcp/servers/docs%2Fa",
    "/v1/mcp/servers/docs%2Fa",
    "/v1/adapters",
    "/v1/knowledge/providers/lexical%2Fa",
    "/v1/knowledge/assets/asset%2Fa",
    "/v1/knowledge/uploads",
    "/v1/knowledge/uploads/upload%2Fa",
    "/v1/knowledge/uploads/upload%2Fa/commit",
    "/v1/knowledge/assets/asset%2Fa/original",
    "/v1/memory/ingest",
    "/v1/memory/ingestions",
    "/v1/devices",
    "/v1/devices/device%2Fa/leases",
    "/v1/devices/enrollment/start",
    "/v1/devices/device%2Fa/roots",
    "/v1/devices/device%2Fa/roots/root%2Fa",
    "/v1/devices/device%2Fa",
  ]);
  const deleteKey = requests.find(
    ({ url }) => url === "/v1/ai-keys/user/user%2Fa",
  );
  assert.equal(
    new Headers(deleteKey?.init?.headers).get("x-boltrig-approval-id"),
    "approval/a",
  );
  const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  for (const { init } of requests.filter(({ init }) => mutating.has(init?.method ?? ""))) {
    assert.equal(new Headers(init?.headers).get("x-boltrig-csrf"), "extension-csrf");
  }
});
