import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface DesktopCameraCapability {
  state: string;
  source: string;
  evidence: string[];
  reason: string | null;
}

export interface DesktopCamera {
  camera_id: string;
  descriptor_fingerprint: string;
  label: string;
  manufacturer: string | null;
  product: string;
  transport: string;
  connection_state: string;
  permission: string;
  format_count: number;
  capabilities: Record<string, DesktopCameraCapability>;
  interfaces: string[];
  warnings: string[];
  allowed_verbs: string[];
}

export interface DesktopCameraDiscoveryStatus {
  schema_version: number;
  state: string;
  runtime: string;
  cameras: DesktopCamera[];
  refreshed_at: string;
  reason: string | null;
}

export interface DesktopCameraVerification {
  camera_id: string;
  kind: string;
  state: string;
  control_mechanism: string;
  capture_attempted: boolean;
  writes_attempted: boolean;
  hid_reports_sent: boolean;
  evidence: string[];
  errors: string[];
}

function hasDesktopRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function desktopCameraDiscover(): Promise<DesktopCameraDiscoveryStatus | null> {
  if (!hasDesktopRuntime()) return null;
  return invoke<DesktopCameraDiscoveryStatus>("camera_discover");
}

export async function desktopCameraStatus(): Promise<DesktopCameraDiscoveryStatus | null> {
  if (!hasDesktopRuntime()) return null;
  return invoke<DesktopCameraDiscoveryStatus>("camera_status");
}

export async function verifyDesktopCameraSnapshot(
  cameraId: string,
): Promise<DesktopCameraVerification> {
  if (!hasDesktopRuntime()) throw new Error("camera_verification_requires_desktop");
  return invoke<DesktopCameraVerification>("camera_verify_snapshot", { cameraId });
}

export async function verifyDesktopCameraPtz(
  cameraId: string,
): Promise<DesktopCameraVerification> {
  if (!hasDesktopRuntime()) throw new Error("camera_verification_requires_desktop");
  return invoke<DesktopCameraVerification>("camera_verify_ptz", { cameraId });
}

export async function listenDesktopCameraDiscovery(
  handler: (event: DesktopCameraDiscoveryStatus) => void,
): Promise<UnlistenFn> {
  if (!hasDesktopRuntime()) return () => {};
  return listen<DesktopCameraDiscoveryStatus>(
    "boltrig://camera-discovery-changed",
    ({ payload }) => handler(payload),
  );
}
