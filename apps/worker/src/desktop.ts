import { Channel, invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { DeviceEnrollmentStart, DeviceRootScope } from "@wlilley93/boltrig-web-sdk";
import workerPackage from "../package.json";

import { configuredApiOrigin } from "./apiOrigin";

export const isDesktop = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
export const workerVersion = workerPackage.version;

export function hasDesktopRuntime(): boolean {
  return isDesktop;
}

export interface DesktopUpdateReadiness {
  runtime: "desktop" | "web";
  state: "ready" | "unavailable";
  current_version: string | null;
  target: string | null;
  endpoint_origin: string | null;
  public_key_fingerprint: string | null;
  reason: string | null;
}

export interface DesktopUpdateCheck {
  status: "current" | "available";
  current_version: string;
  version: string | null;
  notes: string | null;
  published_at: string | null;
}

export type DesktopUpdateProgress =
  | { event: "started"; content_length: number | null }
  | { event: "progress"; chunk_length: number }
  | { event: "download_finished" };

export async function desktopUpdateReadiness(): Promise<DesktopUpdateReadiness> {
  if (!isDesktop) {
    return {
      runtime: "web",
      state: "unavailable",
      current_version: workerVersion,
      target: null,
      endpoint_origin: null,
      public_key_fingerprint: null,
      reason: "desktop_runtime_required",
    };
  }
  const result = await invoke<Omit<DesktopUpdateReadiness, "runtime">>(
    "desktop_update_readiness",
  );
  return { runtime: "desktop", ...result };
}

export async function checkDesktopUpdate(): Promise<DesktopUpdateCheck> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  return invoke<DesktopUpdateCheck>("check_desktop_update");
}

export async function installDesktopUpdate(
  expectedVersion: string,
  onProgress: (event: DesktopUpdateProgress) => void,
): Promise<void> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  const onEvent = new Channel<DesktopUpdateProgress>();
  onEvent.onmessage = onProgress;
  await invoke("install_desktop_update", {
    expectedVersion,
    onEvent,
  });
}

export async function restartDesktopAfterUpdate(): Promise<void> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  await invoke("restart_desktop_after_update");
}

export interface DesktopOAuthReturnReadiness {
  runtime: "desktop" | "web";
  state: "ready" | "unavailable";
  callback_uri: string | null;
  provider_exchange: "unavailable";
  reason: string | null;
}

export interface DesktopOAuthReturnEvent {
  status: "authorization_returned" | "denied";
  integration_id: string;
  provider_exchange: "unavailable";
}

export interface DesktopOAuthReturn {
  status: "authorization_returned" | "denied";
  integration_id: string;
  state: string;
  result: string | null;
  provider_exchange: "unavailable";
}

export async function desktopOAuthReturnReadiness():
Promise<DesktopOAuthReturnReadiness> {
  if (!isDesktop) {
    return {
      runtime: "web",
      state: "unavailable",
      callback_uri: null,
      provider_exchange: "unavailable",
      reason: "desktop_runtime_required",
    };
  }
  const result = await invoke<Omit<DesktopOAuthReturnReadiness, "runtime">>(
    "desktop_oauth_return_readiness",
  );
  return { runtime: "desktop", ...result };
}

export async function armDesktopOAuthReturn(
  integrationId: string,
  state: string,
  expiresAt: string,
): Promise<void> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  await invoke("arm_desktop_oauth_return", {
    integrationId,
    state,
    expiresAt,
  });
}

export async function takeDesktopOAuthReturn(
  integrationId: string,
  expectedState: string,
): Promise<DesktopOAuthReturn | null> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  return invoke<DesktopOAuthReturn | null>("take_desktop_oauth_return", {
    integrationId,
    expectedState,
  });
}

export async function cancelDesktopOAuthReturn(
  integrationId: string,
  expectedState: string,
): Promise<void> {
  if (!isDesktop) throw new Error("desktop_runtime_required");
  await invoke("cancel_desktop_oauth_return", {
    integrationId,
    expectedState,
  });
}

export async function listenDesktopOAuthReturns(
  handler: (event: DesktopOAuthReturnEvent) => void,
): Promise<UnlistenFn> {
  if (!isDesktop) return () => {};
  return listen<DesktopOAuthReturnEvent>(
    "boltrig://oauth-return",
    ({ payload }) => handler(payload),
  );
}

export async function clearDesktopSession(): Promise<void> {
  if (!isDesktop) return;
  await invoke("clear_device_session");
}

export interface DesktopDeviceStatus {
  state: "unenrolled" | "enrolled" | "online" | "degraded" | "reenrollment_required" | string;
  device_id: string | null;
  root_ids: string[];
  reason: string | null;
}

export interface DesktopEnrollmentView {
  device_id: string;
  label: string;
  public_key_fingerprint: string;
  session_expires_at: string;
  lease_verifier_key_id: string;
}

export function serializeDesktopEnrollment(
  enrollment: DeviceEnrollmentStart,
): string {
  return JSON.stringify({
    version: 1,
    authorization_code: enrollment.authorization_code,
    expires_at: enrollment.expires_at,
    verification_uri: enrollment.verification_uri,
    lease_verifier: enrollment.lease_verifier,
  });
}

