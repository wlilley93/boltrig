import { describe, expect, it } from "vitest";
import { ADMIN_ROLES, App, AUTHOR_ROLES } from "@/App";

describe("App", () => {
  it("exports the root component and role sets", () => {
    expect(typeof App).toBe("function");
    expect(ADMIN_ROLES).toBeInstanceOf(Set);
    expect(AUTHOR_ROLES).toBeInstanceOf(Set);
  });
});
