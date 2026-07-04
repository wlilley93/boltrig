import { describe, expect, it } from "vitest";
import { TenancyAdmin } from "@/panels/admin/TenancyAdmin";
import { InvitationsCard } from "@/panels/admin/tenancy/Invitations";
import { AiKeysCard } from "@/panels/admin/tenancy/AiKeys";
import { OrgSettingsCard } from "@/panels/admin/tenancy/OrgSettings";
import { UserDirectoryCard } from "@/panels/admin/tenancy/UserDirectory";
import { WorkspacesCard } from "@/panels/admin/tenancy/Workspaces";

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
});
