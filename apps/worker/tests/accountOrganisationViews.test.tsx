// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  addWorkspaceMember: vi.fn(),
  aiKeyProposal: vi.fn(),
  aiKeyProposals: vi.fn(),
  aiKeys: vi.fn(),
  adminInvitations: vi.fn(),
  adminUsers: vi.fn(),
  artifacts: vi.fn(),
  chatConfig: vi.fn(),
  configurePersonalAgent: vi.fn(),
  conversation: vi.fn(),
  conversations: vi.fn(),
  createInvitation: vi.fn(),
  createWorkspace: vi.fn(),
  currentOrg: vi.fn(),
  deleteMyConversation: vi.fn(),
  deletePersonalAgent: vi.fn(),
  downloadArtifact: vi.fn(),
  invokeApprovalState: vi.fn(),
  meActivity: vi.fn(),
  meAgent: vi.fn(),
  meConnections: vi.fn(),
  myOrganisations: vi.fn(),
  meNotifications: vi.fn(),
  meSessions: vi.fn(),
  meSettings: vi.fn(),
  meTokens: vi.fn(),
  mintToken: vi.fn(),
  modelProfiles: vi.fn(),
  orgMembers: vi.fn(),
  patchUser: vi.fn(),
  putMeNotification: vi.fn(),
  putMeSettings: vi.fn(),
  privacyPolicy: vi.fn(),
  regenerateMessage: vi.fn(),
  removeWorkspaceMember: vi.fn(),
  renameConversation: vi.fn(),
  restoreMyConversation: vi.fn(),
  revokeInvitation: vi.fn(),
  revokeSession: vi.fn(),
  revokeToken: vi.fn(),
  switchActiveContext: vi.fn(),
  switchActiveOrg: vi.fn(),
  testMeNotification: vi.fn(),
  twoFactorDisable: vi.fn(),
  twoFactorEnrollBegin: vi.fn(),
  twoFactorVerifyEnroll: vi.fn(),
  setAiKey: vi.fn(),
  streamChat: vi.fn(),
  deleteAiKey: vi.fn(),
  finalizeAiKeyProposal: vi.fn(),
  invalidateAiKeyProposal: vi.fn(),
  updateCurrentOrg: vi.fn(),
  updateWorkspace: vi.fn(),
  workspaceMembers: vi.fn(),
  workspaces: vi.fn(),
}));
const native = vi.hoisted(() => ({
  materializeArtifact: vi.fn(),
  openMaterializedArtifact: vi.fn(),
  revealMaterializedArtifact: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", () => native);

import { AccountView } from "../src/components/AccountView";
import { ChatView } from "../src/components/ChatView";
import { ConversationControls } from "../src/components/ConversationControls";
import { OrganisationView } from "../src/components/OrganisationView";

const profile = {
  id: "alice",
  email: "alice@example.test",
  display_name: "Alice",
  role: "admin",
  status: "active",
};
const organisation = {
  id: "org-a",
  name: "Acme",
  slug: "acme",
  settings: {},
  allow_own_ai_keys: false,
  require_two_factor: false,
};
const workspace = {
  id: "workspace-a",
  name: "Operations",
  slug: "operations",
  status: "active",
  settings: {},
};

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
  native.materializeArtifact.mockResolvedValue({ status: "web_fallback" });
  native.openMaterializedArtifact.mockResolvedValue(undefined);
  native.revealMaterializedArtifact.mockResolvedValue(undefined);
  api.meSettings.mockResolvedValue({
    profile,
    settings: {
      theme: "system",
      locale: "en-GB",
      timezone: "Europe/London",
    },
    setting_sources: {
      locale: "tenant_default",
      timezone: "tenant_default",
    },
  });
  api.privacyPolicy.mockResolvedValue({
    policy: {
      state: "partial",
      source: "process_start_manifest",
      generation: "privacy-generation",
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
  });
  api.meActivity.mockResolvedValue({ results: [] });
  api.meTokens.mockResolvedValue({
    tokens: [{
      id: "token-a",
      name: "Existing CLI",
      scope: ["work.read"],
      revoked: false,
    }],
  });
  api.meSessions.mockResolvedValue({
    sessions: [{ id: "session-a", client: "Firefox", revoked: false }],
  });
  api.workspaces.mockResolvedValue({ workspaces: [workspace] });
  api.currentOrg.mockResolvedValue({ organisation });
  api.meNotifications.mockResolvedValue({
    prefs: [],
    catalogue: {
      events: [{
        id: "approval",
        label: "Approval requested",
        description: "An action is paused waiting for a person.",
      }],
      transports: [{
        id: "ch-slack",
        platform: "slack",
        label: "Operations",
        delivery_mode: "durable_outbox",
        targets: [{ id: "U-alice", label: "Verified slack identity" }],
      }],
    },
  });
  api.meAgent.mockResolvedValue({ agent: null });
  api.meConnections.mockResolvedValue({
    rest_base: "https://boltrig.example",
    mcp_endpoint: "https://boltrig.example/v1/mcp",
    auth: "Bearer SECRET_MUST_NOT_RENDER",
    snippets: {
      claude_code: "claude mcp add boltrig --header 'Authorization: Bearer <PAT>'",
      curl: "curl https://boltrig.example/v1/capabilities -H 'Authorization: Bearer <PAT>'",
    },
    note: "Mint a scoped PAT.",
  });
  api.myOrganisations.mockResolvedValue({
    organisations: [{ id: organisation.id, active: true }],
  });
  api.aiKeys.mockResolvedValue({ allow_own_ai_keys: false, ai_keys: [] });
  api.aiKeyProposals.mockResolvedValue({ proposals: [] });
  api.aiKeyProposal.mockResolvedValue({ status: "pending" });
  api.invalidateAiKeyProposal.mockResolvedValue({ status: "invalidated" });
  api.orgMembers.mockResolvedValue({
    members: [{ user_id: "alice", role: "admin" }],
  });
  api.workspaceMembers.mockResolvedValue({
    members: [{
      user_id: "alice",
      workspace_id: "workspace-a",
      role: "owner",
      permissions: {},
    }],
  });
  api.adminUsers.mockResolvedValue({ users: [{ ...profile, scope: {} }] });
  api.adminInvitations.mockResolvedValue({ invitations: [] });
  api.artifacts.mockResolvedValue({ artifacts: [] });
  api.chatConfig.mockResolvedValue({
    attachments: {
      max_count: 8,
      max_bytes: 262_144,
      max_total_bytes: 1_048_576,
      model_readable_media_types: ["text/*"],
    },
  });
  api.conversations.mockResolvedValue({
    conversations: [{
      id: "conversation-a",
      title: "Renewals",
      status: "active",
      updated_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.conversation.mockResolvedValue({
    messages: [{
      id: "assistant-a",
      role: "assistant",
      content: "Ready.",
      created_at: "2026-01-01T00:00:00Z",
    }],
  });
  api.modelProfiles.mockResolvedValue({ profiles: [] });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("Worker account surface", () => {
  it("shows the exact partial privacy boundary", async () => {
    render(<AccountView />);

    expect(await screen.findByText("Privacy coverage")).toBeTruthy();
    expect(await screen.findByText("Closed-conversation retention: 30 days")).toBeTruthy();
    expect(screen.getByText("Partial enforcement only")).toBeTruthy();
    expect(screen.getByText(/not a compliance archive/)).toBeTruthy();
  });

  it("shows tenant locale/timezone defaults and saves explicit user overrides", async () => {
    api.putMeSettings.mockResolvedValue({
      status: "ok",
      keys: ["theme", "locale", "timezone"],
    });
    render(<AccountView />);
    await screen.findByText("Alice");

    expect((screen.getByLabelText("Locale") as HTMLInputElement).value).toBe("en-GB");
    expect((screen.getByLabelText("Timezone") as HTMLInputElement).value)
      .toBe("Europe/London");
    expect(screen.getByText(/come from your organisation defaults/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Locale"), {
      target: { value: "fr-FR" },
    });
    fireEvent.change(screen.getByLabelText("Timezone"), {
      target: { value: "Europe/Paris" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: {
        theme: "system",
        locale: "fr-FR",
        timezone: "Europe/Paris",
      },
    }));
  });

  it("applies a saved theme immediately without waiting for a reload", async () => {
    api.putMeSettings.mockResolvedValue({
      status: "ok",
      keys: ["theme", "locale", "timezone"],
    });
    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.change(screen.getByLabelText("Theme"), { target: { value: "dark" } });
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalled());
    expect(localStorage.getItem("boltrig-worker-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("shows a PAT secret once and confirms session revocation", async () => {
    api.mintToken.mockResolvedValue({ status: "ok", secret: "pat_shown_once" });
    api.revokeSession.mockResolvedValue({ status: "ok", id: "session-a" });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    await screen.findByText("https://boltrig.example/v1/mcp");
    expect(document.body.textContent).not.toContain("SECRET_MUST_NOT_RENDER");

    const tokenSection = screen.getByRole("heading", {
      name: "Personal access tokens",
    }).closest("section");
    fireEvent.change(within(tokenSection!).getByLabelText("Token name"), {
      target: { value: "Laptop CLI" },
    });
    fireEvent.click(within(tokenSection!).getByRole("button", { name: "Mint token" }));
    expect(await within(tokenSection!).findByText("pat_shown_once")).toBeTruthy();
    fireEvent.click(within(tokenSection!).getByRole("button", { name: "Copy" }));
    expect(await within(tokenSection!).findByText(/Token copied to the clipboard/))
      .toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("pat_shown_once");
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
      new Error("clipboard denied"),
    );
    fireEvent.click(within(tokenSection!).getByRole("button", { name: "Copy" }));
    expect(await within(tokenSection!).findByText(/token could not be copied/i))
      .toBeTruthy();
    fireEvent.click(within(tokenSection!).getByRole("button", { name: "Dismiss" }));
    expect(within(tokenSection!).queryByText("pat_shown_once")).toBeNull();

    const sessionSection = screen.getByRole("heading", {
      name: "Signed-in sessions",
    }).closest("section");
    fireEvent.click(within(sessionSection!).getByRole("button", { name: "Revoke" }));
    expect(api.revokeSession).not.toHaveBeenCalled();
    fireEvent.click(within(sessionSection!).getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(api.revokeSession).toHaveBeenCalledWith("session-a"));
  });

  it("reports clipboard success and failure for both one-time 2FA values", async () => {
    api.twoFactorEnrollBegin.mockResolvedValue({
      status: "ok",
      secret: "TOTP-SHOWN-ONCE",
      otpauth_uri: "otpauth://totp/Boltrig?secret=TOTP-SHOWN-ONCE",
      recovery_codes: ["recovery-one", "recovery-two"],
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    const section = screen.getByRole("heading", {
      name: "Authenticator and recovery codes",
    }).closest("section")!;
    fireEvent.click(within(section).getByRole("button", {
      name: "Start enrollment",
    }));
    expect(await within(section).findByText("TOTP-SHOWN-ONCE")).toBeTruthy();

    fireEvent.click(within(section).getByRole("button", { name: "Copy secret" }));
    expect(await within(section).findByText(/Authenticator secret copied/))
      .toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("TOTP-SHOWN-ONCE");

    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
      new Error("clipboard denied"),
    );
    fireEvent.click(within(section).getByRole("button", {
      name: "Copy recovery codes",
    }));
    expect(await within(section).findByText(/recovery codes could not be copied/i))
      .toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      "recovery-one\nrecovery-two",
    );
  });

  it("renders pending notification writes and personal-agent lifecycle", async () => {
    api.putMeNotification
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-notification",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.configurePersonalAgent.mockResolvedValue({
      status: "ok",
      id: "agent-a",
      owner: "alice",
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const addRoute = screen.getByRole("button", { name: "Add route" });
    await waitFor(() => expect((addRoute as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(addRoute);
    await screen.findByText("Pending approval in your Inbox.");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.putMeNotification).toHaveBeenNthCalledWith(
      2,
      {
        event_type: "approval",
        channel: "ch-slack",
        target: "U-alice",
        enabled: true,
      },
      "approval-notification",
    ));
    await screen.findByText("Notification route saved.");

    fireEvent.click(screen.getByRole("button", { name: "Personal agent" }));
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
    await waitFor(() => expect(api.configurePersonalAgent).toHaveBeenCalledWith({
      runtime: "codex",
      skills: [],
    }));
  });

  it("refuses a pending notification approval after its exact route input changes", async () => {
    api.putMeNotification.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-stale-notification",
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const addRoute = screen.getByRole("button", { name: "Add route" });
    await waitFor(() => expect((addRoute as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(addRoute);
    await screen.findByText("Notification route change is waiting for approval");

    fireEvent.change(screen.getByLabelText("Notification target"), {
      target: { value: "different-target" },
    });
    await screen.findByText("Notification route change changed");
    expect(screen.queryByRole("button", {
      name: "Check approval and apply exact change",
    })).toBeNull();
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
    expect(api.putMeNotification).toHaveBeenCalledTimes(1);
  });

  it("offers only server-deliverable notification routes and reports test status", async () => {
    api.meNotifications.mockResolvedValue({
      catalogue: {
        events: [{
          id: "approval",
          label: "Approval requested",
          description: "An action is paused waiting for a person.",
        }],
        transports: [{
          id: "ch-slack",
          platform: "slack",
          label: "Operations",
          delivery_mode: "durable_outbox",
          targets: [{ id: "U-alice", label: "Verified slack identity" }],
        }],
      },
      prefs: [{
        id: "pref-a",
        event_type: "approval",
        channel: "ch-slack",
        target: "U-alice",
        enabled: true,
        deliverable: true,
        last_delivery: null,
      }],
    });
    api.testMeNotification.mockResolvedValue({
      status: "ok",
      delivery_id: "co-test",
      delivery_status: "queued",
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByRole("option", { name: "Approval requested" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Email" })).toBeNull();
    expect(screen.queryByRole("option", { name: "In-app" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    await waitFor(() => expect(api.testMeNotification).toHaveBeenCalledWith("pref-a"));
    await screen.findByText(/Test queued/);
  });

  it("clears AI-key plaintext before awaiting and applies only the recovered sealed proposal", async () => {
    const staged = {
      id: "akp-proposal-a",
      level: "user",
      scope_id: "alice",
      provider: "openai",
      model: "gpt-5",
      base_url: null,
      status: "pending",
      created_at: "2026-01-01T00:00:00Z",
      expires_at: "2026-01-01T00:15:00Z",
    };
    api.aiKeys.mockResolvedValue({ allow_own_ai_keys: true, ai_keys: [] });
    api.setAiKey.mockResolvedValue({
      status: "pending_human",
      proposal: staged,
    });
    api.aiKeyProposal.mockResolvedValue({
      status: "approved",
      proposal: { ...staged, status: "approved" },
    });
    api.finalizeAiKeyProposal.mockResolvedValue({
      status: "ok",
      proposal_id: staged.id,
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    const keyInput = await screen.findByLabelText("API key (write only)");
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "gpt-5" },
    });
    fireEvent.change(keyInput, { target: { value: "sk-browser-only" } });
    fireEvent.click(screen.getByRole("button", { name: "Seal key for approval" }));

    await waitFor(() => expect(api.setAiKey).toHaveBeenCalledWith({
      level: "user",
      scope_id: undefined,
      provider: "openai",
      model: "gpt-5",
      base_url: undefined,
      api_key: "sk-browser-only",
    }));
    expect((keyInput as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("sk-browser-only");
    await screen.findByText("Sealed key proposal is waiting for approval");

    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply sealed key",
    }));
    await waitFor(() => expect(api.aiKeyProposal).toHaveBeenCalledWith(staged.id));
    await waitFor(() => expect(api.finalizeAiKeyProposal).toHaveBeenCalledWith(staged.id));
    await screen.findByText("Approved AI key installed from its sealed proposal.");
  });

  it("invalidates staged AI-key material when any proposal input changes", async () => {
    const staged = {
      id: "akp-proposal-edit",
      level: "user",
      scope_id: "alice",
      provider: "openai",
      model: "gpt-5",
      status: "pending",
      created_at: "2026-01-01T00:00:00Z",
      expires_at: "2026-01-01T00:15:00Z",
    };
    api.aiKeys.mockResolvedValue({ allow_own_ai_keys: true, ai_keys: [] });
    api.setAiKey.mockResolvedValue({
      status: "pending_human",
      proposal: staged,
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    fireEvent.change(await screen.findByLabelText("Model"), {
      target: { value: "gpt-5" },
    });
    fireEvent.change(screen.getByLabelText("API key (write only)"), {
      target: { value: "sk-edit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Seal key for approval" }));
    await screen.findByText("Sealed key proposal is waiting for approval");

    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "anthropic" },
    });
    await screen.findByText("Sealed key proposal was invalidated");
    await waitFor(() => expect(api.invalidateAiKeyProposal).toHaveBeenCalledWith(
      staged.id,
    ));
    expect(api.aiKeyProposal).not.toHaveBeenCalled();
    expect(api.finalizeAiKeyProposal).not.toHaveBeenCalled();
  });

  it.each([
    ["rejected", "Sealed key proposal was rejected"],
    ["expired", "Sealed key proposal expired"],
    ["consumed", "Sealed key proposal was already consumed"],
    ["unavailable", "Sealed key proposal state is unavailable"],
  ])("recovers %s sealed-proposal state after navigation", async (status, copy) => {
    api.aiKeys.mockResolvedValue({ allow_own_ai_keys: true, ai_keys: [] });
    api.aiKeyProposals.mockResolvedValue({
      proposals: [{
        id: `akp-${status}`,
        level: "user",
        scope_id: "alice",
        provider: "openai",
        model: "gpt-5",
        status,
        created_at: "2026-01-01T00:00:00Z",
        expires_at: "2026-01-01T00:15:00Z",
      }],
    });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    expect(await screen.findByText(copy)).toBeTruthy();
  });

  it("finalizes non-secret AI-key deletion through the shared exact lane", async () => {
    api.aiKeys.mockResolvedValue({
      allow_own_ai_keys: true,
      ai_keys: [{
        level: "user",
        scope_id: "alice",
        provider: "openai",
        model: "gpt-5",
        has_key: true,
      }],
    });
    api.deleteAiKey
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-delete-key",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<AccountView />);
    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Access" }));
    const remove = await screen.findByRole("button", { name: "Remove" });
    fireEvent.click(remove);
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
    await screen.findByText("AI key removal is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.deleteAiKey).toHaveBeenNthCalledWith(
      2,
      "user",
      "alice",
      "approval-delete-key",
    ));
  });
});

describe("Worker organisation surface", () => {
  it("keeps denied or pending admin writes explicit", async () => {
    api.createInvitation
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-a",
      })
      .mockResolvedValueOnce({
        status: "ok",
        id: "invite-a",
        invite_token: "approved_invite_token",
      });
    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Administration" }));
    const inviteSection = await screen.findByRole("heading", { name: "Invite-only access" });
    fireEvent.change(within(inviteSection.closest("section")!).getByLabelText("Invitation email"), {
      target: { value: "new@example.test" },
    });
    fireEvent.click(within(inviteSection.closest("section")!).getByRole("button", {
      name: "Invite",
    }));
    await screen.findByText("Pending approval in your Inbox.");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.createInvitation).toHaveBeenNthCalledWith(
      2,
      {
        email: "new@example.test",
        role: "viewer",
        scope: {},
        ttl_days: 14,
        workspace_id: undefined,
        provision_workspace_name: undefined,
        provision_org_name: undefined,
      },
      "approval-a",
    ));
    expect(await screen.findByText("approved_invite_token")).toBeTruthy();
  });

  it("refuses a pending directory approval after an edited scope draft", async () => {
    api.patchUser.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-user-scope",
    });
    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Administration" }));
    const scope = await screen.findByLabelText("Scope for alice");
    fireEvent.change(scope, { target: { value: '{"departments":["ops"]}' } });
    fireEvent.click(screen.getByRole("button", { name: "Save scope" }));
    await screen.findByText("User scope change is waiting for approval");

    fireEvent.change(scope, { target: { value: '{"departments":["finance"]}' } });
    await screen.findByText("User scope change changed");
    expect(api.patchUser).toHaveBeenCalledTimes(1);
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
  });

  it("requires confirmation before archiving a workspace", async () => {
    api.updateWorkspace
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-workspace-archive",
      })
      .mockResolvedValueOnce({ status: "ok", workspace: { ...workspace, status: "archived" } });
    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    const archive = await screen.findByRole("button", { name: "Archive workspace" });
    fireEvent.click(archive);
    expect(api.updateWorkspace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm archive workspace" }));
    await waitFor(() => expect(api.updateWorkspace).toHaveBeenNthCalledWith(
      1,
      "workspace-a",
      { status: "archived" },
    ));
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.updateWorkspace).toHaveBeenNthCalledWith(
      2,
      "workspace-a",
      { status: "archived" },
      "approval-workspace-archive",
    ));
    await screen.findByText("Workspace archived.");
  });

  it("refuses a pending workspace approval after its form changes", async () => {
    api.updateWorkspace.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval-workspace-details",
    });
    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Workspaces" }));
    const workspaceName = await screen.findByLabelText("Workspace name");
    fireEvent.change(workspaceName, { target: { value: "Operations v2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save workspace details" }));
    await screen.findByText("Workspace detail change is waiting for approval");

    fireEvent.change(workspaceName, { target: { value: "Operations v3" } });
    await screen.findByText("Workspace detail change changed");
    expect(api.updateWorkspace).toHaveBeenCalledTimes(1);
    expect(api.invokeApprovalState).not.toHaveBeenCalled();
  });

  it("passes scoped, expiring workspace provisioning and shows the invite token once", async () => {
    api.meSettings.mockResolvedValue({
      profile: { ...profile, role: "superadmin" },
      settings: {},
    });
    api.createInvitation.mockResolvedValue({
      status: "ok",
      id: "invite-a",
      invite_token: "invite_shown_once",
    });

    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Administration" }));
    const section = (await screen.findByRole("heading", { name: "Invite-only access" })).closest("section")!;
    fireEvent.change(within(section).getByLabelText("Invitation email"), {
      target: { value: "new@example.test" },
    });
    fireEvent.change(within(section).getByLabelText("Invitation expiry days"), {
      target: { value: "5" },
    });
    fireEvent.change(within(section).getByLabelText("Invitation scope"), {
      target: { value: '{"departments":["ops"]}' },
    });
    fireEvent.change(within(section).getByLabelText("Existing workspace id (optional)"), {
      target: { value: "workspace-a" },
    });
    fireEvent.change(within(section).getByLabelText("Provision organisation on acceptance (owner only)"), {
      target: { value: "Subsidiary" },
    });
    fireEvent.click(within(section).getByRole("button", { name: "Invite" }));

    await waitFor(() => expect(api.createInvitation).toHaveBeenCalledWith({
      email: "new@example.test",
      role: "viewer",
      scope: { departments: ["ops"] },
      ttl_days: 5,
      workspace_id: "workspace-a",
      provision_workspace_name: undefined,
      provision_org_name: "Subsidiary",
    }));
    expect(await within(section).findByText("invite_shown_once")).toBeTruthy();
    fireEvent.click(within(section).getByRole("button", {
      name: "Copy invitation link",
    }));
    expect(await within(section).findByText("Invitation link copied to the clipboard."))
      .toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining(
        "#/accept-invite?token=invite_shown_once",
      ),
    );
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
      new Error("clipboard denied"),
    );
    fireEvent.click(within(section).getByRole("button", {
      name: "Copy invitation link",
    }));
    expect(await within(section).findByText(/invitation link could not be copied/i))
      .toBeTruthy();
    fireEvent.click(within(section).getByRole("button", { name: "Dismiss" }));
    expect(within(section).queryByText("invite_shown_once")).toBeNull();
  });

  it("updates complete user scope and explicitly confirms reactivation", async () => {
    api.adminUsers.mockResolvedValue({
      users: [{ ...profile, status: "deactivated", scope: { departments: ["old"] } }],
    });
    api.patchUser.mockResolvedValue({ status: "ok" });

    render(<OrganisationView />);
    await screen.findByRole("heading", { name: "Acme" });
    fireEvent.click(screen.getByRole("button", { name: "Administration" }));
    const scope = await screen.findByLabelText("Scope for alice");
    fireEvent.change(scope, { target: { value: '{"departments":["ops"]}' } });
    fireEvent.click(screen.getByRole("button", { name: "Save scope" }));
    await waitFor(() => expect(api.patchUser).toHaveBeenCalledWith("alice", {
      scope: { departments: ["ops"] },
    }));

    fireEvent.click(screen.getByRole("button", { name: "Reactivate" }));
    expect(api.patchUser).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Confirm reactivate" }));
    await waitFor(() => expect(api.patchUser).toHaveBeenCalledWith("alice", {
      status: "active",
    }));
  });
});

describe("Worker conversation management", () => {
  it("confirms destructive close and keeps regenerate owner-scoped", async () => {
    api.regenerateMessage.mockResolvedValue({ status: "denied", reason: "not your conversation" });
    api.deleteMyConversation.mockResolvedValue({ status: "ok", id: "conversation-a" });
    render(
      <ConversationControls
        conversationId="conversation-a"
        title="Renewals"
        status="active"
        lastAssistantMessageId="assistant-a"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Regenerate last response" }));
    await screen.findByText("not your conversation");
    fireEvent.click(screen.getByRole("button", { name: "Close conversation" }));
    expect(api.deleteMyConversation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm close conversation" }));
    await waitFor(() => expect(api.deleteMyConversation).toHaveBeenCalledWith("conversation-a"));
  });

  it("makes a closed transcript restore-only", async () => {
    api.restoreMyConversation.mockResolvedValue({
      status: "ok",
      id: "conversation-a",
      conversation_status: "active",
    });
    const onChanged = vi.fn();
    render(
      <ConversationControls
        conversationId="conversation-a"
        title="Renewals"
        status="closed"
        lastAssistantMessageId="assistant-a"
        onChanged={onChanged}
      />,
    );

    expect(screen.getByText(/read-only during its retention grace window/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Regenerate last response" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close conversation" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Restore conversation" }));
    await waitFor(() => expect(api.restoreMyConversation).toHaveBeenCalledWith("conversation-a"));
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("clears busy state and announces rejected conversation mutations", async () => {
    api.renameConversation.mockRejectedValueOnce(new Error("offline"));
    api.regenerateMessage.mockRejectedValueOnce(new Error("offline"));
    api.deleteMyConversation.mockRejectedValueOnce(new Error("offline"));
    api.restoreMyConversation.mockRejectedValueOnce(new Error("offline"));
    const { rerender } = render(
      <ConversationControls
        conversationId="conversation-a"
        title="Renewals"
        status="active"
        lastAssistantMessageId="assistant-a"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save title" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/safe to retry/i);
    expect((screen.getByRole("button", { name: "Save title" }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Regenerate last response" }));
    expect(await screen.findByText("The response could not be regenerated. It is safe to retry.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Regenerate last response" }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Close conversation" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm close conversation" }));
    expect(await screen.findByText("The conversation could not be closed. It is safe to retry.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Confirm close conversation" }) as HTMLButtonElement).disabled).toBe(false);

    rerender(
      <ConversationControls
        conversationId="conversation-a"
        title="Renewals"
        status="closed"
        lastAssistantMessageId="assistant-a"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Restore conversation" }));
    expect(await screen.findByText("The conversation could not be restored. It is safe to retry.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Restore conversation" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("opens compact task details as a dismissible focus-managed dialog", async () => {
    stubCompactViewport();
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    const trigger = await screen.findByRole("button", { name: "Task details" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    const hiddenSheet = document.getElementById("worker-task-details");
    expect(hiddenSheet?.hasAttribute("inert")).toBe(true);
    expect(hiddenSheet?.querySelectorAll("button").length).toBeGreaterThan(0);
    fireEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: "Task details" })).toBeTruthy();
    expect(hiddenSheet?.hasAttribute("inert")).toBe(false);
    const close = screen.getByRole("button", { name: "Close task details" });
    await waitFor(() => expect(document.activeElement).toBe(close));
    expect(document.body.style.overflow).toBe("hidden");
    const dialogButtons = screen.getByRole("dialog", { name: "Task details" })
      .querySelectorAll<HTMLButtonElement>("button:not([disabled])");
    const last = dialogButtons[dialogButtons.length - 1];
    last.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Task details" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(hiddenSheet?.hasAttribute("inert")).toBe(true);
    expect(document.body.style.overflow).toBe("");

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss task details" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Task details" })).toBeNull());
  });

  it("keeps restore controls reachable in compact task details", async () => {
    stubCompactViewport();
    api.conversations.mockResolvedValue({
      conversations: [{
        id: "conversation-a",
        title: "Renewals",
        status: "closed",
        updated_at: "2026-01-01T00:00:00Z",
      }],
    });
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Task details" }));
    expect(await screen.findByRole("button", { name: "Restore conversation" })).toBeTruthy();
  });

  it("refreshes a closed conversation in place without reloading the page", async () => {
    api.deleteMyConversation.mockResolvedValue({ status: "ok", id: "conversation-a" });
    api.conversations
      .mockResolvedValueOnce({
        conversations: [{
          id: "conversation-a",
          title: "Renewals",
          status: "active",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })
      .mockResolvedValueOnce({
        conversations: [{
          id: "conversation-a",
          title: "Renewals",
          status: "closed",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      });
    const onChanged = vi.fn();
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={onChanged}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Close conversation" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm close conversation" }));
    expect(await screen.findByRole("heading", { name: "Closed conversation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Restore conversation" })).toBeTruthy();
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("does not submit the composer while an IME composition is active", async () => {
    api.streamChat.mockResolvedValue(undefined);
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    const composer = await screen.findByRole("textbox", { name: "Task instructions" });
    fireEvent.change(composer, { target: { value: "still composing" } });
    fireEvent.keyDown(composer, { key: "Enter", code: "Enter", isComposing: true });
    expect(api.streamChat).not.toHaveBeenCalled();

    fireEvent.keyDown(composer, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledOnce());
  });

  it("shows artifact download failures inside task details", async () => {
    api.artifacts.mockResolvedValue({
      artifacts: [{
        id: "artifact-a",
        owner_id: "alice",
        name: "brief.md",
        digest: "sha256:artifact-a",
        media_type: "text/markdown",
        size: 10,
        revision: 1,
        provenance: { kind: "agent" },
        created_at: "2026-01-01T00:00:00Z",
      }],
    });
    api.downloadArtifact.mockRejectedValueOnce(new Error("offline"));
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /brief\.md/i }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The artifact could not be downloaded. It is safe to retry.",
    );
  });

  it("offers native open and reveal only after a user-chosen artifact save", async () => {
    api.artifacts.mockResolvedValue({
      artifacts: [{
        id: "artifact-a",
        owner_id: "alice",
        name: "brief.md",
        digest: "sha256:artifact-a",
        media_type: "text/markdown",
        size: 10,
        revision: 1,
        provenance: { kind: "agent" },
        created_at: "2026-01-01T00:00:00Z",
      }],
    });
    api.downloadArtifact.mockResolvedValue(new Uint8Array([1, 2, 3]));
    native.materializeArtifact.mockResolvedValue({
      status: "saved",
      handle: "opaque-native-handle",
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: /brief\.md/i }));
    expect(await screen.findByRole("button", { name: "Open" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));

    await waitFor(() => {
      expect(native.openMaterializedArtifact)
        .toHaveBeenCalledWith("opaque-native-handle");
      expect(native.revealMaterializedArtifact)
        .toHaveBeenCalledWith("opaque-native-handle");
    });
  });

  it("honours native artifact save cancellation without starting a web download", async () => {
    api.artifacts.mockResolvedValue({
      artifacts: [{
        id: "artifact-a",
        owner_id: "alice",
        name: "brief.md",
        digest: "sha256:artifact-a",
        media_type: "text/markdown",
        size: 10,
        revision: 1,
        provenance: { kind: "agent" },
        created_at: "2026-01-01T00:00:00Z",
      }],
    });
    api.downloadArtifact.mockResolvedValue(new Uint8Array([1, 2, 3]));
    native.materializeArtifact.mockResolvedValue({ status: "cancelled" });
    const browserDownload = vi.spyOn(HTMLAnchorElement.prototype, "click");

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /brief\.md/i }));
    await waitFor(() => expect(native.materializeArtifact).toHaveBeenCalled());
    expect(browserDownload).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
  });

  it("is wired into the live chat rail for the last eligible assistant message", async () => {
    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByRole("button", {
      name: "Regenerate last response",
    })).toBeTruthy();
    expect(screen.getByLabelText("Conversation title")).toBeTruthy();
  });

  it("loads further artifact pages without replacing the first page", async () => {
    const artifact = (id: string, name: string) => ({
      id,
      owner_id: "alice",
      name,
      digest: `sha256:${id}`,
      media_type: "text/markdown",
      size: 10,
      revision: 1,
      provenance: { kind: "agent" },
      created_at: "2026-01-01T00:00:00Z",
    });
    api.artifacts
      .mockResolvedValueOnce({
        artifacts: [artifact("artifact-a", "brief.md")],
        next_cursor: "cursor/artifact-a",
      })
      .mockResolvedValueOnce({
        artifacts: [artifact("artifact-b", "appendix.md")],
        next_cursor: null,
      });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("brief.md")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Load more artifacts" }));
    expect(await screen.findByText("appendix.md")).toBeTruthy();
    expect(screen.getByText("brief.md")).toBeTruthy();
    expect(api.artifacts).toHaveBeenLastCalledWith({
      conversationId: "conversation-a",
      limit: 25,
      cursor: "cursor/artifact-a",
    });
    expect(screen.queryByRole("button", { name: "Load more artifacts" })).toBeNull();
  });

  it("uses emitted Familiar identity and leaves the root activity orb unbound", async () => {
    api.conversation.mockResolvedValue({
      messages: [{
        id: "assistant-a",
        role: "assistant",
        content: "Ready.",
        created_at: "2026-01-01T00:00:00Z",
        events: [{
          type: "subagent",
          child_run_id: "run-child",
          task: "Handle the turn",
          name: "local-worker",
          spawn_rule: {
            id: "research-route",
            priority: 50,
            matched_intent_tags: ["analysis", "research"],
            capability: "local-worker",
            skills_added: ["analysis/research"],
            max_depth: 2,
          },
          familiar_genotype: {
            source: "agent_capability.name.v1",
            palette: ["#112233", "#445566", "#778899"],
          },
        }, {
          type: "message_end",
          run_id: "run-parent",
        }],
      }],
    });

    render(
      <ChatView
        conversationId="conversation-a"
        onConversation={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    const profile = await screen.findByRole("img", {
      name: "local-worker Familiar · ready",
    });
    expect(profile.dataset.genotypeSource).toBe("agent_capability.name.v1");
    expect(profile.getAttribute("style")).toContain("#112233");
    expect(screen.getByText(/policy research-route/)).toBeTruthy();
    const root = screen.getByRole("img", { name: "Boltrig activity · ready" });
    expect(root.dataset.genotypeSource).toBe("unbound");
    expect(root.getAttribute("style")).toBeNull();
  });
});

function stubCompactViewport() {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 1020px)",
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}
