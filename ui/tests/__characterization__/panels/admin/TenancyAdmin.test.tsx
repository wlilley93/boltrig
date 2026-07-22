import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TenancyAdmin } from "@/panels/admin/TenancyAdmin";
import { InvitationsCard } from "@/panels/admin/tenancy/Invitations";
import { AiKeysCard } from "@/panels/admin/tenancy/AiKeys";
import { OrgSettingsCard } from "@/panels/admin/tenancy/OrgSettings";
import { UserDirectoryCard } from "@/panels/admin/tenancy/UserDirectory";
import { WorkspacesCard } from "@/panels/admin/tenancy/Workspaces";
import { clearApiMocks, mockApi } from "../../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("TenancyAdmin", () => {
  it("exports the panel component", () => {
    // The component depends on many API endpoints and is covered by a
    // characterisation import-only test here; a full render needs too many mocks
    // for the pre-arc gate.
    expect(typeof TenancyAdmin).toBe("function");
  });

  it("exports every extracted card", () => {
    expect(typeof UserDirectoryCard).toBe("function");
    expect(typeof InvitationsCard).toBe("function");
    expect(typeof OrgSettingsCard).toBe("function");
    expect(typeof WorkspacesCard).toBe("function");
    expect(typeof AiKeysCard).toBe("function");
  });

  it("shows one organisation task at a time", () => {
    mockApi({
      adminUsers: { users: [] },
      adminInvitations: { invitations: [] },
      workspaces: { workspaces: [] },
      aiKeys: { keys: [] },
      capabilities: { verbs: [] },
      currentOrg: { name: "Default" },
      orgMembers: { members: [] },
    });
    const { container } = render(<TenancyAdmin />);

    expect(screen.getByRole("tab", { name: "Members" }).getAttribute("aria-selected")).toBe("true");
    expect(container.querySelector("#organisation-panel-members")?.hasAttribute("hidden")).toBe(false);
    expect(container.querySelector("#organisation-panel-workspaces")?.hasAttribute("hidden")).toBe(true);

    fireEvent.click(screen.getByRole("tab", { name: "Workspaces" }));
    expect(container.querySelector("#organisation-panel-members")?.hasAttribute("hidden")).toBe(true);
    expect(container.querySelector("#organisation-panel-workspaces")?.hasAttribute("hidden")).toBe(false);
  });
});
