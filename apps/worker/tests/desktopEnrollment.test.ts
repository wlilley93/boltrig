import { describe, expect, it } from "vitest";

import {
  parseDesktopEnrollment,
  serializeDesktopEnrollment,
} from "../src/desktop";

const enrollment = {
  authorization_code: "one-time-code",
  expires_at: "2026-07-29T12:00:00Z",
  verification_uri: "/#/settings",
  lease_verifier: {
    algorithm: "Ed25519",
    key_id: "device-lease-v1",
    public_key: "public-key",
  },
};

describe("desktop enrollment handoff", () => {
  it("round-trips the exact code and pinned verifier", () => {
    expect(parseDesktopEnrollment(serializeDesktopEnrollment(enrollment))).toEqual(enrollment);
  });

  it("rejects incomplete, unversioned, or whitespace-bearing bundles", () => {
    expect(() => parseDesktopEnrollment("{}")).toThrow("invalid_device_enrollment_bundle");
    expect(() => parseDesktopEnrollment(JSON.stringify({
      ...JSON.parse(serializeDesktopEnrollment(enrollment)),
      authorization_code: "code with spaces",
    }))).toThrow("invalid_device_enrollment_bundle");
  });
});
