import type { EnrolledDevice } from "@wlilley93/boltrig-web-sdk";

import type { DesktopDeviceStatus } from "../desktop";

export function needsLocalEnrollmentCleanup({
  available, desktop, devicesLoaded, localServerDevice, nativeStatus,
}: {
  available: boolean;
  desktop: boolean;
  devicesLoaded: boolean;
  localServerDevice: EnrolledDevice | null;
  nativeStatus: DesktopDeviceStatus | null;
}) {
  return desktop && (
    nativeStatus?.state === "reenrollment_required"
    || Boolean(nativeStatus?.device_id && devicesLoaded && available && !localServerDevice)
  );
}

export function desktopConnectionVisible(desktop: boolean, downloadUrl: string | null) {
  return desktop || Boolean(downloadUrl);
}

export function trustedComputersVisible(available: boolean, error: string) {
  return available || Boolean(error);
}