export function parseDesktopEnrollment(value: string): DeviceEnrollmentStart {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("invalid_device_enrollment_bundle");
  }
  if (!parsed || typeof parsed !== "object") {
    throw new Error("invalid_device_enrollment_bundle");
  }
  const candidate = parsed as Record<string, unknown>;
  const verifier = candidate.lease_verifier;
  if (
    candidate.version !== 1
    || typeof candidate.authorization_code !== "string"
    || candidate.authorization_code.length === 0
    || candidate.authorization_code.length > 4_096
    || /\s/.test(candidate.authorization_code)
    || typeof candidate.expires_at !== "string"
    || typeof candidate.verification_uri !== "string"
    || !verifier
    || typeof verifier !== "object"
  ) {
    throw new Error("invalid_device_enrollment_bundle");
  }
  const verifierFields = verifier as Record<string, unknown>;
  if (
    typeof verifierFields.algorithm !== "string"
    || typeof verifierFields.key_id !== "string"
    || typeof verifierFields.public_key !== "string"
    || !verifierFields.algorithm
    || !verifierFields.key_id
    || !verifierFields.public_key
  ) {
    throw new Error("invalid_device_enrollment_bundle");
  }
  return {
    authorization_code: candidate.authorization_code,
    expires_at: candidate.expires_at,
    verification_uri: candidate.verification_uri,
    lease_verifier: {
      algorithm: verifierFields.algorithm,
      key_id: verifierFields.key_id,
      public_key: verifierFields.public_key,
    },
  };
}

export interface DesktopRootView {
  root_id: string;
  scope: DeviceRootScope;
  command_enabled: boolean;
}

export interface DesktopLeaseTerminal {
  lease_id: string;
  root_id: string;
  verb: "device.file.read" | "device.file.write" | "device.command.run" | string;
  status: string;
  receipt: Record<string, unknown>;
}

export async function desktopDeviceStatus(): Promise<DesktopDeviceStatus | null> {
  if (!isDesktop) return null;
  return invoke<DesktopDeviceStatus>("device_agent_status");
}

export async function completeDesktopEnrollment(
  enrollment: DeviceEnrollmentStart,
): Promise<DesktopEnrollmentView> {
  if (!isDesktop) throw new Error("device_enrollment_requires_desktop");
  const origin = configuredApiOrigin();
  if (!origin) throw new Error("desktop_api_origin_not_configured");
  return invoke<DesktopEnrollmentView>("complete_device_enrollment", {
    apiOrigin: origin,
    authorizationCode: enrollment.authorization_code,
    expectedVerifier: enrollment.lease_verifier,
  });
}

export async function bindDesktopRoot(
  rootId: string,
  scope: DeviceRootScope,
  commandEnabled: boolean,
): Promise<DesktopRootView | null> {
  if (!isDesktop) throw new Error("device_root_binding_requires_desktop");
  return invoke<DesktopRootView | null>("bind_device_root", {
    rootId,
    scope,
    commandEnabled,
  });
}

export async function unbindDesktopRoot(rootId: string): Promise<void> {
  if (!isDesktop) return;
  await invoke("unbind_device_root", { rootId });
}

export async function stageDesktopWrite(bytes: Uint8Array): Promise<{
  content_digest: string;
  byte_size: number;
}> {
  if (!isDesktop) throw new Error("device_write_staging_requires_desktop");
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return invoke("stage_device_write", {
    contentDigest: digest,
    bytes: Array.from(bytes),
  });
}

export async function takeDesktopReadResult(leaseId: string): Promise<Uint8Array | null> {
  if (!isDesktop) return null;
  const result = await invoke<number[] | null>("take_device_read_result", { leaseId });
  return result ? new Uint8Array(result) : null;
}

export async function listenDeviceLeaseTerminals(
  handler: (event: DesktopLeaseTerminal) => void,
): Promise<UnlistenFn> {
  if (!isDesktop) return () => {};
  return listen<DesktopLeaseTerminal>("boltrig://device-lease-terminal", ({ payload }) => handler(payload));
}

export async function listenDesktopDeviceStatus(
  handler: (event: DesktopDeviceStatus) => void,
): Promise<UnlistenFn> {
  if (!isDesktop) return () => {};
  return listen<DesktopDeviceStatus>("boltrig://device-agent-status", ({ payload }) => handler(payload));
}

export type MaterializeArtifactResult =
  | { status: "saved"; handle: string }
  | { status: "cancelled" }
  | { status: "web_fallback" };

export async function materializeArtifact(
  suggestedName: string,
  bytes: Uint8Array,
): Promise<MaterializeArtifactResult> {
  if (!isDesktop) return { status: "web_fallback" };
  const handle = await invoke<string | null>("materialize_artifact", {
    suggestedName,
    bytes: Array.from(bytes),
  });
  return handle === null
    ? { status: "cancelled" }
    : { status: "saved", handle };
}

export async function openMaterializedArtifact(handle: string): Promise<void> {
  if (!isDesktop) return;
  await invoke("open_materialized_artifact", { handle });
}

export async function revealMaterializedArtifact(handle: string): Promise<void> {
  if (!isDesktop) return;
  await invoke("reveal_materialized_artifact", { handle });
}
