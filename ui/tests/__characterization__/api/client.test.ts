import { describe, expect, it } from "vitest";
import {
  ApiError,
  api,
  StreamIdleError,
  streamChat,
  streamRunEvents,
} from "@/api/client";

describe("api/client (public surface)", () => {
  it("exposes ApiError with status and body", () => {
    const err = new ApiError(403, "denied", { reason: "no grant" });
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(403);
    expect(err.message).toBe("denied");
    expect(err.body).toEqual({ reason: "no grant" });
  });

  it("exposes StreamIdleError as an ApiError subclass", () => {
    const err = new StreamIdleError(120_000);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.name).toBe("StreamIdleError");
    expect(err.status).toBe(0);
    expect(err.message).toBe("stream idle for 120s (no data)");
  });

  it("exposes stream entry points", () => {
    expect(streamChat).toBeTypeOf("function");
    expect(streamRunEvents).toBeTypeOf("function");
  });

  it("exposes the assembled api object with every legacy method", () => {
    const expected = [
      // core
      "health",
      "capabilities",
      "capabilityChangelog",
      "invoke",
      "spawn",
      "work",
      "hitl",
      "respondHitl",
      "answerQuestion",
      "auditTree",
      "conversations",
      "listConversations",
      "searchConversations",
      "conversation",
      "regenerateMessage",
      "cancelRun",
      // studio
      "skills",
      "upsertSkill",
      "testSpawn",
      "upsertNoun",
      "upsertVerb",
      "setBinding",
      "generateAdapter",
      "adapterSource",
      "activateAdapter",
      "registerMcpServer",
      "adapters",
      "workflows",
      "getWorkflow",
      "upsertWorkflow",
      "scheduleWorkflow",
      "triggerWorkflow",
      "executeWorkflow",
      "workflowRuns",
      // admin config
      "getConfig",
      "putConfig",
      "configHistory",
      "configRollback",
      "configExport",
      "adminCredentials",
      // channels
      "channels",
      "connectChannel",
      "configureChannel",
      "disconnectChannel",
      "channelBindings",
      "pairChannel",
      "bindChannel",
      "deleteChannelBinding",
      // insight
      "cost",
      "budgets",
      "auditSearch",
      "auditExport",
      "runs",
      "createEvalCase",
      "runEval",
      "evalRuns",
      // memory / personal agent
      "configurePersonalAgent",
      "invokePersonalAgent",
      "memoryQuery",
      "memoryFacts",
      "memoryRecall",
      "memoryRemember",
      "memoryForget",
      "memoryIngest",
      "memoryIngestions",
      // me
      "meSettings",
      "putMeSettings",
      "meActivity",
      "meExport",
      "deleteMyConversation",
      "renameConversation",
      "meTokens",
      "mintToken",
      "revokeToken",
      "meConnections",
      "meSessions",
      "revokeSession",
      "meNotifications",
      "putMeNotification",
      "meAgent",
      // admin users / invitations
      "adminUsers",
      "patchUser",
      "adminInvitations",
      "createInvitation",
      "revokeInvitation",
      // auth / 2fa / context
      "login",
      "acceptInvite",
      "logout",
      "twoFactorChallenge",
      "twoFactorEnrollBegin",
      "twoFactorVerifyEnroll",
      "twoFactorDisable",
      "switchActiveContext",
      // workspaces / orgs / ai keys
      "workspaces",
      "createWorkspace",
      "updateWorkspace",
      "workspaceMembers",
      "addWorkspaceMember",
      "removeWorkspaceMember",
      "currentOrg",
      "updateCurrentOrg",
      "orgMembers",
      "aiKeys",
      "setAiKey",
      "deleteAiKey",
    ];

    for (const name of expected) {
      expect(api).toHaveProperty(name);
      expect((api as Record<string, unknown>)[name]).toBeTypeOf("function");
    }
  });
});
