import { describe, expect, it } from "vitest";
import { ADMIN_ROLES, App, AUTHOR_ROLES } from "@/App";
import { AppSidebar } from "@/app/AppSidebar";
import { AppTopbar } from "@/app/AppTopbar";
import { BoltMark } from "@/app/BoltMark";
import { HINT, ICON } from "@/app/navMeta";
import { IdentityBar } from "@/app/IdentityBar";
import { IdentityChip } from "@/app/IdentityChip";
import { OpsGroup } from "@/app/OpsGroup";
import { ZoneGroup } from "@/app/ZoneGroup";
import { renderCell } from "@/app/renderCell";
import { PRIMARY_NAV } from "@/app/navigation";

describe("App", () => {
  it("exports the root component and role sets", () => {
    expect(typeof App).toBe("function");
    expect(ADMIN_ROLES).toBeInstanceOf(Set);
    expect(AUTHOR_ROLES).toBeInstanceOf(Set);
  });

  it("exposes every extracted app-shell unit", () => {
    expect(typeof AppSidebar).toBe("function");
    expect(typeof AppTopbar).toBe("function");
    expect(typeof BoltMark).toBe("function");
    expect(typeof IdentityChip).toBe("function");
    expect(typeof IdentityBar).toBe("function");
    expect(typeof OpsGroup).toBe("function");
    expect(typeof ZoneGroup).toBe("function");
    expect(typeof renderCell).toBe("function");
    expect(typeof HINT).toBe("object");
    expect(typeof ICON).toBe("object");
    expect(PRIMARY_NAV).toHaveLength(5);
  });
});
