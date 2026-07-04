import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";

describe("api/client (ApiError)", () => {
  it("exposes ApiError with status and body", () => {
    const err = new ApiError(403, "denied", { reason: "no grant" });
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(403);
    expect(err.message).toBe("denied");
    expect(err.body).toEqual({ reason: "no grant" });
  });
});
