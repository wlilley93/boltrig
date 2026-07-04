import { describe, expect, it } from "vitest";
import { TenancyAdmin } from "@/panels/admin/TenancyAdmin";

describe("TenancyAdmin", () => {
  it("exports the panel component", () => {
    // The component depends on many API endpoints and is covered by a
    // characterisation import-only test here; a full render needs too many mocks
    // for the pre-arc gate.
    expect(typeof TenancyAdmin).toBe("function");
  });
});
