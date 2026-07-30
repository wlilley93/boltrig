import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient } from "../src/index.js";

test("account and organisation methods use only canonical scoped routes", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "account-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.putMeSettings({ key: "theme", value: "dark" });
  await client.meActivity();
  await client.meExport();
  await client.renameConversation("conversation/a", "Renewals");
  await client.regenerateMessage("conversation/a", "message/a");
  await client.deleteMyConversation("conversation/a");
  await client.restoreMyConversation("conversation/a");
  await client.meTokens();
  await client.mintToken({ name: "CLI", scope: ["work.read"], ttl_days: 7 });
  await client.revokeToken("token/a");
  await client.meConnections();
  await client.meSessions();
  await client.revokeSession("session/a");
  await client.switchActiveContext("workspace/a");
  await client.switchActiveOrg("org/a");
  await client.meNotifications();
  await client.putMeNotification({
    event_type: "approval",
    channel: "channel/a",
    target: "U-a",
    enabled: true,
  });
  await client.testMeNotification("notification/a");
  await client.meAgent();
  await client.configurePersonalAgent({ runtime: "codex", skills: ["analysis/*"] });
  await client.invokePersonalAgent({ message: "Review queue" });
  await client.deletePersonalAgent();
  await client.currentOrg();
  await client.myOrganisations();
  await client.updateCurrentOrg({ name: "Acme" });
  await client.orgMembers();
  await client.workspaces();
  await client.createWorkspace({ name: "Operations" });
  await client.updateWorkspace("workspace/a", { status: "archived" });
  await client.workspaceMembers("workspace/a");
  await client.addWorkspaceMember("workspace/a", {
    user_id: "member/a",
    role: "member",
  });
  await client.removeWorkspaceMember("workspace/a", "member/a");
  await client.adminUsers();
  await client.patchUser("member/a", { status: "deactivated" });
  await client.adminInvitations();
  await client.createInvitation({ email: "invite@example.test", role: "member" });
  await client.revokeInvitation("invite/a");

  assert.deepEqual(requests.map(({ url }) => url), [
    "/v1/me/settings",
    "/v1/me/activity",
    "/v1/me/export",
    "/v1/me/conversations/conversation%2Fa",
    "/v1/me/conversations/conversation%2Fa/messages/message%2Fa/regenerate",
    "/v1/me/conversations/conversation%2Fa",
    "/v1/me/conversations/conversation%2Fa/restore",
    "/v1/me/tokens",
    "/v1/me/tokens",
    "/v1/me/tokens/token%2Fa",
    "/v1/me/connections",
    "/v1/me/sessions",
    "/v1/me/sessions/session%2Fa",
    "/v1/me/active-context",
    "/v1/me/active-org",
    "/v1/me/notifications",
    "/v1/me/notifications",
    "/v1/me/notifications/notification%2Fa/test",
    "/v1/me/agent",
    "/v1/me/agent",
    "/v1/me/agent/invoke",
    "/v1/me/agent",
    "/v1/orgs/current",
    "/v1/me/orgs",
    "/v1/orgs/current",
    "/v1/orgs/current/members",
    "/v1/workspaces",
    "/v1/workspaces",
    "/v1/workspaces/workspace%2Fa",
    "/v1/workspaces/workspace%2Fa/members",
    "/v1/workspaces/workspace%2Fa/members",
    "/v1/workspaces/workspace%2Fa/members/member%2Fa",
    "/v1/admin/users",
    "/v1/admin/users/member%2Fa",
    "/v1/admin/invitations",
    "/v1/admin/invitations",
    "/v1/admin/invitations/invite%2Fa",
  ]);
  const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  for (const { init } of requests.filter(({ init }) => mutating.has(String(init?.method)))) {
    assert.equal(new Headers(init?.headers).get("x-boltrig-csrf"), "account-csrf");
  }
  assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), {
    key: "theme",
    value: "dark",
  });
  assert.deepEqual(JSON.parse(String(requests[13]?.init?.body)), {
    workspace_id: "workspace/a",
  });
  assert.deepEqual(JSON.parse(String(requests[14]?.init?.body)), {
    org_id: "org/a",
  });
});

test("role denials remain typed response states for the Worker to render", async () => {
  const client = new BoltrigClient({
    fetch: async () => new Response(
      JSON.stringify({ status: "denied", reason: "organisation administration required" }),
      { status: 403, headers: { "content-type": "application/json" } },
    ),
  });

  assert.deepEqual(await client.adminUsers(), {
    status: "denied",
    reason: "organisation administration required",
  });
  assert.deepEqual(await client.createWorkspace({ name: "Restricted" }), {
    status: "denied",
    reason: "organisation administration required",
  });
});

test("question answers use the owner-scoped answer route and retain typed denials", async () => {
  let request: { url: string; init?: RequestInit } | undefined;
  const client = new BoltrigClient({
    csrfToken: () => "hitl-csrf",
    fetch: async (input, init) => {
      request = { url: String(input), init };
      return new Response(
        JSON.stringify({ status: "denied", reason: "not your run" }),
        { status: 403, headers: { "content-type": "application/json" } },
      );
    },
  });

  assert.deepEqual(await client.answerQuestion("question/a", "Use the signed copy"), {
    status: "denied",
    reason: "not your run",
  });
  assert.equal(request?.url, "/v1/hitl/question%2Fa/answer");
  assert.equal(request?.init?.method, "POST");
  assert.equal(new Headers(request?.init?.headers).get("x-boltrig-csrf"), "hitl-csrf");
  assert.deepEqual(JSON.parse(String(request?.init?.body)), {
    answer: "Use the signed copy",
  });
});
