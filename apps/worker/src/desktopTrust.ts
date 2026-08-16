import type { DeviceEnrollmentStart } from "@wlilley93/boltrig-web-sdk";

import { client } from "./client";
import { completeDesktopEnrollment } from "./desktop";

export const DEFAULT_DESKTOP_LABEL = "Boltrig Desktop";

export async function connectAuthenticatedDesktop(
  label = DEFAULT_DESKTOP_LABEL,
) {
  const result = await client.startDeviceEnrollment(label.trim());
  if (!isDeviceEnrollmentStart(result)) {
    throw new Error(
      "reason" in result && typeof result.reason === "string"
        ? result.reason
        : "desktop_connection_unavailable",
    );
  }
  return completeDesktopEnrollment(result);
}

function isDeviceEnrollmentStart(value: unknown): value is DeviceEnrollmentStart {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DeviceEnrollmentStart>;
  return typeof candidate.authorization_code === "string"
    && candidate.authorization_code.length > 0
    && typeof candidate.expires_at === "string"
    && typeof candidate.verification_uri === "string"
    && Boolean(candidate.lease_verifier);
}
